"""
Phantom-Dev local task orchestrator.

Manages the full perception → plan → act → verify loop for a given goal.

Loop per step:
  capture → get_next_action → execute_action → capture → verify_step

  On verify failure: 3-tier self-correction system:
    TIER 1 — Retry same action (timing/slow UI): wait 2s, exact same action.
    TIER 2 — Alternative path (missing element): fresh screenshot → Gemini
              suggests a different approach → execute → verify.
    TIER 3 — Human-in-the-loop: pause, ask user to unblock, then retry once.

  All correction attempts are recorded in state["correction_history"].

DRY_RUN = True  → actions are logged but not sent to pyautogui.
DRY_RUN = False → actions are executed for real.
"""

import json
import logging
import re
import time
from copy import deepcopy

import pyautogui

from capture import capture_frame_b64
from executor import execute_action
from gemini_client import GeminiClient
from playbook_manager import PlaybookManager

logger = logging.getLogger(__name__)

DRY_RUN = False

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

DECOMPOSE_PROMPT = """\
IMPORTANT CONTEXT — App URLs to use:
- Jira: https://hegajvova77.atlassian.net/jira/software/projects/PD/boards/2
- Google Sheets: https://docs.google.com/spreadsheets/d/1kxWI3Vst0K2HPlkZdbkDbRAHg-JBQr6G9XSYRVxXxvw/edit
- Slack: https://app.slack.com/client/T0ALNCJAG0Y/C0AKQMHB7SR

Always navigate directly to these URLs. Do not search for the apps.

You are a desktop automation planner. The user wants to accomplish this goal:

  "{goal}"

IMPORTANT: Before planning any steps, check the current screen state carefully.
If an application is already open and visible on screen, do NOT include a step
to open it. Start from the current screen state and work forward from there.

IMPORTANT: Break the goal into DETAILED, GRANULAR steps. Each step should be \
ONE single action (one click, one navigation, one data entry). \
For a task involving Jira → Sheets → Slack, you must produce AT MINIMUM 15 steps:
- Steps to read each Jira ticket (navigate, screenshot, read data)
- Steps to open Sheets and enter each row of data
- Steps to open Slack and post the summary message
Do NOT summarize multiple actions into one step. Each atomic action is its own step.

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
- expected_result MUST be visually verifiable from a screenshot.
- expected_result should describe the FINAL STATE, not the action itself.
- Remember: This is macOS, not Windows. Use macOS-specific shortcuts (Cmd+Tab for app switching).
- To open applications: ALWAYS try Dock first. If Dock icon is visible, use ONE step: "Click on [AppName] icon in Dock"
- DO NOT use keyboard shortcuts like Command+Shift+A or Command+Space unless absolutely necessary
- Keep steps SIMPLE - if you can do it in 1 click, don't make it 3 steps

EXPECTED RESULT GUIDELINES (CRITICAL):
- expected_result must describe what the SCREEN should show, not what action was taken
- Good: "Google homepage is open and visible" (describes screen state)
- Bad: "Opened Google" (describes action, not state)
- Good: "Search results for 'Gemini' are displayed" (describes screen state)
- Bad: "Searched for Gemini" (describes action, not state)
- The verifier will check if the expected_result is visible on screen
- Make expected_result specific and checkable: "X is visible", "Y appears", "Z is displayed"

FOR SEARCH TASKS (e.g., "open Google and search for Gemini"):
- Step 1: Open the website
  - Description: "Open Google"
  - Expected result: "Google homepage or search page is open and visible on screen"
- Step 2: Type the search query
  - Description: "Type 'Gemini' into the search bar"
  - Expected result: "The search query 'Gemini' appears in the search bar, OR search results for 'Gemini' are displayed"
- Step 3: Execute the search (if Step 2 didn't auto-execute)
  - Description: "Press Enter to execute the search"
  - Expected result: "Search results page for 'Gemini' is displayed with links, snippets, or video thumbnails"
- The FINAL step's expected_result should clearly indicate task completion
- If search results are visible → task is complete → mark that step as the last one
"""

