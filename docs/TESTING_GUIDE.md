# Complete Testing Guide for Phantom Dev

## Preparation (Once)

### 1. Verify All Services Are Running

**Cloud Run services:**
```bash
gcloud run services list --project=phantom-dev-489603
```

Should show:
- `phantom-agent` (status: Ready)
- `phantom-voice` (status: Ready)

**Local services:**
- Dashboard: `npm run dev` (should be running)
- Executor: will be started later

---

## Quick Start (Before Each Test Session)

### Step 1: Start the Dashboard

```bash
cd dashboard
npm run dev
```

**Verify:**
- Open `http://localhost:3000` → dashboard should load
- Browser console (F12) should show: `WebSocket connected`

### Step 2: Start the Executor

```bash
cd executor
PHANTOM_MODE=cloud python3 phantom.py
```

**Verify in executor logs:**
- `GeminiClient initialised with Vertex AI — project=phantom-dev-489603`
- `Connected to agent at wss://...`
- `Phantom is online. Waiting for tasks...`

**Verify in dashboard:**
- Should show: **"1 executor connected"** (green status)

---

## Tests by Level

### Level 1: Connection Checks

#### Test 1.1: Dashboard → Agent
1. Open `http://localhost:3000`
2. Check status: **"WebSocket connected"** (green)
3. If red — check `.env.local` in `dashboard/`

#### Test 1.2: Executor → Agent
1. Start the executor (see above)
2. Executor logs should show: `Connected to agent at wss://...`
3. Dashboard should show: **"1 executor connected"**

#### Test 1.3: Voice Gateway → Agent
```bash
curl https://phantom-voice-874381233509.us-central1.run.app/health
```

Should return: `{"status":"ok","active_session":false}`

---

### Level 2: Simple Tasks (Without Executor)

#### Test 2.1: Voice Command → Task Created

1. Open `http://localhost:3000/voice-test.html`
2. Click the microphone button
3. Say: **"Hey Phantom, test task"**
4. Verify:
   - Browser console: `HTTP TASK DETECTED: test task (task_id=...)`
   - Dashboard: a new task with status `queued` appeared
   - Voice gateway logs (see below): `Task created in agent`

**Check voice gateway logs:**
```bash
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20 | grep -E "stt-task|Task created"
```

**Check agent logs:**
```bash
gcloud run services logs read phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20 | grep -E "Task created"
```

---

### Level 3: Simple Tasks (With Executor)

#### Test 3.1: Open an Application

**Command:** "Hey Phantom, open Safari"

**Expected behavior:**
1. Executor receives the task
2. Executor opens Safari (via `open_app`)
3. Safari opens on screen
4. Task completes with status `completed`

**Verify:**
- Executor logs: `Executing: {'type': 'open_app', 'app_name': 'Safari'}`
- Safari opened on screen
- Dashboard: task status → `completed`

#### Test 3.2: Open a Website

**Command:** "Hey Phantom, open Google"

**Expected behavior:**
1. Executor opens Google in the browser (via `open_url`)
2. Google opens in a new tab
3. Task completes

**Verify:**
- Executor logs: `Executing: {'type': 'open_url', 'url': 'https://www.google.com'}`
- Google opened in the browser
- Dashboard: status → `completed`

#### Test 3.3: Search in Google

**Command:** "Hey Phantom, open Google and search for Gemini"

**Expected behavior:**
1. Executor opens Google
2. Executor finds the search bar and clicks it
3. Executor types "Gemini"
4. Executor presses Enter
5. Search results appear
6. Task completes

**Verify:**
- Executor logs: `Executing: {'type': 'open_url', ...}`
- Then: `Executing: {'type': 'type', 'text': 'Gemini', ...}`
- Then: `Executing: {'type': 'key_combo', 'keys': ['return']}`
- On screen: "Gemini" search results
- Dashboard: status → `completed`

**If the executor misses the search bar:**
- Check logs: a fallback method (Tab navigation) may be used
- This is acceptable if the search completes successfully

---

### Level 4: Complex Tasks (Full Scenario)

#### Test 4.1: YouTube Search

**Command:** "Hey Phantom, open YouTube and search for Gemini AI"

**Expected behavior:**
1. Executor opens YouTube
2. Executor finds the search bar
3. Executor types "Gemini AI"
4. Executor presses Enter
5. Search results appear
6. Task completes

**Verify:**
- All steps completed in order
- Search results visible on screen
- Dashboard: status → `completed`

#### Test 4.2: Multi-Step Task

**Command:** "Hey Phantom, open Safari, then open Google, then search for Phantom Dev"

