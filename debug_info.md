# Debug Info — Phantom Dev Executor

## 1. Full Contents of `executor/capture.py`

```python
"""
Screen capture module for Phantom-Dev executor.
Uses mss for fast, cross-platform screenshot capture.
When run directly, captures the primary monitor, sends the screenshot to
Gemini 2.0 Flash, and prints a structured JSON description of the screen.
"""

import io
import json
import base64
import logging
from typing import Optional

from PIL import Image
import mss
import mss.tools

from gemini_client import GeminiClient

logger = logging.getLogger(__name__)


def capture_frame(
    monitor_index: int = 1,
    region: Optional[dict] = None,
    encode: str = "jpeg",
) -> bytes:
    """
    Capture a single frame from the specified monitor (or region).

    Args:
        monitor_index: 1-based monitor index (0 = all monitors combined).
        region: Optional dict with keys top, left, width, height (pixels).
                If provided, overrides monitor_index.
        encode: Output image format — 'jpeg' (default, smaller) or 'png'.

    Returns:
        Raw image bytes in the requested format.
    """
    with mss.mss() as sct:
        target = region if region else sct.monitors[monitor_index]
        raw = sct.grab(target)

        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format=encode.upper())
        return buf.getvalue()


def capture_frame_b64(monitor_index: int = 1, encode: str = "jpeg") -> str:
    """
    Capture a frame and return it as a base64-encoded string, suitable for
    embedding in JSON payloads sent to the agent or Gemini.
    """
    raw = capture_frame(monitor_index=monitor_index, encode=encode)
    return base64.b64encode(raw).decode("utf-8")


def get_monitor_info() -> list[dict]:
    """Return metadata for all connected monitors."""
    with mss.mss() as sct:
        return list(sct.monitors)


def analyze_current_screen(context: str = "") -> dict:
    """
    Capture the primary monitor and ask Gemini 2.0 Flash to describe it.

    Args:
        context: Optional hint passed to the model (e.g. current task description).

    Returns:
        Parsed dict with keys: screen_description, visible_apps,
        active_window, ui_elements.
    """
    screenshot_b64 = capture_frame_b64()
    client = GeminiClient()
    return client.analyze_screen(screenshot_b64, context=context)


# ---------------------------------------------------------------------------
# Entry point — capture + Gemini analysis
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    monitors = get_monitor_info()
    print(f"Detected {len(monitors) - 1} monitor(s): {monitors[1:]}\n")

    print("Capturing primary monitor...")
    screenshot_b64 = capture_frame_b64()
    print(f"Screenshot captured: {len(screenshot_b64)} base64 chars\n")

    print("Sending to Gemini 2.0 Flash for analysis...")
    client = GeminiClient()
    analysis = client.analyze_screen(screenshot_b64, context="manual capture test")

    print("\n--- Screen Analysis ---")
    print(json.dumps(analysis, indent=2))
```

---

## 2. Full Contents of `executor/executor.py`

```python
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
        pyautogui.hotkey("command", "a")
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
```

---

## 3. Full Contents of `executor/gemini_client.py`

