"""
Phantom-Dev Agent — FastAPI backend running on Cloud Run.
Receives task instructions, delegates to Gemini, streams results back.
"""

import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

app = FastAPI(title="Phantom-Dev Agent", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class TaskRequest(BaseModel):
    task: str
    context: dict = {}


class TaskResponse(BaseModel):
    status: str
    task_id: str
    message: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/health")
async def health_check():
    """Liveness probe — used by Cloud Run and docker-compose."""
    return {"status": "ok", "service": "phantom-dev-agent"}


@app.post("/run-task", response_model=TaskResponse)
async def run_task(request: TaskRequest):
    """
    Accept a natural-language task, plan steps with Gemini, and push
    action events to the executor via WebSocket.

    TODO:
    - Initialise Gemini client with GEMINI_API_KEY
    - Break task into discrete actions (click / type / scroll / key_combo)
    - Persist run state to Firestore
    - Stream action events to connected executor WebSocket clients
    """
    import uuid
    task_id = str(uuid.uuid4())

    # Placeholder — replace with real Gemini + executor logic
    return TaskResponse(
        status="accepted",
        task_id=task_id,
        message=f"Task '{request.task}' queued. Executor will begin shortly.",
    )


@app.websocket("/ws/events")
async def websocket_events(websocket: WebSocket):
    """
    Bidirectional channel between the agent and the dashboard.
    The agent pushes action events; the dashboard renders them live.
    """
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            # TODO: route incoming messages (e.g. task cancellation)
            await websocket.send_json({"echo": data, "status": "received"})
    except WebSocketDisconnect:
        pass


# ---------------------------------------------------------------------------
# Entry point (local dev)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
