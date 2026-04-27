"""
Phantom-Dev local task orchestrator — REACTIVE LOOP architecture.

Instead of decomposing the goal into 70 rigid steps upfront, this uses a
tight reactive loop:

  1. Capture screenshot
  2. Ask Gemini: "Given the goal and what's on screen, what is the ONE next action?"
  3. Execute that action
  4. Capture screenshot again
  5. Ask Gemini: "Is the goal complete?"
  6. If not, go to step 2

This is fundamentally more robust because every action decision is based on
what's ACTUALLY on screen right now, not what we guessed 30 steps ago.

Self-correction is built into the loop naturally — if an action doesn't work,
the next iteration sees the unchanged screen and tries something different.

DRY_RUN = True  → actions are logged but not sent to pyautogui.
DRY_RUN = False → actions are executed for real.
"""

import json
import logging
import re
import time
from copy import deepcopy
from typing import Any

import pyautogui

from capture import capture_frame_b64
from executor import execute_action
from gemini_client import GeminiClient
from playbook_manager import PlaybookManager

logger = logging.getLogger(__name__)

DRY_RUN = False

# Maximum number of action cycles before we give up
MAX_CYCLES = 60

# After how many consecutive failures we escalate to human
CONSECUTIVE_FAIL_LIMIT = 3

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

