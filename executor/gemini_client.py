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
        key = api_key or os.getenv("GEMINI_API_KEY")
        if not key:
            raise EnvironmentError(
                "GEMINI_API_KEY is not set. Add it to your .env file or pass it explicitly."
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
            contents=prompt,
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