NEXT_ACTION_PROMPT = """\
You are a desktop automation agent running on macOS.
Screen resolution: {screen_width}x{screen_height} pixels.
Screen center: x={screen_center_x}, y={screen_center_y}

COORDINATE REFERENCE FOR THIS EXACT SCREEN:
- Google search box: approximately x={screen_center_x}, y={screen_center_y_minus_50}
- YouTube search box: approximately x={screen_center_x}, y=55
- Browser address bar: approximately x={screen_center_x}, y=45
- macOS Dock: bottom of screen at y={screen_height_minus_30}

Your current task is:
  "{description}"

IMPORTANT: Before typing into any input field, ALWAYS first click on that \
field to focus it. Never assume a field is already focused. Your action should \
be a click on the target field, not a type action, if the field has not been \
explicitly clicked in this step.

Return ONLY a single JSON action object — no markdown fences, no extra text:
{{"type": "click|type|key_combo|scroll|double_click|move|wait|open_app|open_url", "x": <int>, "y": <int>, "text": "<string>", "keys": ["<key>", ...], "direction": "up|down", "amount": <int>, "seconds": <float>, "app_name": "<string>", "url": "<string>", "confidence": <0.0-1.0>, "reason": "<why>"}}

For opening:
- Applications: {{"type": "open_app", "app_name": "Calculator"}}
- Websites: {{"type": "open_url", "url": "youtube.com"}}

Include only the fields relevant to the chosen action type.
Set "confidence" to reflect how certain you are about the coordinates/target. If coordinates are uncertain, use confidence < 0.8.
"""

VERIFY_PROMPT = """\
You are a desktop automation verifier.

Look ONLY at the AFTER screenshot. Is the expected result currently visible \
and true on screen? Do not require a visual change — the state may have already \
been achieved. Answer based solely on what you see in the AFTER screenshot.

The expected result is:
  "{expected_result}"

Return ONLY a JSON object — no markdown fences, no extra text:
{{"success": <true|false>, "description": "<what you see in the AFTER screenshot relevant to the expected result>", "confidence": <0.0-1.0>}}

"success" is true if the expected result is currently present on screen, regardless of whether it changed.
"""

