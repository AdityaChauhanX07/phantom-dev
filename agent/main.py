"""
Phantom-Dev Agent — FastAPI cloud orchestrator running on Cloud Run.

Responsibilities
----------------
1. Receive task goals (from Voice Gateway or direct HTTP).
2. Persist task state in Firestore.
3. Push tasks to connected local executors via WebSocket (/ws/executor).
4. Forward progress updates to dashboard clients (/ws/dashboard).
5. Store screenshots sent by executors in Cloud Storage.

Environment variables (all loaded from .env / Cloud Run env):
  GCP_PROJECT_ID        — Google Cloud project (required for Firestore)
  GCS_BUCKET            — Cloud Storage bucket for screenshots (optional)
  LOG_LEVEL             — Python logging level (default INFO)
"""

import json
import logging
import os
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from google.cloud import firestore
from pydantic import BaseModel

load_dotenv()

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("phantom.agent")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

GCP_PROJECT_ID: str = os.getenv("GCP_PROJECT_ID", "")
GCS_BUCKET: str = os.getenv("GCS_BUCKET", "")

if not GCP_PROJECT_ID:
    logger.warning("GCP_PROJECT_ID is not set — Firestore calls will fail.")

# ---------------------------------------------------------------------------
# Firestore (async client)
# ---------------------------------------------------------------------------

db = firestore.AsyncClient(project=GCP_PROJECT_ID or None)
TASKS_COLLECTION = "tasks"

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Phantom-Dev Agent", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# In-memory connection registries
# ---------------------------------------------------------------------------

# executor_id (str) → WebSocket
_executors: dict[str, WebSocket] = {}

# client_id (str) → WebSocket
_dashboards: dict[str, WebSocket] = {}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def broadcast_to_dashboards(message: dict) -> None:
    """
    Send *message* as JSON to every connected dashboard client.

    Stale sockets are silently removed from the registry.
    """
    dead: list[str] = []
    payload = json.dumps(message)
    for client_id, ws in _dashboards.items():
        try:
            await ws.send_text(payload)
        except Exception as exc:
            logger.debug("[broadcast] Dashboard %s unreachable: %s", client_id, exc)
            dead.append(client_id)
    for client_id in dead:
        _dashboards.pop(client_id, None)


async def _create_task_doc(task_id: str, goal: str, session_id: str) -> None:
    """Write the initial task document to Firestore."""
    doc = {
        "task_id": task_id,
        "goal": goal,
        "session_id": session_id,
        "status": "queued",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "result": None,
    }
    await db.collection(TASKS_COLLECTION).document(task_id).set(doc)
    logger.info("[Firestore] Task created: %s", task_id)


async def _update_task_doc(task_id: str, updates: dict) -> None:
    """Merge *updates* into an existing Firestore task document."""
    updates["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db.collection(TASKS_COLLECTION).document(task_id).update(updates)
    logger.info("[Firestore] Task updated: %s  keys=%s", task_id, list(updates.keys()))


async def _store_screenshot(task_id: str, screenshot_b64: str) -> str:
    """
    Upload a base64-encoded screenshot to Cloud Storage.

    Returns the GCS URI, or an empty string if GCS_BUCKET is not configured.
    """
    if not GCS_BUCKET:
        logger.debug("[GCS] GCS_BUCKET not set — screenshot not stored.")
        return ""

    try:
        import base64

        from google.cloud import storage

        blob_name = f"screenshots/{task_id}/{uuid.uuid4().hex}.jpg"
        client = storage.Client(project=GCP_PROJECT_ID or None)
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(blob_name)
        blob.upload_from_string(
            base64.b64decode(screenshot_b64), content_type="image/jpeg"
        )
        uri = f"gs://{GCS_BUCKET}/{blob_name}"
        logger.info("[GCS] Screenshot stored: %s", uri)
        return uri
    except Exception as exc:
        logger.warning("[GCS] Screenshot upload failed: %s", exc)
        return ""


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class TaskRequest(BaseModel):
    goal: str
    session_id: str = ""


class TaskResponse(BaseModel):
    task_id: str
    status: str


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    """Liveness probe used by Cloud Run and docker-compose."""
    return {
        "status": "ok",
        "connected_executors": len(_executors),
    }


@app.post("/task", response_model=TaskResponse)
async def create_task(request: TaskRequest):
    """
    Create a new task, persist it to Firestore, and broadcast to executors.

    Body:  {"goal": "string", "session_id": "string"}
    Returns: {"task_id": "uuid", "status": "queued"}
    """
    task_id = str(uuid.uuid4())
    goal = request.goal.strip()
    session_id = request.session_id

    if not goal:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="goal must not be empty.")

    logger.info("[POST /task] New task %s: %r", task_id, goal)

    # Persist to Firestore
    await _create_task_doc(task_id, goal, session_id)

    # Push to all connected executors
    task_message = json.dumps({
        "type": "task",
        "task_id": task_id,
        "goal": goal,
        "session_id": session_id,
    })
    dead_executors: list[str] = []
    for exec_id, ws in _executors.items():
        try:
            await ws.send_text(task_message)
            logger.info("[POST /task] Sent to executor %s", exec_id)
        except Exception as exc:
            logger.warning("[POST /task] Executor %s unreachable: %s", exec_id, exc)
            dead_executors.append(exec_id)
    for exec_id in dead_executors:
        _executors.pop(exec_id, None)

    if not _executors and not dead_executors:
        logger.warning("[POST /task] No executors connected — task queued but not dispatched.")

    # Notify dashboards
    await broadcast_to_dashboards({
        "type": "task_queued",
        "task_id": task_id,
        "goal": goal,
        "session_id": session_id,
    })

    return TaskResponse(task_id=task_id, status="queued")