**Expected behavior:**
1. Executor opens Safari
2. Executor opens Google in Safari
3. Executor searches for "Phantom Dev"
4. Task completes

**Verify:**
- All steps completed
- Dashboard: status → `completed`

---

## How to Check Logs During a Test

### Real-Time (Stream)

**Voice Gateway:**
```bash
gcloud run services logs tail phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603
```

**Agent:**
```bash
gcloud run services logs tail phantom-agent \
  --region=us-central1 \
  --project=phantom-dev-489603
```

**Executor:**
- Logs are visible directly in the terminal where the executor is running

**Dashboard:**
- Open DevTools (F12) → Console
- All WebSocket events will appear in the console

---

## Common Issues and Solutions

### Issue 1: Executor Does Not Connect

**Symptoms:**
- Dashboard: "No executor connected"
- Executor logs: connection error

**Solution:**
1. Verify the executor is running
2. Check `.env` in `executor/`:
   - `AGENT_WS_URL=wss://phantom-agent-874381233509.us-central1.run.app/ws/executor`
3. Verify Application Default Credentials exist:
   ```bash
   gcloud auth application-default login --project=phantom-dev-489603
   ```

### Issue 2: Voice Gateway Returns 429

**Symptoms:**
- Voice gateway logs: `429 RESOURCE_EXHAUSTED`
- Browser console: error when sending voice command

**Solution:**
1. Verify voice gateway is using Vertex AI:
   ```bash
   gcloud run services logs read phantom-voice \
     --region=us-central1 \
     --project=phantom-dev-489603 \
     --limit=20 | grep "Vertex AI"
   ```
2. Should show: `[/stt-task] Using Vertex AI — project=phantom-dev-489603`
3. If not — redeploy the voice gateway (see `DEPLOY_VERTEX_AI.md`)

### Issue 3: Executor Does Not Perform Actions

**Symptoms:**
- Executor receives the task but nothing happens on screen
- Executor logs show `Executing: ...` but no actions occur

**Solution:**
1. Check macOS permissions:
   - System Settings → Privacy & Security → Accessibility
   - Terminal (or Python) must be enabled
2. Check Input Monitoring:
   - System Settings → Privacy & Security → Input Monitoring
   - Terminal (or Python) must be enabled
3. Restart the executor after enabling permissions

### Issue 4: Executor Misses the Search Bar

**Symptoms:**
- Executor attempts to click but misses the search bar
- Logs show incorrect coordinates

**Solution:**
1. This is expected — executor uses a fallback method (Tab navigation)
2. If the search still fails:
   - Verify the browser is in focus
   - Verify the search bar is visible on screen
   - Try increasing screen resolution (not zoom)

### Issue 5: Task Does Not Complete

**Symptoms:**
- Executor performs all actions but task remains in `running` status
- Dashboard status does not change to `completed`

**Solution:**
1. Check executor logs: should show `Task completed successfully`
2. If not — check `VERIFY_PROMPT` in `orchestrator.py`
3. Gemini may not be recognizing successful completion
4. Try a simpler task to verify

---

## Full Test Checklist

### Before Each Test:
- [ ] Dashboard is running (`npm run dev`)
- [ ] Executor is running (`python3 phantom.py`)
- [ ] Dashboard shows "1 executor connected"
- [ ] Dashboard shows WebSocket connected

### After Each Test:
- [ ] Task appeared in dashboard
- [ ] Task status changed to `completed` (or `failed` with a clear error message)
- [ ] Executor logs show `Task completed successfully`
- [ ] Task is visually completed on screen

---

## Full End-to-End Test

### Scenario: "Open Google and Search for Gemini"

1. **Start all components:**
   - Dashboard: `npm run dev`
   - Executor: `python3 phantom.py`

2. **Verify connections:**
   - Dashboard: WebSocket connected
   - Dashboard: 1 executor connected

3. **Execute the voice command:**
   - Open `http://localhost:3000/voice-test.html`
   - Say: "Hey Phantom, open Google and search for Gemini"

4. **Watch:**
   - Dashboard: task appears → status `queued` → `running`
   - On screen: Google opens → search bar → type "Gemini" → Enter
   - Dashboard: status → `completed`

5. **Verify the result:**
   - "Gemini" search results visible on screen
   - Dashboard: task completed successfully
   - Executor logs: `Task completed successfully`

---

## Done

Now you know how to test all components of Phantom Dev. Start with **Level 1** and gradually move to more complex tests.

**Tip:** If something is not working, check logs first (see `CHECK_LOGS.md`), then macOS permissions, then connections between components.
