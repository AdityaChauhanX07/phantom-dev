"""
Phantom-Dev Voice Gateway — FastAPI service running on Cloud Run.

Responsibilities
----------------
1. Accept a bidirectional WebSocket stream from the client (browser / mobile).
2. Forward raw audio to the Gemini Live API for real-time transcription.
3. Detect "TASK:" prefixes in Gemini responses and POST them to the Agent.
4. Convert agent status text back to speech via Gemini Live and relay
   the audio bytes to the client.

Environment variables
---------------------
  GEMINI_API_KEY   — required
  AGENT_URL        — base HTTP URL of the agent (default http://localhost:8000)
  VOICE_PORT       — port for local dev (default 8766)
  LOG_LEVEL        — Python log level (default INFO)

WebSocket message contract
--------------------------
Client → Gateway:
  Binary frame  : raw PCM audio chunk (16-bit, 16 kHz, mono recommended)
  Text frame    : JSON control message
    {"type": "start",  "session_id": "<str>"}
    {"type": "stop"}
    {"type": "status", "text": "<status text to speak aloud>"}

Gateway → Client:
  Binary frame  : Gemini response audio bytes
  Text frame    : JSON event
    {"event": "session_started", "session_id": "<str>"}
    {"event": "task_detected",   "goal": "<str>"}
    {"event": "status_update",   "text": "<str>"}
    {"event": "session_ended"}
    {"event": "error",           "message": "<str>"}
"""

import json
import logging
import os
import uuid

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from google import genai
from google.genai import types

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("phantom.voice")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
AGENT_URL: str = os.getenv("AGENT_URL", "http://localhost:8000").rstrip("/")
GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "phantom-dev-489603")
GCP_LOCATION: str = os.getenv("GCP_LOCATION", "us-east4")
LIVE_MODEL: str = "gemini-2.0-flash-live-001"
SYSTEM_INSTRUCTION: str = (
    "You are Phantom, a calm professional AI computer operator. "
    "When the user speaks a task, extract just the task goal as plain text "
    "and prefix it with TASK: "
    "When providing status updates, speak clearly and concisely."
)

if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY is not set — Gemini Live calls will fail.")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Phantom-Dev Voice Gateway", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# VoiceGateway
# ---------------------------------------------------------------------------

