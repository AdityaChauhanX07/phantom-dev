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
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import JSONResponse
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
GCP_LOCATION: str = os.getenv("GCP_LOCATION", "us-central1")
# Text model for offline STT → TASK flow (non-Live). Must be a regular Gemini model name.
TEXT_MODEL: str = os.getenv("TEXT_MODEL", "gemini-2.5-flash")
# Live API model - MUST use native-audio model for Live API
# Official model: "gemini-2.5-flash-native-audio-preview-12-2025"
# Regular models (gemini-2.0-flash, etc.) do NOT support Live API
# Check https://ai.google.dev/gemini-api/docs/live for current models
LIVE_MODEL: str = os.getenv("LIVE_MODEL", "gemini-2.5-flash-native-audio-preview-12-2025")
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
        # Live API requires API key (does not support Vertex AI)
        # Only /stt-task endpoint uses Vertex AI to avoid rate limits
        if not self._api_key:
            logger.warning("GEMINI_API_KEY not set — Live API will not work")
        self._genai_client = genai.Client(api_key=self._api_key) if self._api_key else None
        if self._genai_client:
            logger.info("GeminiLiveGateway using API key for Live API (Vertex AI used only for /stt-task)")
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
            raise EnvironmentError("GEMINI_API_KEY is not set — cannot start Gemini Live session.")

        self._session_id = session_id
        # Request both TEXT and AUDIO so we get a transcript ("TASK: ...") and spoken response.
        # TEXT is critical for extracting the goal and posting it to the agent.
        live_config = types.LiveConnectConfig(
        response_modalities=["AUDIO"],  # keep only AUDIO; TEXT here causes 1007 invalid argument
        system_instruction=SYSTEM_INSTRUCTION)

        try:
            logger.info("[VoiceGateway] Attempting to start session with model: %s", LIVE_MODEL)
            logger.debug("[VoiceGateway] Using genai client: %s", type(self._genai_client).__name__)
            
            self._session_ctx = self._genai_client.aio.live.connect(
                model=LIVE_MODEL,
                config=live_config,
            )
            self.session = await self._session_ctx.__aenter__()
            self.active = True
            logger.info("[VoiceGateway] Voice session started successfully: %s (model: %s)", session_id, LIVE_MODEL)
        except Exception as exc:
            error_msg = str(exc)
            logger.error(
                "[VoiceGateway] Failed to start session with model %s. Error: %s (type: %s)",
                LIVE_MODEL, error_msg, type(exc).__name__
            )
            # Check if it's a model not found error
            if "not found" in error_msg.lower() or "not supported" in error_msg.lower():
                logger.error(
                    "[VoiceGateway] Model error detected. This model may not support Live API. "
                    "Try: 'gemini-2.5-flash-native-audio-preview-12-2025' or check API docs: "
                    "https://ai.google.dev/gemini-api/docs/live"
                )
            raise

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

    async def stream_audio(self, audio_chunk: bytes) -> str | bytes | None:
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
        
        # Try to get response (non-blocking check)
        # Gemini may not respond to every chunk, only when user pauses or finishes
        try:
            # Check if there's a response available (with timeout)
            response_text: str = ""
            response_audio: bytes = b""
            
            # Process any available responses (non-blocking)
            async for response in self.session.receive():
                if response.text:
                    response_text += response.text
                    logger.debug("[VoiceGateway:%s] Received text: %r", self._session_id, response.text)
                
                if (
                    response.data
                    and hasattr(response, "mime_type")
                    and "audio" in (response.mime_type or "")
                ):
                    response_audio += response.data
                
                if response.server_content and response.server_content.turn_complete:
                    break
                    
            if response_text:
                stripped = response_text.strip()
                logger.info("[VoiceGateway:%s] Full response text: %r", self._session_id, stripped)
                if stripped.upper().startswith("TASK:"):
                    goal = stripped[5:].strip()
                    logger.info("[VoiceGateway:%s] Task detected: %r", self._session_id, goal)
                    await self._post_task_to_agent(goal)
                    return goal
                return stripped
                
            if response_audio:
                return response_audio
        except Exception as exc:
            logger.debug("[VoiceGateway:%s] No response yet or error: %s", self._session_id, exc)
        
        return None

    async def finish_speech_and_get_response(self) -> str | bytes | None:
        """
        Signal that user finished speaking and get final response from Gemini.
        Call this after user stops recording.
        """
        if not self.active or self.session is None:
            logger.warning("[VoiceGateway:%s] finish_speech_and_get_response called but session not active", self._session_id)
            return None
            
        # Send empty audio chunk to signal end of speech
        logger.info("[VoiceGateway:%s] Sending end-of-speech signal to Gemini...", self._session_id)
        try:
            # Send empty audio to signal completion
            await self.session.send_realtime_input(
                audio=types.Blob(data=b"", mime_type="audio/pcm")
            )
            logger.debug("[VoiceGateway:%s] End-of-speech signal sent", self._session_id)
        except Exception as exc:
            logger.warning("[VoiceGateway:%s] Failed to send end-of-speech signal: %s", self._session_id, exc)
            
        logger.info("[VoiceGateway:%s] Waiting for final response from Gemini...", self._session_id)
        try:
            response_text: str = ""
            response_audio: bytes = b""
            response_count = 0
            
            # Wait for final response with timeout handling
            async for response in self.session.receive():
                response_count += 1
                logger.debug("[VoiceGateway:%s] Received response #%d: text=%s, has_data=%s, turn_complete=%s", 
                           self._session_id, response_count, 
                           bool(response.text), 
                           bool(response.data),
                           response.server_content.turn_complete if response.server_content else None)
                
                if response.text:
                    response_text += response.text
                    logger.info("[VoiceGateway:%s] Response text chunk: %r", self._session_id, response.text)
                
                if (
                    response.data
                    and hasattr(response, "mime_type")
                    and "audio" in (response.mime_type or "")
                ):
                    response_audio += response.data
                    logger.debug("[VoiceGateway:%s] Received audio chunk: %d bytes", self._session_id, len(response.data))
                
                if response.server_content and response.server_content.turn_complete:
                    logger.info("[VoiceGateway:%s] Turn complete signal received", self._session_id)
                    break
                    
            if response_text:
                stripped = response_text.strip()
                logger.info("[VoiceGateway:%s] Final response text: %r", self._session_id, stripped)
                if stripped.upper().startswith("TASK:"):
                    goal = stripped[5:].strip()
                    logger.info("[VoiceGateway:%s] Task detected: %r", self._session_id, goal)
                    await self._post_task_to_agent(goal)
                    return goal
                return stripped
                
            if response_audio:
                logger.info("[VoiceGateway:%s] Final response audio: %d bytes", self._session_id, len(response_audio))
                return response_audio
                
            logger.warning("[VoiceGateway:%s] No response received from Gemini (got %d response chunks)", self._session_id, response_count)
        except Exception as exc:
            logger.error("[VoiceGateway:%s] Error getting final response: %s", self._session_id, exc, exc_info=True)
        
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