```python
"""
Gemini client for Phantom-Dev executor.
Wraps google-genai calls for screen analysis and action planning.
"""

import json
import logging
import os
import re
from typing import Optional

from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

MODEL = "gemini-2.5-flash"

# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

ANALYZE_SCREEN_PROMPT = """\
You are a desktop automation assistant. Analyse the screenshot provided and \
return ONLY a JSON object — no markdown fences, no extra text — matching this schema:

{{
  "screen_description": "<one concise sentence describing the overall screen>",
  "visible_apps": ["<app name>", ...],
  "active_window": "<title of the focused window, or null if unclear>",
  "ui_elements": [
    {{
      "type": "<button | input | menu | link | text | image | icon | scrollbar | other>",
      "text": "<visible label or placeholder, empty string if none>",
      "approximate_location": "<top-left | top-center | top-right | center-left | center | center-right | bottom-left | bottom-center | bottom-right>"
    }}
  ]
}}

Additional context from the caller: {context}
"""

PLAN_ACTIONS_PROMPT = """\
You are a desktop automation planner. Given a user goal and a structured \
description of the current screen state, return ONLY a JSON object — no \
markdown fences, no extra text — matching this schema:

{{
  "goal_summary": "<restate the goal in one sentence>",
  "feasible": <true | false>,
  "reasoning": "<brief explanation of your plan or why the goal is not feasible>",
  "steps": [
    {{
      "step": <1-based integer>,
      "action": {{
        "type": "<click | type | scroll | key_combo | move | wait>",
        "params": {{ ... }}
      }},
      "description": "<human-readable explanation of this step>"
    }}
  ]
}}

User goal: {goal}

Current screen analysis:
{screen_analysis}
"""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class GeminiClient:
    """
    Thin wrapper around google-genai for Phantom-Dev executor tasks.

    Usage:
        client = GeminiClient()
        analysis = client.analyze_screen(screenshot_b64, context="user is on Chrome")
        plan = client.plan_actions("Open a new tab", analysis)
    """

    def __init__(self, api_key: Optional[str] = None):
        project  = os.getenv("GCP_PROJECT_ID")
        location = os.getenv("GCP_LOCATION", "us-central1")

        if project:
            self._client = genai.Client(
                vertexai=True,
                project=project,
                location=location,
            )
            logger.info(
                "GeminiClient initialised with Vertex AI — project=%s location=%s model=%s",
                project, location, MODEL,
            )
        else:
            key = api_key or os.getenv("GEMINI_API_KEY")
            if not key:
                raise EnvironmentError(
                    "Neither GCP_PROJECT_ID nor GEMINI_API_KEY is set. "
                    "Add one to your .env file."
                )
            logger.warning(
                "GeminiClient falling back to AI Studio key — rate limits apply."
            )
            self._client = genai.Client(api_key=key)
            logger.info("GeminiClient initialised with model %s", MODEL)

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def analyze_screen(self, screenshot_base64: str, context: str = "") -> dict:
        """
        Send a base64-encoded screenshot to Gemini and receive a structured
        JSON description of what is visible on screen.

        Args:
            screenshot_base64: Base64-encoded JPEG/PNG image string.
            context: Optional free-text hint for the model (e.g. current task).

        Returns:
            Parsed dict matching the screen analysis schema.

        Raises:
            ValueError: If Gemini returns content that cannot be parsed as JSON.
        """
        prompt = ANALYZE_SCREEN_PROMPT.format(context=context or "none provided")

        import base64 as _base64
        image_part = types.Part.from_bytes(
            data=_base64.b64decode(screenshot_base64),
            mime_type="image/jpeg",
        )

        logger.debug("Sending screenshot to Gemini for analysis (%d chars b64)", len(screenshot_base64))
        response = self._client.models.generate_content(
            model=MODEL,
            contents=[prompt, image_part],
        )
        return self._parse_json_response(response.text, label="analyze_screen")

    def plan_actions(self, goal: str, screen_analysis: dict) -> dict:
        """
        Given a natural-language goal and the current screen analysis, ask
        Gemini to produce a step-by-step action plan for the executor.

        Args:
            goal: Natural-language task description, e.g. "Open Gmail".
            screen_analysis: Dict returned by analyze_screen().

        Returns:
            Parsed dict matching the action plan schema.

        Raises:
            ValueError: If Gemini returns content that cannot be parsed as JSON.
        """
        prompt = PLAN_ACTIONS_PROMPT.format(
            goal=goal,
            screen_analysis=json.dumps(screen_analysis, indent=2),
        )

        logger.debug("Requesting action plan for goal: %r", goal)
        response = self._client.models.generate_content(
            model=MODEL,
            contents=contents,
        )
        return self._parse_json_response(response.text, label="plan_actions")

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _parse_json_response(raw: str, label: str) -> dict:
        """
        Robustly parse a JSON string from Gemini's response text.

        Strips common wrapping artefacts (```json ... ```) before parsing.
        Raises ValueError with a clear message on failure.
        """
        cleaned = raw.strip()
        fenced = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", cleaned)
        if fenced:
            cleaned = fenced.group(1).strip()

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as exc:
            logger.error("[%s] JSON parse failed.\nRaw response:\n%s", label, raw)
            raise ValueError(
                f"GeminiClient.{label}: could not parse response as JSON.\n"
                f"Parse error: {exc}\n"
                f"Raw response (first 500 chars): {raw[:500]}"
            ) from exc
```

---

## 4. Full Contents of `executor/playbook_manager.py`