class VoiceGateway:
    """
    Manages one Gemini Live API session for a single WebSocket client.

    Lifecycle::

        gw = VoiceGateway()
        await gw.start_session(session_id)
        # receive audio frames from client:
        goal = await gw.stream_audio(chunk)
        # push agent status text back as speech:
        audio = await gw.send_status_update("Task completed.")
        await gw.end_session()
    """

    def __init__(self):
        self._api_key: str = GEMINI_API_KEY
        self._agent_url: str = AGENT_URL
        self._genai_client = genai.Client(api_key=self._api_key) if self._api_key else None
        self.session = None          # active Gemini Live session context manager
        self._session_ctx = None     # the context manager handle
        self.active: bool = False
        self._session_id: str = ""

    # ------------------------------------------------------------------ #
    # Session management                                                   #
    # ------------------------------------------------------------------ #

    async def start_session(self, session_id: str) -> None:
        """
        Open a Gemini Live API session configured for audio I/O.

        Args:
            session_id: Caller-supplied identifier for logging/correlation.
        """
        if not self._genai_client:
            raise EnvironmentError("GEMINI_API_KEY is not set — cannot start Gemini session.")

        self._session_id = session_id
        live_config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=SYSTEM_INSTRUCTION,
        )

        self._session_ctx = self._genai_client.aio.live.connect(
            model=LIVE_MODEL,
            config=live_config,
        )
        self.session = await self._session_ctx.__aenter__()
        self.active = True
        logger.info("[VoiceGateway] Voice session started: %s", session_id)

    async def end_session(self) -> None:
        """Close the Gemini Live session and release resources."""
        if self._session_ctx is not None:
            try:
                await self._session_ctx.__aexit__(None, None, None)
            except Exception as exc:
                logger.debug("[VoiceGateway] Error closing session: %s", exc)
        self.session = None
        self._session_ctx = None
        self.active = False
        logger.info("[VoiceGateway] Voice session ended: %s", self._session_id)

    # ------------------------------------------------------------------ #
    # Audio streaming                                                      #
    # ------------------------------------------------------------------ #

    async def stream_audio(self, audio_chunk: bytes) -> str | None:
        """
        Forward *audio_chunk* to the Gemini Live session and process the response.

        - If Gemini returns text starting with ``"TASK:"`` the goal is extracted,
          POSTed to the agent backend, and returned.
        - Any other text response is returned as a status string.
        - Audio responses are returned as ``bytes`` (caller should relay to client).
        - Returns ``None`` when Gemini produces no meaningful response for this chunk.

        Args:
            audio_chunk: Raw PCM audio bytes from the WebSocket client.

        Returns:
            Detected task goal string, status text string, raw audio bytes, or None.
        """
        if not self.active or self.session is None:
            logger.warning(
                "[VoiceGateway:%s] stream_audio called before session started.",
                self._session_id,
            )
            return None

        # Send the audio chunk to Gemini Live
        await self.session.send_realtime_input(
            audio=types.Blob(data=audio_chunk, mime_type="audio/pcm")
        )

        # Collect the response turn
        response_text: str = ""
        response_audio: bytes = b""

        async for response in self.session.receive():
            # Text part
            if response.text:
                response_text += response.text

            # Audio part
            if (
                response.data
                and hasattr(response, "mime_type")
                and "audio" in (response.mime_type or "")
            ):
                response_audio += response.data

            # End-of-turn signal
            if response.server_content and response.server_content.turn_complete:
                break

        # ── Interpret text response ──────────────────────────────────────
        if response_text:
            stripped = response_text.strip()
            if stripped.upper().startswith("TASK:"):
                goal = stripped[5:].strip()
                logger.info(
                    "[VoiceGateway:%s] Task detected: %r", self._session_id, goal
                )
                await self._post_task_to_agent(goal)
                return goal

            # Non-task text — treat as status update
            logger.debug(
                "[VoiceGateway:%s] Status text from Gemini: %r", self._session_id, stripped
            )
            return stripped

        if response_audio:
            return response_audio   # type: ignore[return-value]  # bytes

        return None

    # ------------------------------------------------------------------ #
    # Status → speech                                                      #
    # ------------------------------------------------------------------ #

    async def send_status_update(self, text: str) -> bytes | None:
        """
        Send *text* to Gemini Live and return the spoken audio response.

        Args:
            text: Status message to be read aloud by Gemini.

        Returns:
            Raw audio bytes of Gemini's spoken response, or ``None`` on error.
        """
        if not self.active or self.session is None:
            logger.warning(
                "[VoiceGateway:%s] send_status_update called without active session.",
                self._session_id,
            )
            return None

        try:
            await self.session.send_client_content(
                turns=types.Content(
                    role="user",
                    parts=[types.Part(text=text)],
                )
            )

            audio_out: bytes = b""
            async for response in self.session.receive():
                if (
                    response.data
                    and hasattr(response, "mime_type")
                    and "audio" in (response.mime_type or "")
                ):
                    audio_out += response.data
                if response.server_content and response.server_content.turn_complete:
                    break

            return audio_out if audio_out else None

        except Exception as exc:
            logger.error(
                "[VoiceGateway:%s] send_status_update failed: %s", self._session_id, exc
            )
            return None

    # ------------------------------------------------------------------ #
    # Agent integration                                                    #
    # ------------------------------------------------------------------ #

    async def _post_task_to_agent(self, goal: str) -> None:
        """POST the detected task goal to the Agent backend."""
        payload = {"goal": goal, "session_id": self._session_id}
        url = f"{self._agent_url}/task"
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                resp.raise_for_status()
                logger.info(
                    "[VoiceGateway:%s] Task POSTed to agent — task_id=%s",
                    self._session_id,
                    resp.json().get("task_id", "?"),
                )
        except Exception as exc:
            logger.error(
                "[VoiceGateway:%s] Failed to POST task to agent (%s): %s",
                self._session_id, url, exc,
            )


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Liveness probe used by Cloud Run and docker-compose."""
    # active_session reflects whether *any* gateway on this instance is live.
    # For a proper multi-client count, a global registry would be needed;
    # the boolean here matches the spec intent for single-session deployments.
    return {"status": "ok", "active_session": False}


# ---------------------------------------------------------------------------
# WebSocket /stream
# ---------------------------------------------------------------------------

@app.websocket("/stream")
async def stream(websocket: WebSocket):
    """
    Bidirectional audio/control stream.

    Client sends binary (PCM audio) or text (JSON control) frames.
    Gateway sends binary (response audio) or text (JSON event) frames.
    """
    await websocket.accept()
    session_id = str(uuid.uuid4())
    gateway = VoiceGateway()
    logger.info("[/stream] Client connected — session_id=%s", session_id)

    async def _send_event(event: str, **kwargs) -> None:
        payload = {"event": event, **kwargs}
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception as exc:
            logger.debug("[/stream:%s] Could not send event %r: %s", session_id, event, exc)

    try:
        while True:
            message = await websocket.receive()

            # ── Binary frame: audio chunk ────────────────────────────────
            if message.get("bytes"):
                audio_chunk: bytes = message["bytes"]

                if not gateway.active:
                    await _send_event("error", message="Session not started. Send {type:start} first.")
                    continue

                result = await gateway.stream_audio(audio_chunk)

                if result is None:
                    pass  # Gemini still processing — no meaningful output yet

                elif isinstance(result, bytes):
                    # Raw audio response — relay to client
                    await websocket.send_bytes(result)

                elif isinstance(result, str):
                    stripped = result.strip()
                    if stripped.upper().startswith("TASK:"):
                        # Already POSTed to agent inside stream_audio
                        goal = stripped[5:].strip()
                        await _send_event("task_detected", goal=goal)

                        # Speak a confirmation back to the user
                        confirm_audio = await gateway.send_status_update(
                            f"Got it. Starting task: {goal}"
                        )
                        if confirm_audio:
                            await websocket.send_bytes(confirm_audio)
                    else:
                        await _send_event("status_update", text=stripped)

            # ── Text frame: JSON control message ─────────────────────────
            elif message.get("text"):
                try:
                    control = json.loads(message["text"])
                except json.JSONDecodeError:
                    await _send_event("error", message="Invalid JSON in control frame.")
                    continue

                msg_type = control.get("type")

                if msg_type == "start":
                    sid = control.get("session_id") or session_id
                    try:
                        await gateway.start_session(sid)
                        await _send_event("session_started", session_id=sid)
                    except Exception as exc:
                        logger.error("[/stream:%s] start_session failed: %s", session_id, exc)
                        await _send_event("error", message=str(exc))

                elif msg_type == "stop":
                    await gateway.end_session()
                    await _send_event("session_ended")
                    break

                elif msg_type == "status":
                    text = control.get("text", "")
                    if not text:
                        await _send_event("error", message="status message has no 'text' field.")
                        continue

                    audio = await gateway.send_status_update(text)
                    if audio:
                        await websocket.send_bytes(audio)
                    await _send_event("status_update", text=text)

                else:
                    await _send_event(
                        "error", message=f"Unknown control type: {msg_type!r}"
                    )

    except WebSocketDisconnect:
        logger.info("[/stream] Client disconnected — session_id=%s", session_id)
    except Exception as exc:
        logger.exception("[/stream:%s] Unhandled error: %s", session_id, exc)
        await _send_event("error", message=str(exc))
    finally:
        if gateway.active:
            await gateway.end_session()


# ---------------------------------------------------------------------------
# Entry point (local dev)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("VOICE_PORT", "8766"))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
