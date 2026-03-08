"""
Screen capture module for Phantom-Dev executor.
Uses mss for fast, cross-platform screenshot capture.
"""

import io
import base64
from typing import Optional
from PIL import Image
import mss
import mss.tools


def capture_frame(
    monitor_index: int = 1,
    region: Optional[dict] = None,
    encode: str = "png",
) -> bytes:
    """
    Capture a single frame from the specified monitor (or region).

    Args:
        monitor_index: 1-based monitor index (0 = all monitors combined).
        region: Optional dict with keys top, left, width, height (pixels).
                If provided, overrides monitor_index.
        encode: Output image format — 'png' or 'jpeg'.

    Returns:
        Raw image bytes in the requested format.

    Example:
        frame = capture_frame()
        with open("screenshot.png", "wb") as f:
            f.write(frame)
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
    Convenience wrapper — returns a base64-encoded string suitable for
    embedding in JSON payloads sent to the agent or dashboard.
    """
    raw = capture_frame(monitor_index=monitor_index, encode=encode)
    return base64.b64encode(raw).decode("utf-8")


def get_monitor_info() -> list[dict]:
    """Return metadata for all connected monitors."""
    with mss.mss() as sct:
        return list(sct.monitors)


if __name__ == "__main__":
    info = get_monitor_info()
    print(f"Detected {len(info) - 1} monitor(s): {info[1:]}")
    frame = capture_frame()
    print(f"Captured frame: {len(frame)} bytes")
