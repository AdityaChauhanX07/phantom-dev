"""
phantom.py — main entry point for the Phantom-Dev executor.

Ties together WebSocket transport, playbook management, and task execution.

PHANTOM_MODE=local  → run a single goal directly via TaskOrchestrator (no WebSocket)
PHANTOM_MODE=cloud  → connect to the agent backend and execute tasks on demand

Usage
-----
  # local (goal from CLI arg):
  python phantom.py "Open Notepad and type Hello World"

  # local (goal from prompt):
  python phantom.py

  # cloud:
  PHANTOM_MODE=cloud python phantom.py
"""

import asyncio
import json
import logging
import os
import sys

from dotenv import load_dotenv

from orchestrator import TaskOrchestrator
from playbook_manager import PlaybookManager
from ws_client import PhantomWSClient

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("phantom")


def _print_state_summary(state: dict) -> None:
    """Print a compact human-readable summary of a finished task state."""
    print("\n" + "=" * 60)
    print(f"  STATUS : {state['status'].upper()}")
    print(f"  GOAL   : {state['goal']}")
    print(f"  DONE   : {len(state['steps_completed'])} step(s)")
    print(f"  FAILED : {len(state['steps_failed'])} step(s)")

    corrections = state.get("correction_history", [])
    if corrections:
        print(f"  FIXES  : {len(corrections)} correction attempt(s)")

    if state["steps_completed"]:
        print("\n  Completed steps:")
        for s in state["steps_completed"]:
            print(f"    [OK ] {s['step']}. {s['description']}")

    if state["steps_failed"]:
        print("\n  Failed steps:")
        for s in state["steps_failed"]:
            print(f"    [ERR] {s['step']}. {s['description']}")

    print("=" * 60 + "\n")


class PhantomExecutor:
    """
    Top-level executor that orchestrates task execution in either
    local or cloud mode.

    Attributes:
        ws:           WebSocket client (used in cloud mode).
        pm:           PlaybookManager for saving/loading task traces.
        running:      True while the cloud loop is active.
        current_task: Goal string of the task currently executing, or None.
    """

    def __init__(self):
        self.ws = PhantomWSClient()
        self.pm = PlaybookManager()
        self.running: bool = False
        self.current_task: str | None = None
        self._mode: str = os.getenv("PHANTOM_MODE", "local").lower()
        logger.info("[PhantomExecutor] mode=%s", self._mode)

    # ------------------------------------------------------------------ #
    # Local mode                                                           #
    # ------------------------------------------------------------------ #

    async def run_local(self, goal: str) -> dict:
        """
        Execute *goal* directly via TaskOrchestrator without a WebSocket.

        Args:
            goal: Natural-language task description.

        Returns:
            Final task state dict from the orchestrator.
        """
        self.current_task = goal
        logger.info("[PhantomExecutor] Running locally: %r", goal)

        orchestrator = TaskOrchestrator(goal)
        state = orchestrator.run()   # blocking — TaskOrchestrator is sync

        _print_state_summary(state)
        self.current_task = None
        return state

    # ------------------------------------------------------------------ #
    # Cloud mode                                                           #
    # ------------------------------------------------------------------ #

    async def run_cloud(self) -> None:
        """
        Connect to the agent backend and execute tasks received over WebSocket.

        Runs until a ``"shutdown"`` message is received or the connection drops.
        """
        await self.ws.connect()
        self.running = True
        logger.info("[PhantomExecutor] Phantom is online. Waiting for tasks...")

        try:
            while self.running:
                # Block until any message arrives (no timeout — agent drives pacing)
                try:
                    message = await asyncio.wait_for(
                        self.ws._inbox.get(), timeout=60.0
                    )
                except asyncio.TimeoutError:
                    # Heartbeat gap — check connection state and loop back
                    if not self.ws.connected:
                        logger.warning(
                            "[PhantomExecutor] WebSocket disconnected during wait. Stopping."
                        )
                        break
                    continue

                msg_type = message.get("type")

                if msg_type == "task":
                    goal = message.get("goal") or message.get("data", {}).get("goal", "")
                    if not goal:
                        logger.warning(
                            "[PhantomExecutor] Received task message with no goal: %s",
                            json.dumps(message),
                        )
                        continue

                    logger.info("[PhantomExecutor] Received task: %r", goal)
                    self.current_task = goal

                    orchestrator = TaskOrchestrator(goal)
                    state = orchestrator.run()   # sync — runs in the event loop thread
                    _print_state_summary(state)
                    self.current_task = None

                    await self.ws.send_task_result(state)

                elif msg_type == "shutdown":
                    logger.info("[PhantomExecutor] Shutdown command received.")
                    self.running = False
                    break

                else:
                    logger.debug(
                        "[PhantomExecutor] Ignoring unknown message type: %r", msg_type
                    )

        finally:
            self.running = False
            await self.ws.disconnect()

    # ------------------------------------------------------------------ #
    # Entry point                                                          #
    # ------------------------------------------------------------------ #

    def start(self) -> None:
        """
        Read ``PHANTOM_MODE`` and start the appropriate execution loop.

        - ``local``: executes one goal then exits.
        - ``cloud``: connects to the backend and runs until shutdown.
        """
        if self._mode == "cloud":
            asyncio.run(self.run_cloud())
        else:
            # Local mode — goal from CLI arg or interactive prompt
            if len(sys.argv) > 1:
                goal = " ".join(sys.argv[1:])
            else:
                try:
                    goal = input("What should Phantom do? ").strip()
                except (EOFError, KeyboardInterrupt):
                    print()
                    logger.info("[PhantomExecutor] No goal provided. Exiting.")
                    return

            if not goal:
                logger.warning("[PhantomExecutor] Empty goal. Exiting.")
                return

            asyncio.run(self.run_local(goal))


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    PhantomExecutor().start()