NEXT_ACTION_PROMPT = """\
You are Phantom, an autonomous desktop automation agent running on Windows.
Screen resolution: {screen_width}x{screen_height} pixels.

YOUR GOAL: {goal}

PROGRESS SO FAR:
{progress}

IMPORTANT CONTEXT — use these EXACT URLs:
- Jira: https://hegajvova77.atlassian.net/jira/software/projects/PD/boards/2
- Google Sheets: https://docs.google.com/spreadsheets/d/1kxWI3Vst0K2HPlkZdbkDbRAHg-JBQr6G9XSYRVxXxvw/edit
- Slack: https://app.slack.com/client/T0ALNCJAG0Y/C0AKQMHB7SR

PHASE INSTRUCTIONS — follow this order strictly:

PHASE 1 - READ DATA FROM JIRA:
- Open the Jira board URL
- The page loads automatically (no need to wait)
- IMMEDIATELY look at the screenshot and read ALL bug data visible on screen
- Save ALL bugs you can see in data_collected — include ID, title, status, and tags
- YOU MUST SAVE data_collected BEFORE doing anything else. If you see bugs on screen and data_collected is empty, you are doing it wrong.
- After saving visible bugs, scroll down ONCE (amount: 3-5) to check for more
- Read and save any NEW bugs found after scrolling
- STOP LOOKING after 1-2 scrolls. Work with whatever Q1 bugs you found.
- If you found fewer than 5 Q1 bugs, that is OK — proceed with what you have
- CRITICAL: Do NOT move to Phase 2 until data_collected contains at least one bug. If you somehow have no bugs, scroll back up and read the screen again.

PHASE 2 - ENTER DATA IN GOOGLE SHEETS:
- Open the Google Sheets URL (open_url handles bringing Chrome to foreground)
- The spreadsheet has columns: A=Ticket ID, B=Title, C=Status, D=Priority, E=Date Added
- Existing data is in rows 2-4. Start entering NEW data in row 5.
- Click the Name Box (top-left, shows cell reference like "A1", approximately x=40, y=173), type "A5", press Enter to navigate to cell A5
- Type the first bug ID, press Tab, type the title, press Tab, type the status, press Tab, type priority (use "High" for all), press Tab, type today's date (2026-03-15), press Enter to go to next row
- Repeat for each bug
- After entering all bugs, move to Phase 3

PHASE 3 - POST SUMMARY IN SLACK:
- Open the Slack URL
- Click the message input box at the bottom
- Type a summary message like: "Bug Tracker Update: Added X Q1 bugs from Jira to the spreadsheet: [list bug IDs]"
- Press Enter to send
- After typing the message, you MUST press Enter to send it. The goal is NOT complete until Enter is pressed and the message appears in the channel.

CRITICAL RULES:
- ALWAYS use data_collected to save any information you read from the screen
- Before scrolling, ALWAYS first save what you can already see
- Scroll amounts must be small integers (3-5), NOT large numbers like 500
- Do NOT scroll endlessly looking for data — 3 scrolls maximum per page
- If stuck doing the same action repeatedly, MOVE TO THE NEXT PHASE
- Before typing into any field, click on it first
- NEVER try to log in — all apps are already authenticated
- Browser is Chrome. open_url navigates in the SAME tab.
- This is Windows, not macOS. Use Ctrl (not Cmd) for shortcuts.
- For type actions with coordinates: the executor will click the field, select all, then type
- NEVER repeat the same action more than twice. If you clicked a cell and it didn't work, try a different approach.
- After typing text, your next action should be Tab or Enter to CONFIRM the input, NOT typing the same text again.
- After clicking a cell in Google Sheets, your VERY NEXT action must be a "type" action to enter data. Do NOT click the same cell again.
- open_url navigates in the SAME TAB (not a new tab). You can call it again if needed to re-navigate.
- To navigate in Google Sheets: after typing in a cell, press Tab to go right or Enter to go down. Do NOT click each cell individually.
- WORKFLOW FOR SHEETS DATA ENTRY: (1) open_url once (this navigates in the SAME tab), (2) click on the Name Box (cell reference box at top-left, around x=50, y=135), (3) type "A5" to navigate to cell A5, (4) press Enter to confirm navigation, (5) type "PD-1" then IMMEDIATELY press Tab (one cycle: type, next cycle: Tab), (6) type title then IMMEDIATELY press Tab, (7) type status then IMMEDIATELY press Enter to go to next row. IMPORTANT: after EVERY type action, your VERY NEXT action must be Tab or Enter — never type twice in a row without Tab/Enter between them.
- When Google Sheets shows a 'Leave site?' dialog, press Escape key to dismiss it. Do NOT click buttons on the dialog.
- IGNORE the 'Menus (Alt+/)' tooltip in Google Sheets — it is NOT an open menu. It is just a keyboard shortcut hint and does NOT block interaction. Do NOT press Escape to dismiss it.
- If you see 'Menus (Alt+/)' text on screen, IGNORE IT and proceed with your action (click cell, type data, etc).
- IMPORTANT: After typing in a Sheets cell, ALWAYS press Tab immediately to move to the next column. Do NOT type the same text twice — if you already typed it, press Tab and continue.

Return ONLY a JSON object — no markdown fences, no extra text:
{{
  "action": {{
    "type": "click|type|key_combo|scroll|double_click|move|wait|open_app|open_url",
    "x": <int>,
    "y": <int>,
    "text": "<string>",
    "keys": ["<key>", ...],
    "direction": "up|down",
    "amount": <int between 1-10>,
    "seconds": <float>,
    "app_name": "<string>",
    "url": "<string>"
  }},
  "confidence": <0.0-1.0>,
  "reason": "<what you are doing and why — one sentence>",
  "data_collected": "<CRITICAL: any data you can read from the current screen — ticket IDs, titles, statuses, text content. Save EVERYTHING useful. Use null only if there is truly nothing to read.>",
  "phase": "<Phase 1: Reading Jira | Phase 2: Entering Sheets | Phase 3: Posting Slack>",
  "goal_complete": <true|false — ONLY true when ALL phases are done>
}}

Include only the action fields relevant to the chosen action type.
If the goal is ALREADY fully complete, set goal_complete to true and use a wait action with 0 seconds.
"""

