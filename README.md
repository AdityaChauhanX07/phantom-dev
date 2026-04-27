# phantom-dev

Autonomous AI computer operator. Speak a goal, watch it execute. Vision-first agent that operates any software without APIs or DOM access.

Built for the [Gemini Live Agent Challenge](https://geminiliveagentchallenge.devpost.com/).

---

## What it does

You speak a task out loud -- something like "pull all Q1 bugs from Jira, add them to the Google Sheet, and post a summary in Slack" -- and Phantom figures out how to do it on your actual desktop, step by step, using screenshots and Gemini to decide what to click, type, or scroll next.

No browser extensions. No injected scripts. Just screen capture and pyautogui, the same way a human would do it.

The core idea is a reactive loop: take a screenshot, ask Gemini what the single best next action is, do it, take another screenshot, repeat. This turned out to be way more reliable than trying to plan 50 steps upfront, because every decision is based on what's actually on screen right now, not what we assumed would be there.

---

## Architecture

```
You (voice)
    |
    v
Voice Gateway  (Cloud Run, port 8766)
    |  Gemini Live API -- transcribes audio in real time
    |  detects "TASK:" prefix, POSTs goal to Agent
    |
    v
Agent  (Cloud Run, port 8000)
    |  FastAPI + Firestore + Cloud Storage
    |  dispatches task to Executor over WebSocket
    |  streams progress to Dashboard
    |
    +-------------------------+
    |                         |
    v                         v
Executor  (local)         Dashboard  (Next.js, browser)
    reactive loop:            real-time task feed,
    screenshot -> Gemini      screenshots, status updates
    -> action -> repeat
```

### Services

| Path | Where it runs | What it does |
|---|---|---|
| `agent/` | Cloud Run | task orchestration, Firestore state, WebSocket hub |
| `executor/` | your machine | screen capture, Gemini vision, pyautogui actions |
| `voice/` | Cloud Run | Gemini Live API bridge, speech to task detection |
| `dashboard/` | browser | Next.js 14 frontend, live updates |
| `infra/` | GCP | Terraform for Cloud Run, Firestore, GCS |
| `docs/` | -- | setup guides, deployment notes, troubleshooting |
| `scripts/` | -- | deploy and environment shell scripts |

---

## How the executor loop works

The executor is the interesting part. It runs up to 60 cycles per task:

```
1. capture screenshot
2. send to Gemini with the goal and action history
3. Gemini returns the next action as JSON
4. execute the action locally
5. if Gemini says goal_complete: true, stop
6. otherwise go back to step 1
```

If an action fails 3 times in a row, it pauses and asks for human input before continuing. After a successful run, the action sequence gets saved as a playbook and reused on similar goals in the future.

### Actions the executor supports

| Action | What it does |
|---|---|
| `click` | click at x, y coordinates |
| `double_click` | double click at coordinates |
| `type` | type text (uses clipboard paste internally for reliability) |
| `key_combo` | keyboard shortcuts like `["ctrl", "c"]` |
| `scroll` | scroll up or down at a position |
| `move` | move mouse to coordinates |
| `wait` | pause for N seconds |
| `screenshot` | capture current screen state |
| `open_app` | launch an app by name |
| `open_url` | open a URL in the default browser |

---

## Prerequisites

- Python 3.11+
- Node.js 18+
- Docker and Docker Compose
- A Google Cloud project with these enabled:
  - Gemini API (you need a `GEMINI_API_KEY`)
  - Firestore in Native mode
  - Cloud Run
  - Vertex AI (used by the `/stt-task` endpoint to avoid rate limits)
  - Cloud Storage (optional, for screenshot archiving)

---

## Running locally

### 1. Clone and set up env

```bash
git clone https://github.com/AdityaChauhanX07/phantom-dev.git
cd phantom-dev
cp .env.example .env
# fill in .env with your keys
```

### 2. Start everything with Docker Compose

```bash
docker compose up --build
```

This starts the Agent on port 8000, Voice Gateway on port 8766, and Executor.

### 3. Run the dashboard

```bash
cd dashboard
npm install
npm run dev
```

Open http://localhost:3000.

---

## Running without Docker

### Agent

```bash
pip install -r agent/requirements.txt
cd agent && python main.py
```

### Executor

```bash
pip install -r executor/requirements.txt
cd executor && python orchestrator.py
```

### Voice Gateway

```bash
pip install -r voice/requirements.txt
cd voice && python main.py
```

---

## Environment variables

Copy `.env.example` to `.env` and fill these in:

| Variable | Required | Notes |
|---|---|---|
| `GEMINI_API_KEY` | yes | from Google AI Studio |
| `GCP_PROJECT_ID` | yes | your GCP project |
| `GCP_LOCATION` | yes | e.g. `us-central1` |
| `FIRESTORE_DB` | yes | usually `(default)` |
| `GCS_BUCKET` | no | for screenshot storage |
| `AGENT_URL` | yes | e.g. `http://localhost:8000` |
| `AGENT_PORT` | no | default `8000` |
| `VOICE_PORT` | no | default `8766` |
| `PHANTOM_MODE` | no | `local` or `cloud` |
| `LOG_LEVEL` | no | default `INFO` |

---

## Deploying to GCP

### Provision infrastructure

```bash
cd infra
terraform init
terraform apply
```

### Deploy services

```bash
bash scripts/deploy-agent.sh
bash scripts/deploy-voice.sh
```

See [docs/DEPLOY_STEPS.md](docs/DEPLOY_STEPS.md) for the full walkthrough, and [docs/DEPLOY_VERTEX_AI.md](docs/DEPLOY_VERTEX_AI.md) for Vertex AI setup and service account permissions.

---

## API reference

### Agent HTTP

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | liveness check, returns connected executor count |
| `POST` | `/task` | create a task: `{ "goal": "...", "session_id": "..." }` |
| `GET` | `/task/{task_id}` | get task state from Firestore |

### Voice Gateway HTTP

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | liveness check |
| `POST` | `/stt-task` | one-shot audio to task, body is raw audio bytes |

### WebSocket -- Agent

**`/ws/executor`** -- executor to agent

```json
{ "type": "screenshot", "task_id": "uuid", "data": "<base64>" }
{ "type": "task_result", "task_id": "uuid", "data": { "status": "completed" } }
```

**`/ws/dashboard`** -- agent to dashboard broadcasts

```json
{ "type": "task_queued", "task_id": "...", "goal": "..." }
{ "type": "screenshot", "task_id": "...", "gcs_uri": "gs://..." }
{ "type": "task_result", "task_id": "...", "status": "completed" }
```

### WebSocket -- Voice Gateway

**`/stream`** -- browser audio stream

```json
{ "type": "start", "session_id": "uuid" }
{ "type": "stop" }
{ "type": "status", "text": "Task completed." }
```

Binary frames in are raw PCM audio (16-bit, 16 kHz, mono). Binary frames out are Gemini audio response bytes.

---

## Project structure

```
phantom-dev/
├── agent/
│   ├── main.py              # WebSocket hub, Firestore, task routing
│   ├── Dockerfile
│   └── requirements.txt
├── executor/
│   ├── orchestrator.py      # reactive loop -- the main brain
│   ├── executor.py          # action dispatcher
│   ├── capture.py           # screen capture via mss
│   ├── gemini_client.py     # Gemini API wrapper
│   ├── playbook_manager.py  # saves and replays successful sequences
│   ├── ws_client.py         # WebSocket connection to Agent
│   └── requirements.txt
├── voice/
│   ├── main.py              # Live API bridge, STT, task detection
│   ├── Dockerfile
│   └── requirements.txt
├── dashboard/
│   └── app/
│       ├── page.tsx         # main UI
│       └── layout.tsx
├── infra/                   # Terraform
├── docs/                    # guides and troubleshooting
├── scripts/                 # deploy scripts
├── .env.example
├── docker-compose.yml
└── README.md
```

---

## Troubleshooting

- [docs/DEMO_SETUP_GUIDE.md](docs/DEMO_SETUP_GUIDE.md) -- full demo walkthrough
- [docs/DEMO_CONNECTION_GUIDE.md](docs/DEMO_CONNECTION_GUIDE.md) -- WebSocket connection issues
- [docs/CHECK_LOGS.md](docs/CHECK_LOGS.md) -- reading logs
- [docs/TESTING_GUIDE.md](docs/TESTING_GUIDE.md) -- running tests

---

## Contributors

- [AdityaChauhanX07](https://github.com/AdityaChauhanX07)
- [KhegaiVladimir](https://github.com/KhegaiVladimir)

---

## License

MIT
