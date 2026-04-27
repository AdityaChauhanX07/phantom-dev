# How to Check Logs for All Components

## 1. Voice Gateway (Cloud Run)

```bash
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=50
```

**What to look for:**
- `GeminiLiveGateway using API key for Live API`
- `[/stt-task] Using Vertex AI — project=phantom-dev-489603`
- `Task created in agent — task_id=...`
- NO `429` or `1008` errors

**Last 20 lines:**
```bash
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20
```

---

## 2. Agent (Cloud Run)

```bash
gcloud run services logs read phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=50
```

**What to look for:**
- `[POST /task] Task created — task_id=...`
- `[WS /ws/executor] Task dispatched to executor`
- `connected_executors: 1` (if executor is connected)

**Last 20 lines:**
```bash
gcloud run services logs read phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20
```

---

## 3. Executor (locally, in terminal)

**Logs are visible directly in the terminal where the executor is running.**

**What to look for:**
- `GeminiClient initialised with Vertex AI — project=phantom-dev-489603`
- `Connected to agent at wss://...`
- `Phantom is online. Waiting for tasks...`
- `Received task: '...'`
- `Executing: {'type': 'click', ...}`
- NO `Your default credentials were not found` errors

**To save logs to a file:**
```bash
cd executor
PHANTOM_MODE=cloud python3 /Users/vladimirkhegai/Desktop/gemini_hackathon/phantom-dev/executor/phantom.py 2>&1 | tee executor.log
```

---

## 4. Dashboard (in browser)

**Open DevTools (F12) → Console**

**What to look for:**
- `WebSocket connected`
- `Received event: task_queued`
- `Received event: task_result`
- NO WebSocket errors

**Network tab:**
- Check the WebSocket connection to agent
- Should show status `101 Switching Protocols`

---

## Quick Commands (copy and paste)

### All logs from the last 5 minutes

```bash
# Voice gateway
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=50

# Agent
gcloud run services logs read phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=50
```

### Errors only

```bash
# Voice gateway (ERROR only)
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=100 | grep ERROR

# Agent (ERROR only)
gcloud run services logs read phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=100 | grep ERROR
```

### Stream logs in real time

```bash
# Voice gateway (stream)
gcloud run services logs tail phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603

# Agent (stream)
gcloud run services logs tail phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603
```

---

## What to Check After a Voice Command

### 1. Voice Gateway

```bash
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=30 | grep -E "stt-task|Task created"
```

**Expected:**
- `[/stt-task] Using Vertex AI`
- `Task created in agent — task_id=...`

### 2. Agent

```bash
gcloud run services logs read phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=30 | grep -E "Task created|dispatched"
```

**Expected:**
- `[POST /task] Task created — task_id=...`
- `[WS /ws/executor] Task dispatched to executor`

### 3. Executor

**In the executor terminal you should see:**
- `Received task: '...'`
- `GeminiClient initialised with Vertex AI`
- `Executing: ...`
- `Task completed successfully`

---

## Troubleshooting

### No logs in Cloud Run

**Check that services are running:**
```bash
gcloud run services list --project=phantom-dev-489603
```

### Executor shows no logs

**Check that executor is running:**
- Should show: `Phantom is online. Waiting for tasks...`

### Dashboard shows no events

**Check browser console (F12):**
- Should show: `WebSocket connected`
- NO WebSocket errors

---

## Done

Now you know how to check the logs for all system components.
