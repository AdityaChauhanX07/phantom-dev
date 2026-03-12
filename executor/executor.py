"""
Action executor for Phantom-Dev.
Receives flat action dicts from the agent and performs them on the local machine.

Action format (flat, no nested "params" key):
    {"type": "click",        "x": 412, "y": 280, "button": "left"}
    {"type": "double_click", "x": 412, "y": 280}
    {"type": "type",         "text": "hello world"}
    {"type": "key_combo",    "keys": ["ctrl", "c"]}
    {"type": "scroll",       "x": 700, "y": 400, "direction": "down", "amount": 3}
    {"type": "move",         "x": 500, "y": 300}
    {"type": "wait",         "seconds": 1.5}
    {"type": "screenshot",   "reason": "verify state"}
    {"type": "open_app",     "app_name": "Calculator"}
    {"type": "open_url",     "url": "https://youtube.com"}

Optional field on any action:
    "confidence": 0.0–1.0   — skipped with a warning if below CONFIDENCE_THRESHOLD
"""

import logging
import subprocess
import time
from typing import Any

import pyautogui

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# ---------------------------------------------------------------------------
# Global pyautogui settings
# ---------------------------------------------------------------------------

# Moving the mouse to any screen corner raises FailSafeException — abort signal
pyautogui.FAILSAFE = True
# Small inter-call pause to avoid overwhelming the OS input queue
pyautogui.PAUSE = 0.05

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD = 0.3  # Lowered to 0.3 for testing - allows actions even when element visibility is uncertain
SETTLE_DELAY = 0.2          # Reduced from 0.5 to 0.2 seconds for faster execution
NO_SETTLE = {"wait", "screenshot"}


# ---------------------------------------------------------------------------
# Screen bounds helpers
# ---------------------------------------------------------------------------

