# Fix: Deploy Voice Gateway with Correct Settings

## Problem

The logs show:
- `GeminiLiveGateway using Vertex AI` (old code)
- `GEMINI_API_KEY is not set` (key not set)
- Error 1008 when trying to use Live API via Vertex AI

## Solution

### 1. Ensure GEMINI_API_KEY is set

```bash
# Check if the key is in the environment
echo $GEMINI_API_KEY

# If not, set it (replace with your key)
export GEMINI_API_KEY="your_key_here"
```

### 2. Deploy the updated code

```bash
./deploy-voice.sh
```

The script will automatically:
- Build the Docker image with the fixed code
- Set `GEMINI_API_KEY` in Cloud Run
- Set `GCP_PROJECT_ID` for `/stt-task` (Vertex AI)

### 3. Verify the deployment

```bash
gcloud run services describe phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --format="value(spec.template.spec.containers[0].env)" | grep -E "GEMINI_API_KEY|GCP_PROJECT_ID"
```

Should show:
- `GEMINI_API_KEY=...`
- `GCP_PROJECT_ID=phantom-dev-489603`

### 4. Check the logs

```bash
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20
```

**Expected logs:**
- `GeminiLiveGateway using API key for Live API` (not Vertex AI!)
- `[/stt-task] Using Vertex AI — project=phantom-dev-489603` (for /stt-task)
- Should NOT show: `GEMINI_API_KEY is not set`

---

## Architecture Summary

- **Live API (WebSocket `/stream`)** → uses `GEMINI_API_KEY`
- **`/stt-task` endpoint** → uses Vertex AI (`GCP_PROJECT_ID`)

---

## If GEMINI_API_KEY is Not Set

1. Get the key: https://aistudio.google.com/apikey
2. Set it in your environment:
   ```bash
   export GEMINI_API_KEY="your_key"
   ```
3. Deploy:
   ```bash
   ./deploy-voice.sh
   ```

**Done.**
