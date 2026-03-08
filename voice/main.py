"""
Phantom-Dev Voice Gateway — FastAPI service.
Bridges browser/client audio to the Gemini Live API over WebSocket.
"""

import asyncio
import logging
import os
from typing import Optional

import google.generativeai as genai
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="Phantom-Dev Voice Gateway", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Voice Gateway
# ---------------------------------------------------------------------------

class VoiceGateway:
    """
    Manages a single Gemini Live API session for one connected WebSocket client.
    Lifecycle: start_session → stream_audio (loop) → end_session
    Status updates are pushed back to the client via send_status_update.
    """

    def __init__(self, websocket: WebSocket, session_id: str):
        self.websocket = websocket
        self.session_id = session_id
        self._gemini_session = None   # handle to the active Gemini Live session
        self._running = False

    async def start_session(self) -> None:
        """
        Initialise the Gemini Live API session.

        TODO:
        - Configure genai with GEMINI_API_KEY
        - Open a streaming session via the Live API
          (genai.LiveSession or equivalent when GA)
        - Set voice/language preferences from client handshake payload
        - Store session handle in self._gemini_session
        """
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise EnvironmentError("GEMINI_API_KEY is not set")

        genai.configure(api_key=api_key)
        self._running = True

        logger.info("[%s] Session started", self.session_id)
        await self.send_status_update("session_started", {"session_id": self.session_id})

    async def stream_audio(self, audio_chunk: bytes) -> None:
        """
        Forward a raw PCM/opus audio chunk from the client to Gemini Live,
        then relay any response audio back to the client.

        Args:
            audio_chunk: Raw audio bytes received from the WebSocket client.

        TODO:
        - Send audio_chunk to self._gemini_session.send_audio(audio_chunk)
        - Await response chunks from Gemini (text transcript + audio)
        - Forward audio response bytes to the client: await self.websocket.send_bytes(...)
        - Forward transcript to the client: await self.send_status_update("transcript", {...})
        - Detect end-of-turn / VAD signals and relay them
        """
        if not self._running or self._gemini_session is None:
            logger.warning("[%s] stream_audio called before session started", self.session_id)
            return

        logger.debug("[%s] Received audio chunk: %d bytes", self.session_id, len(audio_chunk))

        # Placeholder echo — replace with real Gemini Live streaming
        await self.send_status_update("audio_received", {"bytes": len(audio_chunk)})

    async def send_status_update(self, event: str, payload: dict) -> None:
        """
        Push a JSON status/event message to the connected WebSocket client.

        Args:
            event:   Event name (e.g. "session_started", "transcript", "error").
            payload: Arbitrary JSON-serialisable data.
        """
        try:
            await self.websocket.send_json({"event": event, "data": payload})
        except Exception as exc:
            logger.error("[%s] Failed to send status update '%s': %s", self.session_id, event, exc)

    async def end_session(self) -> None:
        """
        Gracefully close the Gemini Live session and release resources.

        TODO:
        - Call self._gemini_session.close() when the SDK supports it
        - Flush any buffered transcript to Firestore (optional)
        """
        self._running = False
        self._gemini_session = None
        logger.info("[%s] Session ended", self.session_id)
        await self.send_status_update("session_ended", {"session_id": self.session_id})


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Liveness probe."""
    return {"status": "ok", "service": "phantom-dev-voice"}


@app.websocket("/stream")
async def stream(websocket: WebSocket):
    """
    Bidirectional audio stream endpoint.

    Client sends:
        - Binary frames: raw PCM audio chunks (16-bit, 16 kHz mono recommended)
        - JSON frames:   control messages, e.g. {"action": "end_session"}

    Server sends:
        - Binary frames: Gemini response audio
        - JSON frames:   status events (session_started, transcript, error, ...)
    """
    await websocket.accept()

    import uuid
    session_id = str(uuid.uuid4())
    gateway = VoiceGateway(websocket, session_id)

    try:
        await gateway.start_session()

        while True:
            # Receive either binary audio or a JSON control message
            message = await websocket.receive()

            if "bytes" in message and message["bytes"]:
                await gateway.stream_audio(message["bytes"])

            elif "text" in message and message["text"]:
                import json
                control = json.loads(message["text"])
                action = control.get("action")

                if action == "end_session":
                    break
                else:
                    await gateway.send_status_update(
                        "error", {"message": f"Unknown action: {action}"}
                    )

    except WebSocketDisconnect:
        logger.info("[%s] Client disconnected", session_id)
    except Exception as exc:
        logger.exception("[%s] Unhandled error: %s", session_id, exc)
        await gateway.send_status_update("error", {"message": str(exc)})
    finally:
        await gateway.end_session()


# ---------------------------------------------------------------------------
# Entry point (local dev)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("VOICE_PORT", 8766))
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)