ALTERNATIVE_ACTION_PROMPT = """\
You are a desktop automation agent running on macOS.
Screen resolution: {screen_width}x{screen_height} pixels.
Screen center: x={screen_center_x}, y={screen_center_y}

COORDINATE REFERENCE FOR THIS EXACT SCREEN:
- Google search box: approximately x={screen_center_x}, y={screen_center_y_minus_50}
- YouTube search box: approximately x={screen_center_x}, y=55
- Browser address bar: approximately x={screen_center_x}, y=45
- macOS Dock: bottom of screen at y={screen_height_minus_30}

I tried to: {description}
I expected: {expected_result}
It failed because: {failure_description}

Look at the current screen and suggest a completely different approach to achieve the same goal.

IMPORTANT FOR TYPING:
- For tasks that say "Type X into Y", return a "type" action with both coordinates (x, y) of the input field AND the "text" field.
- Example: {{"type": "type", "x": 430, "y": 55, "text": "Google Gemini", "confidence": 0.9, "reason": "Typing into address bar"}}
- The executor will automatically click on the field, select all text, then type the new text.

IMPORTANT FOR OPENING:
- If the goal is to open a WEBSITE (YouTube, Google, Jira, Facebook, Google Gemini, etc.), use {{"type": "open_url", "url": "youtube.com"}}
- If the goal is to open an APPLICATION (Calculator, TextEdit, Safari, Chrome), use {{"type": "open_app", "app_name": "Calculator"}}
- Websites are services you access through a browser - use open_url
- Applications are macOS programs - use open_app
- CRITICAL: For websites, NEVER try to click bookmarks, links, or browser UI - ALWAYS use open_url directly
- For Google services: "Google Gemini" → "gemini.google.com", "Google" → "google.com"

BROWSER: Firefox. All sites already logged in. open_url opens new tab in existing Firefox window.

EXACT DEMO URLS:
- Jira board: https://hegajvova77.atlassian.net/jira/software/projects/PD/boards/2
- Google Sheets: https://docs.google.com/spreadsheets/d/1kxWI3Vst0K2HPlkZdbkDbRAHg-JBQr6G9XSYRVxXxvw/edit
- Slack: https://app.slack.com/client/T0ALNCJAG0Y/C0AKQMHB7SR

IMPORTANT RULES:
- NEVER try to log in — already authenticated
- NEVER click "Sign in" or "Log in" buttons
- Take a screenshot after opening each URL to verify correct page loaded
- Read ticket data directly from screenshots — don't click each ticket to open it
- In Sheets: use Tab between columns, Enter to go to next row
- In Slack: use clipboard paste for the full message, then Enter to send

COORDINATE PRECISION:
- When clicking on UI elements, ALWAYS click on the CENTER of the visible element, not the edges.
- Look carefully at the screenshot to identify the exact center of the target element.
- If you're not 100% certain about coordinates, set confidence < 0.8.
- For buttons/icons: click the center of the visible button/icon area.
- For text fields: click the center of the input field.
- For menu items: click the center of the text/icon of the menu item.

FINDING SEARCH BARS AND INPUT FIELDS (CRITICAL - BE PRECISE):
- Search bars are usually large rectangular boxes, often in the center or top of the page
- On Google homepage: The search box is a LARGE rounded rectangle in the CENTER of the page, below the Google logo
  - It's typically 400-600 pixels wide, 40-50 pixels tall
  - Usually positioned at approximately: x = screen_width/2, y = screen_height/2 or slightly above
  - Look for a white or light gray rounded rectangle with a shadow
  - May have placeholder text "Search Google" or a search icon inside
  - Click on the CENTER of this rectangle (not on the icon, not on the edges)
  - Typical coordinates for 1920x1080 screen: x = 960, y = 400-500
  - Typical coordinates for 1440x900 screen: x = 720, y = 350-450
- On YouTube: The search box is at the TOP of the page, in the header area
  - Usually positioned at: x = screen_width/2, y = 50-100 pixels from top
  - Look for a rectangular input field with "Search" placeholder
- General rules:
  - Search bars are usually the LARGEST input field visible on the page
  - They're often in the center (for homepages) or top (for navigation)
  - Look for rounded corners, shadows, or distinctive styling
  - If you see placeholder text like "Search", "Search Google", "Search YouTube" → that's the search box
  - Click on the CENTER of the visible search box rectangle
  - Use confidence 0.8-0.9 if you can clearly see the search box boundaries
  - Use confidence 0.6-0.7 if you're estimating based on typical layout
  - If confidence is below 0.6, try to identify the search box more carefully before clicking
- ALTERNATIVE METHOD if search box is hard to find:
  - On Google: You can press Tab key multiple times to navigate to the search box, then type
  - But clicking is preferred if you can see the search box clearly

OPENING APPLICATIONS vs WEBSITES:
- For APPLICATIONS (Calculator, TextEdit, Safari, Chrome): Use {{"type": "open_app", "app_name": "Calculator"}}
- For WEBSITES (YouTube, Google, Jira, Facebook): Use {{"type": "open_url", "url": "youtube.com"}}
- Websites are services like YouTube, Google, Jira - use open_url, not open_app
- Applications are macOS apps like Calculator, TextEdit - use open_app
- NEVER use Command+Shift+A, Command+Space, or clicking Dock icons - use open_app or open_url instead

DEMO URLS — use these exact URLs when opening demo apps:
- Jira: https://hegajvova77.atlassian.net/jira/software/projects/PD/boards/2
- Sheets: https://docs.google.com/spreadsheets/d/1kxWI3Vst0K2HPlkZdbkDbRAHg-JBQr6G9XSYRVxXxvw/edit
- Slack: https://app.slack.com/client/T0ALNCJAG0Y/C0AKQMHB7SR

Return ONLY a single JSON action object — no markdown fences, no extra text:
{{"type": "click|type|key_combo|scroll|double_click|move|wait|open_app|open_url", "x": <int>, "y": <int>, "text": "<string>", "keys": ["<key>", ...], "direction": "up|down", "amount": <int>, "seconds": <float>, "app_name": "<string>", "url": "<string>", "confidence": <0.0-1.0>, "reason": "<why>"}}

For opening:
- Applications: {{"type": "open_app", "app_name": "Calculator"}}
- Websites: {{"type": "open_url", "url": "youtube.com"}}

Include only the fields relevant to the chosen action type.
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

    # 1. Bare JSON — only attempt if it looks like a JSON value
    if stripped.startswith(("[", "{")):
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

    # 3. First '['/'{' to last ']'/'}' — handles arrays/objects embedded in prose
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

    INTER_CALL_DELAY = 0    # 0 = no delay (Vertex AI has no RPM cap)

    def __init__(self, goal: str):
        self.goal = goal
        self.client = GeminiClient()
        self.playbook_manager = PlaybookManager()
        self.playbook: dict | None = None   # populated in run() if a match is found
        self.state: dict = {
            "goal": goal,
            "status": "running",          # running | completed | failed | waiting_for_user
            "steps_completed": [],
            "steps_failed": [],
            "correction_history": [],     # {"step": N, "tier": 1|2|3, "reason": "...", "success": bool}
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
        if self.playbook:
            prompt += "\n\n" + self.playbook_manager.format_for_prompt(self.playbook)
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
        screen_w, screen_h = pyautogui.size()
        description = current_step.get("description", "")
        prompt = NEXT_ACTION_PROMPT.format(
            description=description,
            screen_width=screen_w,
            screen_height=screen_h,
            screen_center_x=screen_w // 2,
            screen_center_y=screen_h // 2,
            screen_center_y_minus_50=screen_h // 2 - 50,
            screen_height_minus_30=screen_h - 30,
        )
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

    def get_alternative_action(
        self,
        screenshot_b64: str,
        step: dict,
        failure_description: str,
    ) -> dict:
        """
        Ask Gemini for a completely different action when the primary approach failed.

        Args:
            screenshot_b64:      Base64 JPEG of the current screen.
            step:                The step dict that failed.
            failure_description: Human-readable reason the previous attempt failed.

        Returns:
            Flat action dict suitable for execute_action().

        Raises:
            ValueError: If Gemini's response cannot be parsed as a JSON object.
        """
        screen_w, screen_h = pyautogui.size()
        description = step.get("description", "")
        expected_result = step.get("expected_result", "")
        prompt = ALTERNATIVE_ACTION_PROMPT.format(
            description=description,
            expected_result=expected_result,
            failure_description=failure_description,
            screen_width=screen_w,
            screen_height=screen_h,
            screen_center_x=screen_w // 2,
            screen_center_y=screen_h // 2,
            screen_center_y_minus_50=screen_h // 2 - 50,
            screen_height_minus_30=screen_h - 30,
        )
        logger.info(
            "[get_alternative_action] Requesting alternative for step: %r  failure: %s",
            description,
            failure_description,
        )

        response = self._gemini_call([prompt, _inline_image(screenshot_b64)])

        action = _extract_json(response.text, label="get_alternative_action")
        if not isinstance(action, dict):
            raise ValueError(
                f"[get_alternative_action] Expected a JSON object, got {type(action).__name__}."
            )

        logger.info("[get_alternative_action] Alternative action: %s", json.dumps(action))
        return action

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

        # ── Step 0: look up a matching playbook ──────────────────────────
        self.playbook = self.playbook_manager.find(self.goal)
        if self.playbook:
            logger.info("[run] Found matching playbook — injecting into context.")

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

            # ── Initial attempt ──────────────────────────────────────────
            success = False
            last_failure = "unknown failure"  # updated as each attempt fails

            # (a) Capture before screenshot
            logger.info("[run]   Capturing before-screenshot...")
            before_b64 = capture_frame_b64()

            # (b) Ask Gemini for the action to take
            try:
                action = self.get_next_action(before_b64, step)
            except (ValueError, Exception) as exc:
                logger.error("[run]   get_next_action failed: %s", exc)
                last_failure = str(exc)
                action = None

            if action is not None:
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
                    logger.warning("[run]   Action execution failed: %s", exec_result["error"])
                    last_failure = exec_result["error"] or "action execution failed"
                else:
                    # (d) Capture after screenshot and verify
                    logger.info("[run]   Capturing after-screenshot...")
                    after_b64 = capture_frame_b64()
                    try:
                        verdict = self.verify_step(before_b64, after_b64, expected_result)
                    except (ValueError, Exception) as exc:
                        logger.error("[run]   verify_step failed: %s", exc)
                        verdict = {"success": False, "description": str(exc), "confidence": 0.0}

                    if verdict.get("success"):
                        logger.info(
                            "[run]   Step %d verified OK (confidence=%.2f): %s",
                            step_num,
                            verdict.get("confidence", 0.0),
                            verdict.get("description", ""),
                        )
                        success = True
                    else:
                        last_failure = verdict.get("description", "verify failed")
                        logger.warning(
                            "[run]   Step %d initial attempt FAILED (confidence=%.2f): %s",
                            step_num,
                            verdict.get("confidence", 0.0),
                            last_failure,
                        )

            # ── TIER 1: wait 1s, retry same action ──────────────────────
            if not success and action is not None:
                logger.info(
                    "[run]   [TIER 1] Step %d — waiting 1s then retrying same action...",
                    step_num,
                )
                time.sleep(1)  # Reduced from 2s to 1s for faster execution

                logger.info("[run]   [TIER 1] Capturing before-screenshot...")
                t1_before_b64 = capture_frame_b64()

                if DRY_RUN:
                    logger.info("[run]   [DRY RUN] [TIER 1] Would execute: %s", json.dumps(action))
                    t1_exec = {
                        "success": True,
                        "action": action,
                        "detail": {"dry_run": True},
                        "error": None,
                    }
                else:
                    logger.info("[run]   [TIER 1] Executing same action: %s", json.dumps(action))
                    t1_exec = execute_action(action)

                t1_success = False
                t1_reason = last_failure
                if not t1_exec["success"]:
                    t1_reason = t1_exec["error"] or "tier-1 execution failed"
                    logger.warning("[run]   [TIER 1] Execution failed: %s", t1_reason)
                else:
                    logger.info("[run]   [TIER 1] Capturing after-screenshot...")
                    t1_after_b64 = capture_frame_b64()
                    try:
                        t1_verdict = self.verify_step(t1_before_b64, t1_after_b64, expected_result)
                    except (ValueError, Exception) as exc:
                        logger.error("[run]   [TIER 1] verify_step failed: %s", exc)
                        t1_verdict = {"success": False, "description": str(exc), "confidence": 0.0}

                    t1_success = t1_verdict.get("success", False)
                    t1_reason = t1_verdict.get("description", "")
                    if t1_success:
                        logger.info(
                            "[run]   [TIER 1] Step %d recovered (confidence=%.2f): %s",
                            step_num, t1_verdict.get("confidence", 0.0), t1_reason,
                        )
                    else:
                        logger.warning(
                            "[run]   [TIER 1] Step %d still FAILED (confidence=%.2f): %s",
                            step_num, t1_verdict.get("confidence", 0.0), t1_reason,
                        )
                        last_failure = t1_reason

                self.state["correction_history"].append({
                    "step": step_num,
                    "tier": 1,
                    "reason": f"Initial attempt failed: {last_failure}",
                    "success": t1_success,
                })
                if t1_success:
                    success = True

            # ── TIER 2: alternative path via Gemini ──────────────────────
            if not success:
                logger.info(
                    "[run]   [TIER 2] Step %d — asking Gemini for alternative approach...",
                    step_num,
                )
                logger.info("[run]   [TIER 2] Capturing fresh screenshot...")
                t2_before_b64 = capture_frame_b64()

                try:
                    t2_action = self.get_alternative_action(t2_before_b64, step, last_failure)
                except (ValueError, Exception) as exc:
                    logger.error("[run]   [TIER 2] get_alternative_action failed: %s", exc)
                    t2_action = None

                t2_success = False
                t2_reason = last_failure
                if t2_action is not None:
                    if DRY_RUN:
                        logger.info(
                            "[run]   [DRY RUN] [TIER 2] Would execute: %s", json.dumps(t2_action)
                        )
                        t2_exec = {
                            "success": True,
                            "action": t2_action,
                            "detail": {"dry_run": True},
                            "error": None,
                        }
                    else:
                        logger.info(
                            "[run]   [TIER 2] Executing alternative action: %s",
                            json.dumps(t2_action),
                        )
                        t2_exec = execute_action(t2_action)

                    if not t2_exec["success"]:
                        t2_reason = t2_exec["error"] or "tier-2 execution failed"
                        logger.warning("[run]   [TIER 2] Execution failed: %s", t2_reason)
                    else:
                        logger.info("[run]   [TIER 2] Capturing after-screenshot...")
                        t2_after_b64 = capture_frame_b64()
                        try:
                            t2_verdict = self.verify_step(
                                t2_before_b64, t2_after_b64, expected_result
                            )
                        except (ValueError, Exception) as exc:
                            logger.error("[run]   [TIER 2] verify_step failed: %s", exc)
                            t2_verdict = {
                                "success": False, "description": str(exc), "confidence": 0.0
                            }

                        t2_success = t2_verdict.get("success", False)
                        t2_reason = t2_verdict.get("description", "")
                        if t2_success:
                            logger.info(
                                "[run]   [TIER 2] Step %d recovered (confidence=%.2f): %s",
                                step_num, t2_verdict.get("confidence", 0.0), t2_reason,
                            )
                        else:
                            logger.warning(
                                "[run]   [TIER 2] Step %d still FAILED (confidence=%.2f): %s",
                                step_num, t2_verdict.get("confidence", 0.0), t2_reason,
                            )
                            last_failure = t2_reason

                self.state["correction_history"].append({
                    "step": step_num,
                    "tier": 2,
                    "reason": f"Tier-1 failed — tried alternative: {last_failure}",
                    "success": t2_success,
                })
                if t2_success:
                    success = True

            # ── TIER 3: human in the loop ────────────────────────────────
            if not success:
                self.state["status"] = "waiting_for_user"
                message = (
                    f"I'm stuck on: {description}. "
                    f"I tried twice and failed. "
                    f"Can you help me get past this step, then press Enter to continue?"
                )
                logger.warning("[run]   [TIER 3] Step %d — escalating to user.", step_num)
                print(f"\n[TIER 3 — HUMAN ASSIST] {message}")

                try:
                    import pyttsx3  # optional TTS — silent fallback if unavailable
                    _tts = pyttsx3.init()
                    _tts.say(message)
                    _tts.runAndWait()
                except Exception:
                    pass  # TTS unavailable; printed message is sufficient

                input()  # block until user presses Enter

                self.state["status"] = "running"
                logger.info("[run]   [TIER 3] User signalled ready. Retrying step %d...", step_num)

                logger.info("[run]   [TIER 3] Capturing fresh screenshot...")
                t3_before_b64 = capture_frame_b64()

                try:
                    t3_action = self.get_next_action(t3_before_b64, step)
                except (ValueError, Exception) as exc:
                    logger.error("[run]   [TIER 3] get_next_action failed: %s", exc)
                    t3_action = None

                t3_success = False
                t3_reason = last_failure
                if t3_action is not None:
                    if DRY_RUN:
                        logger.info(
                            "[run]   [DRY RUN] [TIER 3] Would execute: %s", json.dumps(t3_action)
                        )
                        t3_exec = {
                            "success": True,
                            "action": t3_action,
                            "detail": {"dry_run": True},
                            "error": None,
                        }
                    else:
                        logger.info(
                            "[run]   [TIER 3] Executing action: %s", json.dumps(t3_action)
                        )
                        t3_exec = execute_action(t3_action)

                    if not t3_exec["success"]:
                        t3_reason = t3_exec["error"] or "tier-3 execution failed"
                        logger.warning("[run]   [TIER 3] Execution failed: %s", t3_reason)
                    else:
                        logger.info("[run]   [TIER 3] Capturing after-screenshot...")
                        t3_after_b64 = capture_frame_b64()
                        try:
                            t3_verdict = self.verify_step(
                                t3_before_b64, t3_after_b64, expected_result
                            )
                        except (ValueError, Exception) as exc:
                            logger.error("[run]   [TIER 3] verify_step failed: %s", exc)
                            t3_verdict = {
                                "success": False, "description": str(exc), "confidence": 0.0
                            }

                        t3_success = t3_verdict.get("success", False)
                        t3_reason = t3_verdict.get("description", "")
                        if t3_success:
                            logger.info(
                                "[run]   [TIER 3] Step %d recovered after user assist "
                                "(confidence=%.2f): %s",
                                step_num, t3_verdict.get("confidence", 0.0), t3_reason,
                            )
                        else:
                            logger.warning(
                                "[run]   [TIER 3] Step %d still FAILED after user assist "
                                "(confidence=%.2f): %s",
                                step_num, t3_verdict.get("confidence", 0.0), t3_reason,
                            )

                self.state["correction_history"].append({
                    "step": step_num,
                    "tier": 3,
                    "reason": f"Tier-2 failed — required user assist: {t3_reason}",
                    "success": t3_success,
                })
                # Regardless of outcome, continue to next step (as specified)
                if t3_success:
                    success = True

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
            completed_count = len(self.state["steps_completed"])
            
            # Final verification: check if the goal was actually achieved
            # Capture a final screenshot and ask Gemini if the goal is complete
            logger.info("[run] Performing final goal verification...")
            final_b64 = capture_frame_b64()
            try:
                final_check_prompt = f"""Look at this screenshot. The user's goal was: "{self.goal}"

