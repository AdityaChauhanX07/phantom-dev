"""
Phantom-Dev local task orchestrator.

Manages the full perception → plan → act → verify loop for a given goal.

Loop per step:
  capture → get_next_action → execute_action → capture → verify_step
  On verify failure: retry once; if still failing, mark step failed and continue.

DRY_RUN = True  → actions are logged but not sent to pyautogui.
DRY_RUN = False → actions are executed for real.
"""

import json
import logging
import re
import time
from copy import deepcopy

from capture import capture_frame_b64
from executor import execute_action
from gemini_client import GeminiClient

logger = logging.getLogger(__name__)

DRY_RUN = False

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

DECOMPOSE_PROMPT = """\
You are a desktop automation planner. The user wants to accomplish this goal:

  "{goal}"

Look at the current screenshot and break the goal into ordered, atomic sub-steps.
Return ONLY a JSON array — no markdown fences, no extra text:

[
  {{"step": 1, "description": "<what to do>", "expected_result": "<what the screen should show afterwards>"}},
  {{"step": 2, "description": "<what to do>", "expected_result": "<what the screen should show afterwards>"}},
  ...
]

Rules:
- Each step must be a single, observable action (one click, one keystroke, etc.).
- Keep descriptions concise and unambiguous.
- expected_result should be visually verifiable from a screenshot.
"""

NEXT_ACTION_PROMPT = """\
You are a desktop automation agent. Look at the current screenshot.

Your current task is:
  "{description}"

Return ONLY a single JSON action object — no markdown fences, no extra text:
{{"type": "click|type|key_combo|scroll|double_click|move|wait", "x": <int>, "y": <int>, "text": "<string>", "keys": ["<key>", ...], "direction": "up|down", "amount": <int>, "seconds": <float>, "confidence": <0.0-1.0>, "reason": "<why>"}}

Include only the fields relevant to the chosen action type.
Set "confidence" to reflect how certain you are about the coordinates/target.
"""

