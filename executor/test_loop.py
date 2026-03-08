"""
End-to-end test loop for Phantom-Dev executor.

Steps:
  1. Capture a screenshot of the current screen.
  2. Ask Gemini 2.5 Flash to locate the VS Code Explorer icon and return a
     click action as JSON.
  3. Parse the action from Gemini's response.
  4. Execute (or dry-run) the action via execute_action().
  5. Capture a second screenshot and compare screen descriptions.

DRY_RUN = True   → print the action Gemini wants to take, do NOT execute it.
DRY_RUN = False  → execute the action for real via pyautogui.
"""

import json
import logging
import re
import sys

from capture import capture_frame_b64, analyze_current_screen
from executor import execute_action
from gemini_client import GeminiClient

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DRY_RUN = False   # Set to False to let pyautogui actually click

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gemini prompt
# ---------------------------------------------------------------------------

FIND_EXPLORER_PROMPT = """\
Look at this screen. Find the VS Code Explorer icon on the left sidebar.
Return a single action to click it as JSON with NO markdown fences, no extra text:
{"type": "click", "x": <actual x coordinate>, "y": <actual y coordinate>, "confidence": 0.9, "reason": "clicking explorer icon"}
"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_json(text: str) -> dict:
    """
    Parse the first JSON object found in Gemini's response text.
    Handles both bare JSON and responses wrapped in markdown fences.

    Raises:
        ValueError: if no valid JSON object can be extracted.
    """
    # Try the whole response first (bare JSON)
    stripped = text.strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    # Strip markdown fences (```json ... ``` or ``` ... ```)
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped)
    if fenced:
        try:
            return json.loads(fenced.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Last resort: find the first {...} block in the response
    brace = re.search(r"\{[\s\S]*?\}", stripped)
    if brace:
        try:
            return json.loads(brace.group(0))
        except json.JSONDecodeError:
            pass

    raise ValueError(
        f"Could not extract a JSON object from Gemini's response.\n"
        f"Raw response (first 500 chars): {text[:500]}"
    )


def _describe(analysis: dict) -> str:
    """Return the screen_description field, or a fallback string."""
    return analysis.get("screen_description") or "(no description returned)"


# ---------------------------------------------------------------------------
# Main test loop
# ---------------------------------------------------------------------------

def run_test_loop() -> None:
    mode_label = "DRY RUN" if DRY_RUN else "LIVE"
    logger.info("=== Phantom-Dev end-to-end test loop [%s] ===", mode_label)

    client = GeminiClient()

    # ── Step 1: capture before screenshot ───────────────────────────────────
    logger.info("Step 1 — Capturing screenshot...")
    before_b64 = capture_frame_b64()
    logger.info("  Captured %d base64 chars.", len(before_b64))

    # ── Step 2: ask Gemini to locate the Explorer icon ───────────────────────
    logger.info("Step 2 — Sending screenshot to Gemini 2.5 Flash...")
    response = client._client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            FIND_EXPLORER_PROMPT,
            {
                "inline_data": {
                    "mime_type": "image/jpeg",
                    "data": before_b64,
                }
            },
        ],
    )
    raw_response = response.text
    logger.info("  Gemini raw response: %s", raw_response.strip())

    # ── Step 3: parse the action JSON ────────────────────────────────────────
    logger.info("Step 3 — Parsing action from Gemini response...")
    try:
        action = _extract_json(raw_response)
    except ValueError as exc:
        logger.error("  Failed to parse action: %s", exc)
        sys.exit(1)

    logger.info("  Parsed action: %s", json.dumps(action))

    # ── Step 4: execute (or dry-run) the action ──────────────────────────────
    if DRY_RUN:
        logger.info("Step 4 — [DRY RUN] Would execute: %s", json.dumps(action))
        exec_result = {
            "success": True,
            "action": action,
            "detail": {"dry_run": True},
            "error": None,
        }
    else:
        logger.info("Step 4 — Executing action via pyautogui...")
        exec_result = execute_action(action)
        if not exec_result["success"]:
            logger.error("  Action failed: %s", exec_result["error"])
            sys.exit(1)
        logger.info("  Action succeeded: %s", exec_result["detail"])

    # ── Step 5: capture after screenshot + describe both ────────────────────
    logger.info("Step 5 — Capturing post-action screenshot and analysing both...")

    before_analysis = analyze_current_screen(context="before clicking VS Code Explorer")

    # Re-use already-captured before_b64 for the "before" description to avoid
    # a redundant capture; take a fresh shot for "after".
    after_b64 = capture_frame_b64()
    after_analysis = client.analyze_screen(after_b64, context="after clicking VS Code Explorer")

    # ── Results ──────────────────────────────────────────────────────────────
    print()
    print(f"Before action: {_describe(before_analysis)}")
    print(f"After action:  {_describe(after_analysis)}")
    print()
    print("Gemini action:", json.dumps(action, indent=2))
    print("Execution result:", json.dumps(
        {k: v for k, v in exec_result.items() if k != "action"},
        indent=2,
    ))


if __name__ == "__main__":
    run_test_loop()