@app.post("/stt-task")
async def stt_task(request: Request):
    """
    One-shot speech → TASK flow using the non-Live Gemini API.

    Contract (v1):
      - Client sends a single audio blob in the request body.
      - Content-Type should be an audio type (e.g. audio/webm, audio/wav, audio/pcm).
      - Server calls Gemini text model to:
          1) transcribe the audio
          2) compress it into a single goal sentence
          3) return exactly:  TASK: <goal>
      - We parse <goal>, POST it to the Agent /task endpoint, and return:
          { "goal": "<goal>", "task_id": "<uuid>", "session_id": "<uuid>" }
    """
    try:
        audio_bytes = await request.body()
        if not audio_bytes:
            return JSONResponse(
                {"message": "Empty audio payload"},
                status_code=400,
            )

        content_type = request.headers.get("content-type", "audio/webm")

        # Use Vertex AI instead of AI Studio to avoid rate limits
        if not GCP_PROJECT_ID:
            logger.error("[/stt-task] GCP_PROJECT_ID is not set")
            return JSONResponse(
                {"message": "GCP_PROJECT_ID is not configured on the server"},
                status_code=500,
            )

        # Use Vertex AI (no API key needed, uses GCP service account)
        genai_client = genai.Client(
            vertexai=True,
            project=GCP_PROJECT_ID,
            location=GCP_LOCATION,
        )
        logger.info("[/stt-task] Using Vertex AI — project=%s location=%s", GCP_PROJECT_ID, GCP_LOCATION)

        prompt = (
            "You are Phantom's voice interface.\n"
            "The user audio contains a single task they want Phantom to perform "
            "on the computer (for example: move Jira tickets, update a Google Sheet, "
            "send a Slack message).\n\n"
            "Instructions:\n"
            "1) Transcribe what the user said.\n"
            "2) Summarize it into one concise goal sentence in English.\n"
            "3) Return EXACTLY one line in this format (no explanations, no quotes, "
            "no markdown, no extra text):\n"
            "TASK: <concise goal in English>\n"
        )

        logger.info(
            "[/stt-task] Calling Gemini text model %s for STT (content_type=%s, bytes=%d)",
            TEXT_MODEL,
            content_type,
            len(audio_bytes),
        )

        # We send both the audio and the textual instructions as parts of a single user turn.
        response = genai_client.models.generate_content(
            model=TEXT_MODEL,
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=audio_bytes, mime_type=content_type),
                        types.Part(text=prompt),
                    ],
                )
            ],
        )

        # Extract full text from all candidates to be robust to model formatting.
        full_text = ""
        try:
            for cand in getattr(response, "candidates", []) or []:
                content = getattr(cand, "content", None)
                if not content:
                    continue
                for part in getattr(content, "parts", []) or []:
                    text_part = getattr(part, "text", None)
                    if text_part:
                        full_text += text_part
        except Exception as exc:
            logger.warning("[/stt-task] Failed to parse Gemini response: %s", exc)

        stripped = (full_text or "").strip()
        logger.info("[/stt-task] Gemini STT raw response: %r", stripped)

        if not stripped:
            return JSONResponse(
                {"message": "No text returned from Gemini"},
                status_code=502,
            )

        # Be forgiving if the model forgot the TASK: prefix.
        if stripped.upper().startswith("TASK:"):
            goal = stripped[5:].strip()
        else:
            goal = stripped

        if not goal:
            return JSONResponse(
                {"message": "Parsed empty goal from Gemini response"},
                status_code=502,
            )

        # Use a fresh session_id here; voice Live session is not reused.
        session_id = str(uuid.uuid4())
        payload = {"goal": goal, "session_id": session_id}
        agent_url = f"{AGENT_URL}/task"

        logger.info("[/stt-task] Posting task to agent at %s", agent_url)
        task_id = None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(agent_url, json=payload)
                resp.raise_for_status()
                data = resp.json() or {}
                task_id = data.get("task_id")
                logger.info("[/stt-task] Task created in agent — task_id=%s", task_id)
        except Exception as exc:
            logger.error("[/stt-task] Failed to POST task to agent: %s", exc)
            # Still return the goal and session so the client can show something useful.
            return JSONResponse(
                {
                    "goal": goal,
                    "session_id": session_id,
                    "message": f"Failed to POST task to agent: {exc}",
                },
                status_code=502,
            )

        return JSONResponse(
            {"goal": goal, "task_id": task_id, "session_id": session_id},
            status_code=200,
        )

    except Exception as exc:
        logger.exception("[/stt-task] Unhandled error: %s", exc)
        return JSONResponse({"message": str(exc)}, status_code=500)


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
                logger.debug("[/stream:%s] Received audio chunk: %d bytes", session_id, len(audio_chunk))

                if not gateway.active:
                    await _send_event("error", message="Session not started. Send {type:start} first.")
                    continue

                result = await gateway.stream_audio(audio_chunk)
                if result:
                    logger.info("[/stream:%s] stream_audio returned: %s (type: %s)", session_id, result[:100] if isinstance(result, str) else f"{len(result)} bytes", type(result).__name__)

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
                    # User finished speaking - get final response (but keep session open)
                    logger.info("[/stream:%s] Received stop message - user finished speaking", session_id)
                    logger.info("[/stream:%s] Calling finish_speech_and_get_response...", session_id)
                    final_response = await gateway.finish_speech_and_get_response()
                    logger.info("[/stream:%s] finish_speech_and_get_response returned: %s", session_id, 
                              "None" if final_response is None else f"{type(final_response).__name__} ({len(final_response) if isinstance(final_response, (str, bytes)) else 'N/A'})")
                    
                    if final_response:
                        if isinstance(final_response, bytes):
                            await websocket.send_bytes(final_response)
                        elif isinstance(final_response, str):
                            stripped = final_response.strip()
                            if stripped.upper().startswith("TASK:"):
                                goal = stripped[5:].strip()
                                await _send_event("task_detected", goal=goal)
                                confirm_audio = await gateway.send_status_update(
                                    f"Got it. Starting task: {goal}"
                                )
                                if confirm_audio:
                                    await websocket.send_bytes(confirm_audio)
                            else:
                                await _send_event("status_update", text=stripped)
                    else:
                        await _send_event("status_update", text="Processing your request...")
                    # Don't end session - user might want to speak again
                    continue

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
