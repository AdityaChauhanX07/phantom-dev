"""
Action executor for Phantom-Dev.
Receives action dicts from the agent and performs them on the local machine.
"""

import time
import logging
import pyautogui
from typing import Any

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Safety: pyautogui will raise an exception if the mouse reaches a corner
pyautogui.FAILSAFE = True
# Small pause between pyautogui calls to avoid overwhelming the OS
pyautogui.PAUSE = 0.05


# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def _handle_click(params: dict) -> dict:
    """
    Left-click (or right/double-click) at (x, y).
    params: { x, y, button="left", clicks=1, interval=0.1 }
    """
    x = params["x"]
    y = params["y"]
    button = params.get("button", "left")
    clicks = params.get("clicks", 1)
    interval = params.get("interval", 0.1)
    pyautogui.click(x=x, y=y, button=button, clicks=clicks, interval=interval)
    return {"action": "click", "x": x, "y": y, "button": button, "clicks": clicks}


def _handle_type(params: dict) -> dict:
    """
    Type a string with optional per-character interval.
    params: { text, interval=0.05 }
    """
    text = params["text"]
    interval = params.get("interval", 0.05)
    pyautogui.typewrite(text, interval=interval)
    return {"action": "type", "text": text}


def _handle_scroll(params: dict) -> dict:
    """
    Scroll at (x, y) by `amount` clicks (positive = up, negative = down).
    params: { x, y, amount }
    """
    x = params.get("x")
    y = params.get("y")
    amount = params.get("amount", 3)
    if x is not None and y is not None:
        pyautogui.moveTo(x, y)
    pyautogui.scroll(amount)
    return {"action": "scroll", "x": x, "y": y, "amount": amount}


def _handle_key_combo(params: dict) -> dict:
    """
    Press a keyboard shortcut / hotkey combination.
    params: { keys: ["ctrl", "c"] }
    """
    keys = params["keys"]
    pyautogui.hotkey(*keys)
    return {"action": "key_combo", "keys": keys}


def _handle_move(params: dict) -> dict:
    """
    Move mouse to (x, y) without clicking.
    params: { x, y, duration=0.2 }
    """
    x = params["x"]
    y = params["y"]
    duration = params.get("duration", 0.2)
    pyautogui.moveTo(x, y, duration=duration)
    return {"action": "move", "x": x, "y": y}


# ---------------------------------------------------------------------------
# Dispatch table
# ---------------------------------------------------------------------------

ACTION_HANDLERS: dict[str, Any] = {
    "click": _handle_click,
    "type": _handle_type,
    "scroll": _handle_scroll,
    "key_combo": _handle_key_combo,
    "move": _handle_move,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def execute_action(action: dict) -> dict:
    """
    Dispatch an action dict received from the agent.

    Args:
        action: {
            "type": "click" | "type" | "scroll" | "key_combo" | "move",
            "params": { ... }   # type-specific parameters
        }

    Returns:
        Result dict with the action type and resolved parameters.

    Raises:
        ValueError: If the action type is unknown.
        KeyError: If required params are missing.
    """
    action_type = action.get("type")
    params = action.get("params", {})

    handler = ACTION_HANDLERS.get(action_type)
    if handler is None:
        raise ValueError(
            f"Unknown action type '{action_type}'. "
            f"Supported: {list(ACTION_HANDLERS.keys())}"
        )

    logger.info("Executing action: %s | params: %s", action_type, params)
    result = handler(params)
    logger.info("Action completed: %s", result)
    return result


# ---------------------------------------------------------------------------
# Entry point — manual smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    time.sleep(2)  # give user time to switch windows

    execute_action({"type": "move", "params": {"x": 500, "y": 400}})
    execute_action({"type": "click", "params": {"x": 500, "y": 400}})
    execute_action({"type": "type", "params": {"text": "hello phantom-dev"}})
    execute_action({"type": "key_combo", "params": {"keys": ["ctrl", "a"]}})
    execute_action({"type": "scroll", "params": {"x": 500, "y": 400, "amount": -3}})