@app.get("/task/{task_id}")
async def get_task(task_id: str):
    """Return the current state of a task from Firestore."""
    doc_ref = db.collection(TASKS_COLLECTION).document(task_id)
    doc = await doc_ref.get()
    if not doc.exists:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Task {task_id!r} not found.")
    return doc.to_dict()


# ---------------------------------------------------------------------------
# WebSocket — executor
# ---------------------------------------------------------------------------

@app.websocket("/ws/executor")
async def ws_executor(websocket: WebSocket):
    """
    Persistent channel between the cloud agent and a local executor process.

    Expected inbound message shapes:
      {"type": "screenshot", "task_id": str, "data": <b64>}
      {"type": "task_result", "task_id": str, "data": <task_state dict>}
    """
    await websocket.accept()
    exec_id = str(uuid.uuid4())
    _executors[exec_id] = websocket
    logger.info("[WS /ws/executor] Executor connected: %s  (total=%d)", exec_id, len(_executors))

    await broadcast_to_dashboards({
        "type": "executor_connected",
        "executor_id": exec_id,
        "connected_executors": len(_executors),
    })

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("[WS executor:%s] Non-JSON message received.", exec_id)
                continue

            msg_type = message.get("type")
            task_id = message.get("task_id", "")

            if msg_type == "screenshot":
                screenshot_b64 = message.get("data", "")
                logger.debug(
                    "[WS executor:%s] Screenshot received for task %s (%d chars).",
                    exec_id, task_id, len(screenshot_b64),
                )

                # Store in Cloud Storage (fire-and-forget; non-blocking)
                gcs_uri = await _store_screenshot(task_id, screenshot_b64)

                # Forward a thumbnail notification (not the raw b64) to dashboards
                await broadcast_to_dashboards({
                    "type": "screenshot",
                    "task_id": task_id,
                    "executor_id": exec_id,
                    "gcs_uri": gcs_uri,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                })

            elif msg_type == "task_result":
                task_state: dict = message.get("data", {})
                status = task_state.get("status", "unknown")
                logger.info(
                    "[WS executor:%s] Task result for %s — status=%s",
                    exec_id, task_id, status,
                )

                # Persist final state to Firestore
                if task_id:
                    try:
                        await _update_task_doc(task_id, {
                            "status": status,
                            "result": task_state,
                        })
                    except Exception as exc:
                        logger.error(
                            "[WS executor:%s] Firestore update failed: %s", exec_id, exc
                        )

                # Broadcast full result to all dashboards
                await broadcast_to_dashboards({
                    "type": "task_result",
                    "task_id": task_id,
                    "executor_id": exec_id,
                    "status": status,
                    "data": task_state,
                })

            else:
                logger.debug(
                    "[WS executor:%s] Unknown message type %r — ignoring.", exec_id, msg_type
                )

    except WebSocketDisconnect:
        logger.info("[WS /ws/executor] Executor disconnected: %s", exec_id)
    except Exception as exc:
        logger.warning("[WS /ws/executor] Executor %s error: %s", exec_id, exc)
    finally:
        _executors.pop(exec_id, None)
        await broadcast_to_dashboards({
            "type": "executor_disconnected",
            "executor_id": exec_id,
            "connected_executors": len(_executors),
        })


# ---------------------------------------------------------------------------
# WebSocket — dashboard
# ---------------------------------------------------------------------------

@app.websocket("/ws/dashboard")
async def ws_dashboard(websocket: WebSocket):
    """
    Persistent channel between the cloud agent and the Next.js dashboard.

    The dashboard receives broadcast updates about task progress.
    It may also send control messages (e.g. task cancellation) in future.
    """
    await websocket.accept()
    client_id = str(uuid.uuid4())
    _dashboards[client_id] = websocket
    logger.info(
        "[WS /ws/dashboard] Dashboard connected: %s  (total=%d)", client_id, len(_dashboards)
    )

    # Send current executor count as welcome payload
    try:
        await websocket.send_text(json.dumps({
            "type": "connected",
            "client_id": client_id,
            "connected_executors": len(_executors),
        }))
    except Exception:
        pass

    try:
        while True:
            # Keep the socket alive; dashboard messages are currently informational
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
                logger.debug(
                    "[WS dashboard:%s] Message received: type=%r",
                    client_id, message.get("type"),
                )
            except json.JSONDecodeError:
                logger.debug("[WS dashboard:%s] Non-JSON message.", client_id)

    except WebSocketDisconnect:
        logger.info("[WS /ws/dashboard] Dashboard disconnected: %s", client_id)
    except Exception as exc:
        logger.warning("[WS /ws/dashboard] Client %s error: %s", client_id, exc)
    finally:
        _dashboards.pop(client_id, None)


# ---------------------------------------------------------------------------
# Entry point (local dev)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main:app",
        host=os.getenv("AGENT_HOST", "0.0.0.0"),
        port=int(os.getenv("AGENT_PORT", "8000")),
        reload=True,
    )