```python
"""
PlaybookManager — saves and loads successful task traces.

Successful task runs are persisted as JSON playbooks and can be retrieved
via fuzzy goal matching (Jaccard word overlap) so Gemini can use prior
experience as guidance when planning similar tasks.
"""

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

PLAYBOOKS_DIR = Path("executor/playbooks")


def _slugify(text: str) -> str:
    """Lowercase, spaces → hyphens, strip everything except [a-z0-9-]."""
    text = text.lower().strip()
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"[^a-z0-9-]", "", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-")


def _goal_words(goal: str) -> set[str]:
    """Return non-trivial lowercase words from a goal string."""
    stopwords = {"a", "an", "the", "and", "or", "to", "in", "on", "at", "of", "for"}
    return {w for w in re.findall(r"[a-z]+", goal.lower()) if w not in stopwords}


class PlaybookManager:
    """
    Saves and loads successful task traces (playbooks).

    Playbooks are stored as JSON files in ``playbooks_dir``.  Each file holds
    the goal, the completed steps, and metadata that lets the orchestrator
    inject prior experience into Gemini prompts.

    Usage::

        pm = PlaybookManager()
        pm.save(final_state)          # persists if task completed
        pb = pm.find("open chrome")   # fuzzy goal match
        if pb:
            hint = pm.format_for_prompt(pb)
    """

    def __init__(self):
        self.playbooks_dir = PLAYBOOKS_DIR
        self.playbooks_dir.mkdir(parents=True, exist_ok=True)
        logger.debug("[PlaybookManager] playbooks_dir=%s", self.playbooks_dir.resolve())

    # ------------------------------------------------------------------ #

    def save(self, task_state: dict) -> str:
        """
        Persist a completed task trace as a playbook JSON file.

        Only saves when ``task_state["status"] == "completed"`` and at least
        one step was completed.  Silently returns ``""`` otherwise.

        Args:
            task_state: Final state dict returned by ``TaskOrchestrator.run()``.

        Returns:
            Absolute path of the saved file, or ``""`` if nothing was saved.
        """
        if task_state.get("status") != "completed":
            logger.debug("[PlaybookManager.save] Skipping — status=%s", task_state.get("status"))
            return ""

        steps_completed = task_state.get("steps_completed", [])
        if not steps_completed:
            logger.debug("[PlaybookManager.save] Skipping — no completed steps.")
            return ""

        total_steps = len(steps_completed) + len(task_state.get("steps_failed", []))
        success_rate = len(steps_completed) / total_steps if total_steps else 1.0

        playbook = {
            "goal": task_state["goal"],
            "saved_at": datetime.utcnow().isoformat(),
            "steps": steps_completed,
            "correction_history": task_state.get("correction_history", []),
            "success_rate": round(success_rate, 4),
        }

        slug = _slugify(task_state["goal"])[:60]   # cap slug length
        uid = uuid.uuid4().hex[:8]
        filename = f"{slug}-{uid}.json"
        filepath = self.playbooks_dir / filename

        with filepath.open("w", encoding="utf-8") as grab(target)
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        buf = io.BytesIO()
        img.save(buf, format=encode.upper())
        return buf.getvalue()


def capture_frame_b64(monitor_index: int = 1, encode: str = "jpeg") -> str:
    """
    Capture a frame and return it as a base64-encoded string, suitable for
    embedding in JSON payloads sent to the agent or Gemini.
    """
    raw = capture_frame(monitor_index=monitor_index, encode=encode)
    return base64.b64encode(raw).decode("utf-8")
```

---

## 5. From `executor/orchestrator.py`

### DRY_RUN
```python
DRY_RUN = False
```

### INTER_CALL_DELAY
```python
INTER_CALL_DELAY = 0    # 0 = no delay (Vertex AI has no RPM cap)
```

### Model Name Used in `_gemini_call`
```python
def _do_call():
    return self.client._client.models.generate_content(
        model="gemini-2.5-flash",
        contents=contents,
    )
```

---

## 6. Full Contents of `executor/requirements.txt`

```
mss>=9.0.1
pyautogui>=0.9.54
pynput>=1.7.6
websockets>=12.0
python-dotenv>=1.0.1
Pillow>=10.4.0
google-genai>=1.0.0
```

---

## 7. Answers to Questions

