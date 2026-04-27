# Step-by-Step Guide: Deploy with Vertex AI

## Step 1: Update executor/.env

The executor already supports Vertex AI. You need to add GCP_PROJECT_ID.

**Edit `executor/.env`:**

```bash
# Option 1: Use Vertex AI (recommended, no rate limit)
GCP_PROJECT_ID=phantom-dev-489603
GCP_LOCATION=us-central1
AGENT_WS_URL=wss://phantom-agent-874381233509.us-central1.run.app/ws/executor
PHANTOM_MODE=cloud

# Option 2: Use API key (fallback, has rate limit)
# GEMINI_API_KEY=your_key
# AGENT_WS_URL=wss://phantom-agent-874381233509.us-central1.run.app/ws/executor
# PHANTOM_MODE=cloud
```

**Important:**
- If `GCP_PROJECT_ID` is set — executor uses Vertex AI (no rate limit)
- If `GCP_PROJECT_ID` is not set but `GEMINI_API_KEY` is — uses AI Studio (has rate limit)
- Both can be set simultaneously, but `GCP_PROJECT_ID` takes priority

---

## Step 2: Check dashboard/.env.local

Dashboard does NOT use Gemini directly — it only uses WebSocket to communicate with the agent.

**Check `dashboard/.env.local`:**

```bash
NEXT_PUBLIC_AGENT_WS_URL=wss://phantom-agent-874381233509.us-central1.run.app/ws/dashboard
```

**No changes needed!** Dashboard only receives events from the agent via WebSocket.

---

## Step 3: Deploy the Voice Gateway

The voice gateway now uses Vertex AI for `/stt-task`.

**Run:**

```bash
./deploy-voice.sh
```

This script will:
1. Build the Docker image
2. Push it to Artifact Registry
3. Deploy to Cloud Run with the correct env vars

**Env vars in Cloud Run (set automatically):**
- `GCP_PROJECT_ID=phantom-dev-489603`
- `GCP_LOCATION=us-central1`
- `GEMINI_API_KEY=...` (for Live API fallback, if needed)
- `AGENT_URL=...`
- `TEXT_MODEL=gemini-2.5-flash`
- `LIVE_MODEL=gemini-2.5-flash-native-audio-preview-12-2025`

---

## Step 4: Verify the Deployment

**Check voice gateway logs:**

```bash
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20
```

**Look for in logs:**
- `[/stt-task] Using Vertex AI — project=phantom-dev-489603 location=us-central1`
- No more `429 RESOURCE_EXHAUSTED` errors

---

## Step 5: Test

### 5.1. Start the Dashboard (if not already running)

```bash
cd dashboard
npm run dev
```

Open: `http://localhost:3000`

### 5.2. Start the Executor

```bash
cd executor
PHANTOM_MODE=cloud python3 phantom.py
```

**Check executor logs:**
- Should show: `GeminiClient initialised with Vertex AI — project=phantom-dev-489603`
- Should NOT show: `GeminiClient falling back to AI Studio key`

### 5.3. Test the Voice Command

1. Open: `http://localhost:3000/voice-test.html`
2. Click the microphone button
3. Say: "Hey Phantom, test task"
4. Verify:
   - In voice gateway logs: `Using Vertex AI`
   - In dashboard: a new task appeared
   - NO 429 errors

---

## Architecture Overview

```
+------------------+
|  voice-test.html |
|  (browser)       |
+--------+---------+
         | HTTP POST /stt-task
         v
+------------------+
|  Voice Gateway   |
|  (Cloud Run)     |
|  Vertex AI       |
+--------+---------+
         | POST /task
         v
+------------------+
|  Agent           |
|  (Cloud Run)     |
+--------+---------+
         | WebSocket
         +------------------+
         v                  v
+-------------+    +-------------+
|  Executor   |    |  Dashboard  |
|  Vertex AI  |    |  (local)    |
|  (local)    |    |             |
+-------------+    +-------------+
```

**All components use Vertex AI:**
- Voice Gateway `/stt-task` → Vertex AI
- Executor → Vertex AI

**Does NOT use Gemini:**
- Dashboard (WebSocket events only)

---

## Troubleshooting

### Executor still uses API key

**Problem:** Logs show `GeminiClient falling back to AI Studio key`

**Solution:** Check `executor/.env`:
```bash
GCP_PROJECT_ID=phantom-dev-489603  # Must be present!
GCP_LOCATION=us-central1
```

### Voice gateway still returns 429

**Problem:** Still getting 429 errors

**Solution:**
1. Check logs: should show `Using Vertex AI`
2. If not — redeploy: `./deploy-voice.sh`
3. Verify Vertex AI API is enabled: `gcloud services list --enabled --project=phantom-dev-489603 | grep aiplatform`

### Dashboard not connecting

**Problem:** Dashboard shows "Disconnected"

**Solution:** Check `dashboard/.env.local`:
```bash
NEXT_PUBLIC_AGENT_WS_URL=wss://phantom-agent-874381233509.us-central1.run.app/ws/dashboard
```

---

## Done

After completing all steps:
- Voice gateway uses Vertex AI (no rate limit)
- Executor uses Vertex AI (no rate limit)
- Dashboard is connected to agent
- Voice commands are ready for testing

**Start with Step 1!**