VERIFY_PROMPT = """\
You are a desktop automation verifier. Compare the two screenshots:
  - BEFORE: the state before the action was taken.
  - AFTER:  the state after the action was taken.

The expected result was:
  "{expected_result}"

Return ONLY a JSON object — no markdown fences, no extra text:
{{"success": <true|false>, "description": "<what visually changed between the two screenshots>", "confidence": <0.0-1.0>}}

Be strict: "success" is true only if the screen change clearly matches the expected result.
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str, label: str = "") -> dict | list:
    """
    Robustly extract the first JSON value (object or array) from model output.
    Tries bare parse → fenced block → regex scan.

    Raises:
        ValueError with context on complete failure.
    """
    stripped = text.strip()

    # 1. Bare JSON
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # 2. Markdown fences
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    # 3. First {...} or [...] block
    block = re.search(r"(\{[\s\S]*?\}|\[[\s\S]*?\])", stripped)
    if block:
        try:
            return json.loads(block.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"[{label}] Could not extract JSON from model response.\n"
        f"Raw (first 500 chars): {text[:500]}"
    )


def _inline_image(b64: str) -> dict:
    """Build a google-genai inline_data image part from a base64 JPEG string."""
    return {"inline_data": {"mime_type": "image/jpeg", "data": b64}}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class TaskOrchestrator:
    """
    Runs the full perception → plan → act → verify loop for a single goal.

    Usage:
        orch = TaskOrchestrator("Open Chrome and navigate to google.com")
        final_state = orch.run()
        print(final_state["status"])
    """

    INTER_CALL_DELAY = 12   # seconds between Gemini calls — stays under 5 RPM free tier
                            # Set to 0 when using Vertex AI (no rate limits)

    def __init__(self, goal: str):
        self.goal = goal
        self.client = GeminiClient()
        self.state: dict = {
            "goal": goal,
            "status": "running",          # running | completed | failed | waiting_for_user
            "steps_completed": [],
            "steps_failed": [],
            "current_step": None,
            "max_steps": 20,
            "step_count": 0,
        }
        logger.info("TaskOrchestrator initialised. Goal: %r", goal)

    # ------------------------------------------------------------------ #
    # Rate-limit-aware Gemini wrapper                                      #
    # ------------------------------------------------------------------ #

    def _gemini_call(self, contents: list) -> object:
        """
        Call Gemini with automatic rate-limit handling.

        - On success: sleeps INTER_CALL_DELAY seconds before returning, so
          the *next* call is naturally spaced out.
        - On 429 / RESOURCE_EXHAUSTED: extracts the suggested retry delay from
          the error message ("retry in Xs"), waits that long, then retries the
          call exactly once. If the retry also fails the exception propagates.

        Args:
            contents: List passed as-is to generate_content().

        Returns:
            The GenerateContentResponse from the Gemini SDK.
        """
        def _do_call():
            return self.client._client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
            )

        def _is_rate_limit(exc: Exception) -> bool:
            msg = str(exc)
            return "429" in msg or "RESOURCE_EXHAUSTED" in msg

        def _extract_retry_delay(exc: Exception) -> float:
            """Parse 'retry in Xs' from the error message; default to 60 s."""
            match = re.search(r"retry in\s+(\d+(?:\.\d+)?)\s*s", str(exc), re.IGNORECASE)
            return float(match.group(1)) if match else 60.0

        try:
            response = _do_call()
        except Exception as exc:
            if _is_rate_limit(exc):
                delay = _extract_retry_delay(exc)
                logger.warning(
                    "[_gemini_call] Rate limit hit. Waiting %.0f s before retry...", delay
                )
                time.sleep(delay)
                logger.info("[_gemini_call] Retrying Gemini call...")
                response = _do_call()   # let this propagate if it fails again
            else:
                raise

        logger.debug("[_gemini_call] Call succeeded. Sleeping %d s (rate limit buffer)...",
                     self.INTER_CALL_DELAY)
        time.sleep(self.INTER_CALL_DELAY)
        return response

    # ------------------------------------------------------------------ #
    # Core perception / planning methods                                   #
    # ------------------------------------------------------------------ #

    def decompose_goal(self, screenshot_b64: str) -> list[dict]:
        """
        Ask Gemini to break self.goal into ordered, atomic sub-steps.

        Args:
            screenshot_b64: Base64-encoded JPEG of the current screen.

        Returns:
            List of step dicts: [{"step": int, "description": str, "expected_result": str}, ...]

        Raises:
            ValueError: If Gemini's response cannot be parsed as a JSON array.
        """
        prompt = DECOMPOSE_PROMPT.format(goal=self.goal)
        logger.info("[decompose_goal] Sending goal + screenshot to Gemini...")

        response = self._gemini_call([prompt, _inline_image(screenshot_b64)])

        steps = _extract_json(response.text, label="decompose_goal")
        if not isinstance(steps, list):
            raise ValueError(
                f"[decompose_goal] Expected a JSON array, got {type(steps).__name__}.\n"
                f"Raw: {response.text[:500]}"
            )

        logger.info("[decompose_goal] Received %d step(s).", len(steps))
        for s in steps:
            logger.debug("  Step %s: %s", s.get("step"), s.get("description"))
        return steps

    def get_next_action(self, screenshot_b64: str, current_step: dict) -> dict:
        """
        Ask Gemini for a single action that accomplishes current_step.

        Args:
            screenshot_b64: Base64-encoded JPEG of the current screen.
            current_step: Step dict from decompose_goal().

        Returns:
            Flat action dict suitable for execute_action().

        Raises:
            ValueError: If Gemini's response cannot be parsed as a JSON object.
        """
        description = current_step.get("description", "")
        prompt = NEXT_ACTION_PROMPT.format(description=description)
        logger.info("[get_next_action] Requesting action for step: %r", description)

        response = self._gemini_call([prompt, _inline_image(screenshot_b64)])

        action = _extract_json(response.text, label="get_next_action")
        if not isinstance(action, dict):
            raise ValueError(
                f"[get_next_action] Expected a JSON object, got {type(action).__name__}."
            )

        logger.info("[get_next_action] Action: %s", json.dumps(action))
        return action

    def verify_step(
        self,
        before_b64: str,
        after_b64: str,
        expected_result: str,
    ) -> dict:
        """
        Ask Gemini to compare before/after screenshots against expected_result.

        Args:
            before_b64: Base64 JPEG captured before the action.
            after_b64:  Base64 JPEG captured after the action.
            expected_result: Human-readable description of the desired change.

        Returns:
            {"success": bool, "description": str, "confidence": float}

        Raises:
            ValueError: If Gemini's response cannot be parsed.
        """
        prompt = VERIFY_PROMPT.format(expected_result=expected_result)
        logger.info("[verify_step] Verifying expected result: %r", expected_result)

        response = self._gemini_call([
            prompt,
            "BEFORE screenshot:",
            _inline_image(before_b64),
            "AFTER screenshot:",
            _inline_image(after_b64),
        ])

        verdict = _extract_json(response.text, label="verify_step")
        if not isinstance(verdict, dict):
            raise ValueError("[verify_step] Expected a JSON object from Gemini.")

        logger.info(
            "[verify_step] success=%s confidence=%.2f — %s",
            verdict.get("success"),
            verdict.get("confidence", 0.0),
            verdict.get("description", ""),
        )
        return verdict

    # ------------------------------------------------------------------ #
    # Main loop                                                            #
    # ------------------------------------------------------------------ #

    def run(self) -> dict:
        """
        Execute the full perception → plan → act → verify loop.

        Returns:
            Final task state dict (self.state).
        """
        logger.info("=" * 60)
        logger.info("Starting task: %r  [DRY_RUN=%s]", self.goal, DRY_RUN)
        logger.info("=" * 60)

        # ── Step 1: initial screenshot + goal decomposition ──────────────
        logger.info("[run] Capturing initial screenshot...")
        initial_b64 = capture_frame_b64()

        try:
            steps = self.decompose_goal(initial_b64)
        except (ValueError, Exception) as exc:
            logger.error("[run] Goal decomposition failed: %s", exc)
            self.state["status"] = "failed"
            self.state["error"] = str(exc)
            return deepcopy(self.state)

        logger.info("[run] Task decomposed into %d step(s).", len(steps))

        # ── Step 2: iterate through each planned step ────────────────────
        for step in steps:
            if self.state["step_count"] >= self.state["max_steps"]:
                logger.warning(
                    "[run] Safety limit reached (%d steps). Stopping.",
                    self.state["max_steps"],
                )
                self.state["status"] = "failed"
                break

            step_num = step.get("step", self.state["step_count"] + 1)
            description = step.get("description", "")
            expected_result = step.get("expected_result", "")
            self.state["current_step"] = step
            self.state["step_count"] += 1

            logger.info(
                "[run] ── Step %d/%d: %s",
                step_num, len(steps), description,
            )

            # Inner retry loop: attempt the step, retry once on verify failure
            success = False
            for attempt in range(1, 3):   # attempts 1 and 2
                if attempt > 1:
                    logger.info("[run]   Retrying step %d (attempt %d)...", step_num, attempt)

                # (a) Capture before screenshot
                logger.info("[run]   Capturing before-screenshot...")
                before_b64 = capture_frame_b64()

                # (b) Ask Gemini for the action to take
                try:
                    action = self.get_next_action(before_b64, step)
                except (ValueError, Exception) as exc:
                    logger.error("[run]   get_next_action failed: %s", exc)
                    break   # skip to next step on planning failure

                # (c) Execute (or dry-run) the action
                if DRY_RUN:
                    logger.info("[run]   [DRY RUN] Would execute: %s", json.dumps(action))
                    exec_result = {
                        "success": True,
                        "action": action,
                        "detail": {"dry_run": True},
                        "error": None,
                    }
                else:
                    logger.info("[run]   Executing action: %s", json.dumps(action))
                    exec_result = execute_action(action)

                if not exec_result["success"]:
                    logger.warning(
                        "[run]   Action execution failed: %s", exec_result["error"]
                    )
                    break   # no point verifying if the action itself failed

                # (d) Capture after screenshot
                logger.info("[run]   Capturing after-screenshot...")
                after_b64 = capture_frame_b64()

                # (e) Verify the step outcome
                try:
                    verdict = self.verify_step(before_b64, after_b64, expected_result)
                except (ValueError, Exception) as exc:
                    logger.error("[run]   verify_step failed: %s", exc)
                    verdict = {"success": False, "description": str(exc), "confidence": 0.0}

                # (f) Check verdict
                if verdict.get("success"):
                    logger.info(
                        "[run]   Step %d verified OK (confidence=%.2f): %s",
                        step_num,
                        verdict.get("confidence", 0.0),
                        verdict.get("description", ""),
                    )
                    success = True
                    break
                else:
                    logger.warning(
                        "[run]   Step %d verify FAILED (attempt %d, confidence=%.2f): %s",
                        step_num,
                        attempt,
                        verdict.get("confidence", 0.0),
                        verdict.get("description", ""),
                    )

            # (g) Record outcome
            step_record = {
                "step": step_num,
                "description": description,
                "expected_result": expected_result,
                "success": success,
            }
            if success:
                self.state["steps_completed"].append(step_record)
                logger.info("[run]   Step %d → COMPLETED", step_num)
            else:
                self.state["steps_failed"].append(step_record)
                logger.warning("[run]   Step %d → FAILED (continuing to next step)", step_num)

        # ── Step 3: determine final status ───────────────────────────────
        if self.state["status"] == "running":
            failed_count = len(self.state["steps_failed"])
            if failed_count == 0:
                self.state["status"] = "completed"
            elif failed_count < len(steps):
                self.state["status"] = "completed"   # partial success
                logger.warning(
                    "[run] Task finished with %d failed step(s) out of %d.",
                    failed_count, len(steps),
                )
            else:
                self.state["status"] = "failed"

        self.state["current_step"] = None
        logger.info(
            "[run] Task finished. status=%s  completed=%d  failed=%d",
            self.state["status"],
            len(self.state["steps_completed"]),
            len(self.state["steps_failed"]),
        )
        return deepcopy(self.state)


# ---------------------------------------------------------------------------
# Entry point — quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    goal = "Open VS Code's Explorer panel by clicking the Explorer icon in the Activity Bar"
    orchestrator = TaskOrchestrator(goal)
    final_state = orchestrator.run()

    print("\n=== Final Task State ===")
    print(json.dumps(
        {k: v for k, v in final_state.items() if k not in ("steps_completed", "steps_failed")},
        indent=2,
    ))
    print(f"\nCompleted steps ({len(final_state['steps_completed'])}):")
    for s in final_state["steps_completed"]:
        print(f"  [OK ] Step {s['step']}: {s['description']}")
    print(f"\nFailed steps ({len(final_state['steps_failed'])}):")
    for s in final_state["steps_failed"]:
        print(f"  [ERR] Step {s['step']}: {s['description']}")