def _screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary monitor."""
    return pyautogui.size()


def _check_bounds(x: int | float, y: int | float) -> None:
    """
    Raise ValueError if (x, y) falls outside the primary monitor's bounds.
    pyautogui's FAILSAFE only triggers at the very corner, so we validate
    explicitly before any move/click to surface clear errors early.
    """
    w, h = _screen_size()
    if not (0 <= x < w and 0 <= y < h):
        raise ValueError(
            f"Coordinates ({x}, {y}) are outside screen bounds ({w}x{h}). "
            "Refusing to execute action."
        )


# ---------------------------------------------------------------------------
# Individual action handlers
# Each receives the full flat action dict and returns a detail dict.
# ---------------------------------------------------------------------------

def _handle_click(action: dict) -> dict:
    x, y = action["x"], action["y"]
    _check_bounds(x, y)
    button = action.get("button", "left")
    pyautogui.moveTo(x, y, duration=0.2)
    time.sleep(0.1)
    pyautogui.click(x, y, button=button)
    return {"x": x, "y": y, "button": button}


def _handle_double_click(action: dict) -> dict:
    x, y = action["x"], action["y"]
    _check_bounds(x, y)
    pyautogui.moveTo(x, y, duration=0.2)
    time.sleep(0.1)
    pyautogui.doubleClick(x, y)
    return {"x": x, "y": y}


def _handle_type(action: dict) -> dict:
    text = action["text"]
    # If coordinates are provided, click on the field first to focus it
    if "x" in action and "y" in action:
        x, y = action["x"], action["y"]
        logger.info("Clicking on input field at (%d, %d) before typing...", x, y)
        pyautogui.click(x, y)
        time.sleep(0.1)  # Brief pause for field to focus
        # Select all existing text (Cmd+A) before typing new text
        pyautogui.hotkey("ctrl", "a")
        time.sleep(0.05)

    # typewrite is ASCII-safe; use pyperclip+paste for unicode if needed
    interval = action.get("interval", 0.05)
    pyautogui.typewrite(text, interval=interval)
    return {"text": text, "x": action.get("x"), "y": action.get("y")}


def _handle_key_combo(action: dict) -> dict:
    keys = action["keys"]
    if not isinstance(keys, list) or len(keys) == 0:
        raise ValueError(f"'keys' must be a non-empty list, got: {keys!r}")
    pyautogui.hotkey(*keys)
    return {"keys": keys}


def _handle_scroll(action: dict) -> dict:
    x, y = action.get("x"), action.get("y")
    if x is not None and y is not None:
        _check_bounds(x, y)
        pyautogui.moveTo(x, y)

    direction = action.get("direction", "down").lower()
    amount = int(action.get("amount", 3))
    # pyautogui.scroll: positive = up, negative = down
    clicks = amount if direction == "up" else -amount
    pyautogui.scroll(clicks)
    return {"x": x, "y": y, "direction": direction, "amount": amount}


def _handle_move(action: dict) -> dict:
    x, y = action["x"], action["y"]
    _check_bounds(x, y)
    duration = action.get("duration", 0.2)
    pyautogui.moveTo(x, y, duration=duration)
    return {"x": x, "y": y}


def _handle_wait(action: dict) -> dict:
    seconds = float(action.get("seconds", 1.0))
    if seconds < 0:
        raise ValueError(f"'seconds' must be non-negative, got {seconds}")
    time.sleep(seconds)
    return {"seconds": seconds}


def _handle_screenshot(action: dict) -> dict:
    """
    Capture the current screen state and return the path/b64 reference.
    Delegates to capture.py so the image can be forwarded to the agent.
    """
    from capture import capture_frame_b64
    reason = action.get("reason", "")
    b64 = capture_frame_b64()
    logger.info("Screenshot taken — reason: %s | size: %d chars", reason or "(none)", len(b64))
    return {"reason": reason, "screenshot_b64_length": len(b64), "screenshot_b64": b64}


def _handle_open_app(action: dict) -> dict:
    """
    Open an application by name using macOS 'open -a' command.
    This is more reliable than clicking Dock icons.
    
    Args:
        action: {"type": "open_app", "app_name": "Calculator"}
    
    Returns:
        {"app_name": str, "success": bool}
    """
    app_name = action.get("app_name", "")
    if not app_name:
        raise ValueError("'app_name' is required for 'open_app' action")
    
    logger.info("Opening application: %s", app_name)
    try:
        # Use 'open -a' command to launch the app
        result = subprocess.run(
            ["open", "-a", app_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            logger.info("Successfully opened: %s", app_name)
            # Wait a bit for the app to launch
            time.sleep(1.0)
            return {"app_name": app_name, "success": True}
        else:
            error_msg = result.stderr.strip() or "Unknown error"
            logger.warning("Failed to open %s: %s", app_name, error_msg)
            return {"app_name": app_name, "success": False, "error": error_msg}
    except subprocess.TimeoutExpired:
        logger.warning("Timeout opening %s", app_name)
        return {"app_name": app_name, "success": False, "error": "Timeout"}
    except Exception as exc:
        logger.error("Error opening %s: %s", app_name, exc)
        return {"app_name": app_name, "success": False, "error": str(exc)}


def _handle_open_url(action: dict) -> dict:
    """
    Open a URL in the default browser using macOS 'open' command.
    This works for any website: youtube.com, google.com, jira.com, etc.
    
    Args:
        action: {"type": "open_url", "url": "https://youtube.com"}
               or {"type": "open_url", "url": "youtube.com"} (https:// will be added)
    
    Returns:
        {"url": str, "success": bool}
    """
    url = action.get("url", "")
    if not url:
        raise ValueError("'url' is required for 'open_url' action")
    
    # Add https:// if not present
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    
    logger.info("Opening URL: %s", url)
    try:
        # Use 'open' command to open URL in default browser
        result = subprocess.run(
            ["open", url],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            logger.info("Successfully opened URL: %s", url)
            # Wait a bit for the browser to load
            time.sleep(2.0)
            return {"url": url, "success": True}
        else:
            error_msg = result.stderr.strip() or "Unknown error"
            logger.warning("Failed to open URL %s: %s", url, error_msg)
            return {"url": url, "success": False, "error": error_msg}
    except subprocess.TimeoutExpired:
        logger.warning("Timeout opening URL %s", url)
        return {"url": url, "success": False, "error": "Timeout"}
    except Exception as exc:
        logger.error("Error opening URL %s: %s", url, exc)
        return {"url": url, "success": False, "error": str(exc)}


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

_HANDLERS: dict[str, Any] = {
    "click":        _handle_click,
    "double_click": _handle_double_click,
    "type":         _handle_type,
    "key_combo":    _handle_key_combo,
    "scroll":       _handle_scroll,
    "move":         _handle_move,
    "wait":         _handle_wait,
    "screenshot":   _handle_screenshot,
    "open_app":     _handle_open_app,
    "open_url":     _handle_open_url,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_action(action: dict) -> dict:
    """
    Execute a single flat action dict.

    Args:
        action: Flat dict with at minimum a "type" key plus type-specific fields.
                Optional "confidence" key (0.0–1.0) — actions below
                CONFIDENCE_THRESHOLD (0.75) are skipped with a warning.

    Returns:
        {
            "success": True | False,
            "action":  <original action dict>,
            "detail":  <handler-returned detail dict, or None on failure>,
            "error":   None | "<error message>",
        }
    """
    action_type = action.get("type")

    # ── Confidence gate ─────────────────────────────────────────────────────
    confidence = action.get("confidence")
    if confidence is not None and confidence < CONFIDENCE_THRESHOLD:
        msg = (
            f"Action '{action_type}' skipped — confidence {confidence:.2f} "
            f"is below threshold {CONFIDENCE_THRESHOLD}."
        )
        logger.warning(msg)
        return {"success": False, "action": action, "detail": None, "error": msg}

    # ── Handler lookup ───────────────────────────────────────────────────────
    handler = _HANDLERS.get(action_type)
    if handler is None:
        msg = (
            f"Unknown action type '{action_type}'. "
            f"Supported: {list(_HANDLERS.keys())}"
        )
        logger.error(msg)
        return {"success": False, "action": action, "detail": None, "error": msg}

    # ── Execution ────────────────────────────────────────────────────────────
    logger.info("Executing: %s", action)
    try:
        detail = handler(action)
    except pyautogui.FailSafeException:
        msg = "pyautogui FAILSAFE triggered — mouse reached a screen corner. Aborting."
        logger.error(msg)
        return {"success": False, "action": action, "detail": None, "error": msg}
    except (ValueError, KeyError, TypeError) as exc:
        msg = f"{type(exc).__name__}: {exc}"
        logger.error("Action '%s' failed — %s", action_type, msg)
        return {"success": False, "action": action, "detail": None, "error": msg}
    except Exception as exc:
        msg = f"Unexpected error during '{action_type}': {exc}"
        logger.exception(msg)
        return {"success": False, "action": action, "detail": None, "error": msg}

    logger.info("Completed: %s → %s", action_type, detail)

    # ── Settle delay (skip for wait and screenshot) ──────────────────────────
    if action_type not in NO_SETTLE:
        time.sleep(SETTLE_DELAY)

    return {"success": True, "action": action, "detail": detail, "error": None}


def run_action_sequence(actions: list[dict]) -> dict:
    """
    Execute a list of actions in order, stopping at the first failure.

    Args:
        actions: Ordered list of flat action dicts.

    Returns:
        {
            "completed": <number of successfully executed actions>,
            "total":     <total actions>,
            "stopped_at": <0-based index of first failure, or None>,
            "results":  [<result dict per action>],
        }
    """
    results = []
    stopped_at = None

    for i, action in enumerate(actions):
        result = execute_action(action)
        results.append(result)

        if not result["success"]:
            stopped_at = i
            logger.warning(
                "Sequence halted at step %d/%d — %s",
                i + 1, len(actions), result["error"],
            )
            break

    completed = stopped_at if stopped_at is not None else len(actions)
    return {
        "completed": completed,
        "total": len(actions),
        "stopped_at": stopped_at,
        "results": results,
    }


# ---------------------------------------------------------------------------
# Entry point — manual smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    time.sleep(2)  # give user time to switch focus

    sequence = [
        {"type": "move",        "x": 500,  "y": 400},
        {"type": "click",       "x": 500,  "y": 400, "button": "left"},
        {"type": "double_click","x": 500,  "y": 400},
        {"type": "type",        "text": "hello phantom-dev"},
        {"type": "key_combo",   "keys": ["ctrl", "a"]},
        {"type": "scroll",      "x": 500,  "y": 400, "direction": "down", "amount": 3},
        {"type": "wait",        "seconds": 0.5},
        {"type": "screenshot",  "reason": "smoke test verify"},
        # Low-confidence action — should be skipped
        {"type": "click",       "x": 100,  "y": 100, "confidence": 0.5},
        # Out-of-bounds action — should fail gracefully
        {"type": "click",       "x": 99999, "y": 99999},
    ]

    summary = run_action_sequence(sequence)
    import json
    print(json.dumps(
        {k: v for k, v in summary.items() if k != "results"},
        indent=2,
    ))
    for i, r in enumerate(summary["results"]):
        status = "OK " if r["success"] else "ERR"
        print(f"  [{status}] step {i+1}: {r['action']['type']} — {r['error'] or r['detail']}")
