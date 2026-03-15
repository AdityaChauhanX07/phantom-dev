# Requires AGENT_WS_URL in .env — defaults to ws://localhost:8000/ws
"""
PhantomWSClient — WebSocket client connecting the local executor to the
cloud agent backend.

Message contract
----------------
Outbound (executor → agent):
  {"type": "screenshot",  "task_id": str, "data": <b64>}
  {"type": "task_result", "task_id": str, "data": {"status": str, "goal": str}}

Inbound (agent → executor):
  {"type": "task",   "task_id": str, "goal": str, "session_id": str}
  {"type": "action", ...action fields...}
  (other types are silently discarded)
"""

import asyncio
import json
import logging
import os
import ssl

import websockets
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

_DEFAULT_URL = "ws://localhost:8000/ws"
_MAX_RETRIES = 5
_RETRY_DELAY = 3.0   # seconds between connection attempts


class PhantomWSClient:
    """
    Async WebSocket client that bridges the local executor and the cloud agent.

    Usage::

        client = PhantomWSClient()
        await client.connect()

        await client.send_screenshot(b64_frame, task_id="task-001")
        action = await client.receive_action(timeout=30.0)

        await client.send_task_result(final_state)
        await client.disconnect()
    """

    def __init__(self, agent_url: str = None):
        env_url = os.getenv("AGENT_WS_URL", _DEFAULT_URL)
        self.url: str = agent_url or env_url
        self.websocket = None
        self.connected: bool = False
        self._inbox: asyncio.Queue = asyncio.Queue()
        self._listener_task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None
        logger.debug("[PhantomWSClient] Target URL: %s", self.url)

    # ------------------------------------------------------------------ #
    # Connection management                                                #
    # ------------------------------------------------------------------ #

    async def connect(self) -> None:
        """
        Open the WebSocket connection with automatic retry and exponential backoff.

        Retries up to ``_MAX_RETRIES`` times with exponential backoff
        between attempts.  Raises ``ConnectionError`` if all attempts fail.
        """
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                # Create SSL context for wss:// connections
                ssl_context = None
                if self.url.startswith("wss://"):
                    ssl_context = ssl.create_default_context()
                    # For Cloud Run, we may need to disable certificate verification
                    # (Cloud Run uses Google-managed certificates)
                    ssl_context.check_hostname = False
                    ssl_context.verify_mode = ssl.CERT_NONE
                
                self.websocket = await websockets.connect(
                    self.url,
                    ssl=ssl_context,
                    ping_interval=30,  # Send ping every 30 seconds
                    ping_timeout=10,   # Wait 10 seconds for pong
                )
                self.connected = True
                logger.info("[PhantomWSClient] Connected to agent at %s", self.url)
                self._listener_task = asyncio.create_task(
                    self._listen(), name="ws_listener"
                )
                self._heartbeat_task = asyncio.create_task(
                    self._heartbeat(), name="ws_heartbeat"
                )
                return
            except Exception as exc:
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    # Exponential backoff: 2^attempt seconds
                    wait_time = 2 ** attempt
                    logger.warning(
                        "[PhantomWSClient] Connection attempt %d/%d failed (%s). "
                        "Retrying in %.0f s...",
                        attempt, _MAX_RETRIES, exc, wait_time,
                    )
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(
                        "[PhantomWSClient] All %d connection attempts failed.", _MAX_RETRIES
                    )

        raise ConnectionError(
            f"PhantomWSClient: could not connect to {self.url} "
            f"after {_MAX_RETRIES} attempts. Last error: {last_exc}"
        )

    async def disconnect(self) -> None:
        """Close the WebSocket connection gracefully."""
        for task in (self._listener_task, self._heartbeat_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        if self.websocket is not None:
            try:
                await self.websocket.close()
            except Exception as exc:
                logger.debug("[PhantomWSClient] Error during close: %s", exc)

        self.connected = False
        logger.info("[PhantomWSClient] Disconnected from %s", self.url)

    # ------------------------------------------------------------------ #
    # Internal listener                                                    #
    # ------------------------------------------------------------------ #

    async def _listen(self) -> None:
        """
        Background task — reads messages from the WebSocket and queues them.

        Exits when the connection closes or an error occurs.
        """
        try:
            async for raw in self.websocket:
                try:
                    message = json.loads(raw)
                except json.JSONDecodeError as exc:
                    logger.warning(
                        "[PhantomWSClient._listen] Could not parse message as JSON: %s", exc
                    )
                    continue
                await self._inbox.put(message)
        except websockets.ConnectionClosed as exc:
            logger.warning(
                "[PhantomWSClient._listen] Connection closed: code=%s reason=%r",
                exc.code, exc.reason,
            )
        except Exception as exc:
            logger.warning("[PhantomWSClient._listen] Unexpected error: %s", exc)
        finally:
            self.connected = False

    async def _heartbeat(self) -> None:
        """
        Background task — sends a ping every 30 s to keep the connection alive.
        Cloud Run closes WebSocket connections after 60 seconds of inactivity.
        """
        while self.connected:
            await asyncio.sleep(30)
            try:
                if self.websocket is not None:
                    await self.websocket.ping()
                    logger.debug("[PhantomWSClient] Heartbeat ping sent.")
            except Exception as exc:
                logger.warning(
                    "[PhantomWSClient] Heartbeat failed — connection lost: %s", exc
                )
                self.connected = False
                break

    # ------------------------------------------------------------------ #
    # Outbound messages                                                    #
    # ------------------------------------------------------------------ #

    async def send_screenshot(self, screenshot_b64: str, task_id: str) -> None:
        """
        Send a base64-encoded screenshot frame to the agent backend.

        Args:
            screenshot_b64: Base64-encoded JPEG string.
            task_id:        Identifier for the currently running task.
        """
        message = {
            "type": "screenshot",
            "task_id": task_id,
            "data": screenshot_b64,
        }
        await self._send(message)

    async def send_task_result(
        self,
        task_id: str,
        status: str,
        goal: str,
        steps_completed: list = None,
        steps_failed: list = None,
    ) -> None:
        """
        Send the final task result to the agent backend.
        Ensures the message is sent before any disconnection.

        Args:
            task_id: Identifier for the completed task.
            status:  ``"completed"`` or ``"failed"``.
            goal:    The original goal string.
            steps_completed: List of completed steps (optional).
            steps_failed: List of failed steps (optional).
        """
        message = {
            "type": "task_result",
            "task_id": task_id,
            "data": {
                "status": status,
                "goal": goal,
            },
        }
        
        # Add steps if provided
        if steps_completed is not None:
            message["data"]["steps_completed"] = steps_completed
        if steps_failed is not None:
            message["data"]["steps_failed"] = steps_failed
        
        # Ensure connection is alive before sending
        if not self.connected or self.websocket is None:
            logger.warning(
                "[PhantomWSClient] Connection lost before sending task_result. "
                "Attempting to reconnect..."
            )
            try:
                await self.connect()
            except Exception as exc:
                logger.error(
                    "[PhantomWSClient] Failed to reconnect to send task_result: %s", exc
                )
                raise
        
        # Send the message
        await self._send(message)
        
        # Wait a moment to ensure message is sent
        await asyncio.sleep(0.5)
        logger.info(
            "[PhantomWSClient] Task result sent: task_id=%s status=%s", task_id, status
        )

    # ------------------------------------------------------------------ #
    # Inbound messages                                                     #
    # ------------------------------------------------------------------ #

    async def receive_action(self, timeout: float = 30.0) -> dict | None:
        """
        Wait for an ``"action"`` or ``"task"`` message from the agent backend.

        Args:
            timeout: Maximum seconds to wait.

        Returns:
            The full message dict for ``type == "action"`` or ``type == "task"``,
            otherwise ``None``.
        """
        try:
            message = await asyncio.wait_for(self._inbox.get(), timeout=timeout)
        except asyncio.TimeoutError:
            logger.debug(
                "[PhantomWSClient.receive_action] Timed out after %.1f s.", timeout
            )
            return None

        msg_type = message.get("type")
        if msg_type not in ("action", "task"):
            logger.debug(
                "[PhantomWSClient.receive_action] Discarding unhandled message: type=%r",
                msg_type,
            )
            return None

        return message

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _send(self, message: dict) -> None:
        """
        Serialize *message* to JSON and send over the WebSocket.
        Handles reconnection if connection is lost.
        """
        if not self.connected or self.websocket is None:
            logger.warning(
                "[PhantomWSClient._send] Not connected. Attempting to reconnect..."
            )
            try:
                await self.connect()
            except Exception as exc:
                raise RuntimeError(
                    f"PhantomWSClient._send: not connected and reconnection failed: {exc}"
                )
        
        try:
            await self.websocket.send(json.dumps(message))
            logger.debug("[PhantomWSClient] Sent type=%r", message.get("type"))
        except websockets.ConnectionClosed as exc:
            logger.warning(
                "[PhantomWSClient._send] Connection closed while sending. "
                "Attempting to reconnect and resend..."
            )
            try:
                await self.connect()
                await self.websocket.send(json.dumps(message))
                logger.info("[PhantomWSClient] Message resent after reconnection.")
            except Exception as reconnect_exc:
                raise RuntimeError(
                    f"PhantomWSClient._send: failed to reconnect and resend: {reconnect_exc}"
                )