### What library is used for screen capture?
**Answer:** `mss` (Multi-Screen Shot) — a fast, cross-platform screenshot library. The code uses `mss.mss()` to capture screenshots.

### What is the screenshot format sent to Gemini?
**Answer:** 
- **Format:** JPEG (default, can be PNG)
- **Encoding:** Base64-encoded string
- **Function:** `capture_frame_b64()` returns a base64-encoded JPEG string
- **MIME type sent to Gemini:** `image/jpeg` (see `gemini_client.py` line 139)

### Does capture.py account for Retina/HiDPI scaling?
**Answer:** **NO** — There is no explicit Retina/HiDPI scaling handling in `capture.py`. The code uses `mss` directly which captures at the physical resolution. On macOS Retina displays, this means:
- `mss` captures at the physical pixel resolution (e.g., 2880x1800 for a 1440x900 logical display)
- No scaling transformation is applied
- Gemini receives the full-resolution image

**Potential Issue:** If Gemini returns coordinates based on the full-resolution image, but `pyautogui` uses logical coordinates, there could be a mismatch. However, the code does not transform coordinates, so this could be a problem on Retina displays.

### What is the logical screen size detection method?
**Answer:** 
- **Method:** `pyautogui.size()` 
- **Location:** `executor.py` function `_screen_size()` (line 53-55)
- **Returns:** `(width, height)` tuple of the primary monitor in **logical pixels**
- **Usage:** Used for bounds checking (`_check_bounds()`) to validate coordinates before execution

### Does executor.py click at the exact coordinates returned by Gemini, or does it transform them?
**Answer:** **Exact coordinates** — `executor.py` clicks at the exact coordinates returned by Gemini without any transformation:
- `_handle_click()` directly uses `action["x"]` and `action["y"]` (lines 78-84)
- No scaling, no offset, no transformation
- Coordinates are only validated for bounds (`_check_bounds()`) but not transformed

**Potential Issue:** If Gemini returns coordinates based on a high-resolution screenshot (Retina), but `pyautogui` expects logical coordinates, clicks will miss their targets.

### Is there any coordinate scaling between capture and execution?
**Answer:** **NO** — There is no coordinate scaling between capture and execution:
- `capture.py` captures at physical resolution (via `mss`)
- `executor.py` executes at logical coordinates (via `pyautogui`)
- No transformation layer exists between them

**This is a potential bug on Retina/HiDPI displays** where:
- Screenshot: 2880x1800 pixels (physical)
- Execution: 1440x900 logical pixels
- Gemini might return coordinates like (1440, 900) thinking it's the center, but that's actually the bottom-right corner in logical space

### What Vertex AI model is used? What region?
**Answer:**
- **Model:** `gemini-2.5-flash`
- **Region:** `us-central1` (default, can be overridden via `GCP_LOCATION` env var)
- **Location in code:** 
  - `gemini_client.py` line 20: `MODEL = "gemini-2.5-flash"`
  - `gemini_client.py` line 90: `location = os.getenv("GCP_LOCATION", "us-central1")`
  - `orchestrator.py` line 488: `model="gemini-2.5-flash"`

### How is the Gemini client authenticated? (service account, ADC, API key?)
**Answer:** **Application Default Credentials (ADC) for Vertex AI, or API key fallback:**
- **Primary method (if `GCP_PROJECT_ID` is set):** Vertex AI using Application Default Credentials
  - Uses `genai.Client(vertexai=True, project=project, location=location)`
  - Relies on `gcloud auth application-default login` for local credentials
  - No explicit service account key needed
- **Fallback method (if `GCP_PROJECT_ID` is not set):** AI Studio API key
  - Uses `genai.Client(api_key=key)`
  - Reads `GEMINI_API_KEY` from environment
- **Code location:** `gemini_client.py` lines 88-113

---

## Summary of Potential Issues

1. **Retina/HiDPI Coordinate Mismatch:** The most critical issue. Screenshots are captured at physical resolution, but execution uses logical coordinates. Gemini may return coordinates that don't match the logical coordinate space.

2. **No Coordinate Transformation:** There's no layer to convert between physical screenshot coordinates and logical execution coordinates.

3. **Model Consistency:** Both `gemini_client.py` and `orchestrator.py` use `gemini-2.5-flash`, which is good.

4. **Authentication:** Properly configured to use Vertex AI with ADC, which is the recommended approach for production.
