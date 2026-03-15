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
    import pyautogui
    
    with mss.mss() as sct:
        target = region if region else sct.monitors[monitor_index]
        raw = sct.grab(target)

        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
        
        # Fix Retina/HiDPI scaling — scale screenshot down to logical coordinates
        logical_w, logical_h = pyautogui.size()
        if img.width > logical_w * 1.2:  # Retina detected (physical > logical)
            img = img.resize((logical_w, logical_h), Image.LANCZOS)
            logger.debug(
                "Retina scaling applied: %dx%d → %dx%d",
                raw.width, raw.height, logical_w, logical_h
            )
        
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