Is this goal currently achieved? Look for:
- If goal was to open something: is it open and visible?
- If goal was to search: are search results visible?
- If goal was to type something: is the text visible?
- If goal was to click something: did the expected result happen?

Return ONLY a JSON object: {{"goal_achieved": <true|false>, "reason": "<brief explanation>"}}"""
                
                final_response = self._gemini_call([final_check_prompt, _inline_image(final_b64)])
                final_check = _extract_json(final_response.text, label="final_check")
                
                if final_check.get("goal_achieved", False):
                    logger.info("[run] Final verification: Goal achieved! %s", final_check.get("reason", ""))
                    self.state["status"] = "completed"
                elif failed_count == 0:
                    self.state["status"] = "completed"
                elif failed_count < len(steps) and completed_count > 0:
                    self.state["status"] = "completed"   # partial success
                    logger.warning(
                        "[run] Task finished with %d failed step(s) out of %d.",
                        failed_count, len(steps),
                    )
                else:
                    self.state["status"] = "failed"
            except Exception as exc:
                logger.warning("[run] Final verification failed, using step-based logic: %s", exc)
                # Fallback to step-based logic
                if failed_count == 0:
                    self.state["status"] = "completed"
                elif failed_count < len(steps) and completed_count > 0:
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

        # ── Step 4: persist a playbook if the task completed ─────────────
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
    corrections = final_state.get("correction_history", [])
    if corrections:
        print(f"\nCorrection history ({len(corrections)} attempt(s)):")
        for c in corrections:
            status = "OK" if c["success"] else "FAIL"
            print(f"  [TIER {c['tier']}][{status}] Step {c['step']}: {c['reason']}")