GOAL_CHECK_PROMPT = """\
You are verifying whether a desktop automation task is complete.

THE GOAL: {goal}

PROGRESS LOG:
{progress}

Look at the screenshot. Is the ENTIRE goal achieved?

For this specific goal, ALL of these must be true:
{completion_criteria}

Return ONLY a JSON object — no markdown fences, no extra text:
{{"goal_complete": <true|false>, "reason": "<brief explanation of what's done and what's not>"}}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str, label: str = "") -> dict | list:
    """Robustly extract JSON from model output."""
    stripped = text.strip()

    if stripped.startswith(("[", "{")):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            pass

    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    for open_ch, close_ch in (("[", "]"), ("{", "}")):
        start = stripped.find(open_ch)
        end = stripped.rfind(close_ch)
        if start != -1 and end > start:
            try:
                return json.loads(stripped[start : end + 1])
            except json.JSONDecodeError:
                pass

    raise ValueError(
        f"[{label}] Could not extract JSON from model response.\n"
        f"Raw (first 500 chars): {text[:500]}"
    )


def _inline_image(b64: str) -> dict:
    """Build a google-genai inline_data image part from a base64 JPEG string."""
    return {"inline_data": {"mime_type": "image/jpeg", "data": b64}}


def _build_completion_criteria(goal: str) -> str:
    """Generate completion criteria based on the goal."""
    goal_lower = goal.lower()
    criteria = []

    if "jira" in goal_lower:
        criteria.append("- Bug/ticket data has been read from Jira")
    if "sheet" in goal_lower or "spreadsheet" in goal_lower:
        criteria.append("- Data has been entered into Google Sheets")
    if "slack" in goal_lower:
        criteria.append("- A summary message has been posted in Slack")

    if not criteria:
        criteria.append("- The user's stated goal has been fully accomplished")
        criteria.append("- The expected end state is visible on screen")

    return "\n".join(criteria)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class TaskOrchestrator:
    """
    Reactive-loop orchestrator: screenshot → decide → act → repeat.

    Usage:
        orch = TaskOrchestrator("Open Chrome and navigate to google.com")
        final_state = orch.run()
    """

    def __init__(self, goal: str):
        self.goal = goal
        self.client = GeminiClient()
        self.playbook_manager = PlaybookManager()
        self.playbook: dict | None = None

        # Progress tracking — fed back to Gemini each cycle
        self.action_log: list[str] = []
        self.collected_data: list[str] = []

        self.state: dict = {
            "goal": goal,
            "status": "running",
            "steps_completed": [],
            "steps_failed": [],
            "correction_history": [],
            "current_step": None,
            "max_steps": MAX_CYCLES,
            "step_count": 0,
        }
        logger.info("TaskOrchestrator initialised. Goal: %r", goal)

    # ------------------------------------------------------------------ #
    # Rate-limit-aware Gemini wrapper                                      #
    # ------------------------------------------------------------------ #

    def _gemini_call(self, contents: list) -> Any:
        """Call Gemini with rate-limit retry."""
        def _do_call():
            return self.client._client.models.generate_content(
                model="gemini-2.5-flash",
                contents=contents,
            )

        try:
            return _do_call()
        except Exception as exc:
            msg = str(exc)
            if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
                match = re.search(r"retry in\s+(\d+(?:\.\d+)?)\s*s", msg, re.IGNORECASE)
                delay = float(match.group(1)) if match else 60.0
                logger.warning("[_gemini_call] Rate limit. Waiting %.0f s...", delay)
                time.sleep(delay)
                return _do_call()
            raise

    # ------------------------------------------------------------------ #
    # Build progress summary for Gemini context                            #
    # ------------------------------------------------------------------ #

    def _progress_summary(self) -> str:
        """Build a concise progress string for the prompt."""
        lines = []

        if self.collected_data:
            lines.append("DATA COLLECTED:")
            for d in self.collected_data:
                lines.append(f"  • {d}")

        if self.action_log:
            # Show last 8 actions to keep context manageable
            recent = self.action_log[-8:]
            lines.append(f"\nLAST {len(recent)} ACTIONS (of {len(self.action_log)} total):")
            for i, entry in enumerate(recent):
                lines.append(f"  {len(self.action_log) - len(recent) + i + 1}. {entry}")

        if not lines:
            lines.append("No actions taken yet. This is the starting state.")

        # Check for repeated actions — compare by extracting the action type/text pattern
        if len(self.action_log) >= 3:
            last_three = self.action_log[-3:]
            # Normalize: strip leading [Phase X: ...] and [FAILED] prefixes for comparison
            import re as _re
            def _normalize(s):
                return _re.sub(r'^\[.*?\]\s*', '', s).strip().lower()
            normalized = [_normalize(s) for s in last_three]
            if normalized[0] == normalized[1] == normalized[2]:
                lines.append(
                    "\n⚠️ WARNING: You have repeated the same action 3+ times. "
                    "This is NOT WORKING. You MUST try a COMPLETELY DIFFERENT approach. "
                    "If you are trying to type text and it's not appearing, the cell may not be in edit mode. "
                    "Try pressing Enter or Tab to move forward instead of retyping."
                )

        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Core: get next action                                                #
    # ------------------------------------------------------------------ #

    def get_next_action(self, screenshot_b64: str) -> dict:
        """Ask Gemini for the single next action based on current screen."""
        screen_w, screen_h = pyautogui.size()

        # Inject playbook hint if available
        playbook_hint = ""
        if self.playbook:
            playbook_hint = "\n\nPRIOR EXPERIENCE:\n" + self.playbook_manager.format_for_prompt(self.playbook)

        prompt = NEXT_ACTION_PROMPT.format(
            goal=self.goal,
            progress=self._progress_summary(),
            screen_width=screen_w,
            screen_height=screen_h,
        ) + playbook_hint

        response = self._gemini_call([prompt, _inline_image(screenshot_b64)])
        result = _extract_json(response.text, label="get_next_action")

        if not isinstance(result, dict):
            raise ValueError(f"[get_next_action] Expected dict, got {type(result).__name__}")

        return result

    # ------------------------------------------------------------------ #
    # Main loop                                                            #
    # ------------------------------------------------------------------ #

    def run(self) -> dict:
        """
        Reactive loop: screenshot → decide → act → repeat until goal is done.
        """
        logger.info("=" * 60)
        logger.info("Starting task: %r  [DRY_RUN=%s]", self.goal, DRY_RUN)
        logger.info("=" * 60)

        # Look up a matching playbook
        self.playbook = self.playbook_manager.find(self.goal)
        if self.playbook:
            logger.info("[run] Found matching playbook — injecting into context.")

        consecutive_failures = 0

        for cycle in range(1, MAX_CYCLES + 1):
            self.state["step_count"] = cycle
            logger.info("[run] ── Cycle %d/%d ──", cycle, MAX_CYCLES)

            # 1. Capture screenshot
            logger.info("[run]   Capturing screenshot...")
            screenshot_b64 = capture_frame_b64()

            # 2. Ask Gemini for next action
            try:
                decision = self.get_next_action(screenshot_b64)
            except (ValueError, Exception) as exc:
                logger.error("[run]   get_next_action failed: %s", exc)
                consecutive_failures += 1
                self.action_log.append(f"[ERROR] Gemini call failed: {exc}")

                if consecutive_failures >= CONSECUTIVE_FAIL_LIMIT:
                    logger.error("[run]   %d consecutive failures. Stopping.", consecutive_failures)
                    self.state["status"] = "failed"
                    break
                time.sleep(2)
                continue

            # 3. Check if Gemini says goal is complete
            goal_complete = decision.get("goal_complete", False)
            reason = decision.get("reason", "")
            phase = decision.get("phase", "")
            data_collected = decision.get("data_collected")

            if data_collected:
                self.collected_data.append(str(data_collected))
                logger.info("[run]   Data collected: %s", data_collected)

            if goal_complete:
                logger.info("[run]   Gemini says goal is COMPLETE: %s", reason)
                self.state["steps_completed"].append({
                    "step": cycle,
                    "description": f"Goal complete: {reason}",
                    "expected_result": "goal achieved",
                    "success": True,
                })
                self.state["status"] = "completed"
                break

            # 4. Extract and execute the action
            action = decision.get("action", decision)
            # Handle case where action fields are at top level
            if "type" not in action and "type" in decision:
                action = decision

            action_desc = f"[{phase}] {reason}" if phase else reason
            logger.info("[run]   Action: %s → %s", json.dumps(action), action_desc)

            if DRY_RUN:
                logger.info("[run]   [DRY RUN] Would execute: %s", json.dumps(action))
                exec_result = {"success": True, "action": action, "detail": {"dry_run": True}, "error": None}
            else:
                exec_result = execute_action(action)

            if exec_result["success"]:
                consecutive_failures = 0
                self.action_log.append(f"{action_desc}")
                self.state["steps_completed"].append({
                    "step": cycle,
                    "description": action_desc,
                    "expected_result": "",
                    "success": True,
                })
                logger.info("[run]   Action executed OK.")

                # Small delay for UI to settle
                time.sleep(0.5)
            else:
                consecutive_failures += 1
                error = exec_result.get("error", "unknown")
                self.action_log.append(f"[FAILED] {action_desc}: {error}")
                self.state["steps_failed"].append({
                    "step": cycle,
                    "description": action_desc,
                    "expected_result": "",
                    "success": False,
                })
                logger.warning("[run]   Action FAILED: %s", error)

                if consecutive_failures >= CONSECUTIVE_FAIL_LIMIT:
                    # Tier 3: human assist
                    logger.warning("[run]   [HUMAN ASSIST] %d consecutive failures.", consecutive_failures)
                    self.state["status"] = "waiting_for_user"
                    msg = (
                        f"Stuck on: {action_desc}. "
                        f"Failed {consecutive_failures} times. "
                        f"Please help and press Enter to continue."
                    )
                    print(f"\n[HUMAN ASSIST] {msg}")

                    try:
                        input()
                    except (EOFError, KeyboardInterrupt):
                        logger.info("[run]   User cancelled.")
                        self.state["status"] = "failed"
                        break

                    self.state["status"] = "running"
                    consecutive_failures = 0  # reset after human help
                    continue

                time.sleep(1)  # brief pause before retry

        # ── Final status ──────────────────────────────────────────────────
        if self.state["status"] == "running":
            # Hit MAX_CYCLES without completing
            # Do one final goal check
            logger.info("[run] Max cycles reached. Final goal check...")
            try:
                final_b64 = capture_frame_b64()
                criteria = _build_completion_criteria(self.goal)
                check_prompt = GOAL_CHECK_PROMPT.format(
                    goal=self.goal,
                    progress=self._progress_summary(),
                    completion_criteria=criteria,
                )
                resp = self._gemini_call([check_prompt, _inline_image(final_b64)])
                raw_check = _extract_json(resp.text, label="final_check")
                check: dict = raw_check if isinstance(raw_check, dict) else {}

                if check.get("goal_complete", False):
                    logger.info("[run] Final check: goal IS complete — %s", check.get("reason", ""))
                    self.state["status"] = "completed"
                else:
                    logger.warning("[run] Final check: goal NOT complete — %s", check.get("reason", ""))
                    self.state["status"] = "failed"
            except Exception as exc:
                logger.warning("[run] Final check failed: %s", exc)
                # Partial success if we completed more than we failed
                completed = len(self.state["steps_completed"])
                failed = len(self.state["steps_failed"])
                self.state["status"] = "completed" if completed > failed else "failed"

        self.state["current_step"] = None
        logger.info(
            "[run] Task finished. status=%s  completed=%d  failed=%d  cycles=%d",
            self.state["status"],
            len(self.state["steps_completed"]),
            len(self.state["steps_failed"]),
            self.state["step_count"],
        )

        # Persist playbook if successful
        self.playbook_manager.save(self.state)

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