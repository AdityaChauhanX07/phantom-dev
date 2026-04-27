# Deploy Voice Gateway with Vertex AI

## Changes Made

✅ **Updated `voice/main.py`:**
- `/stt-task` endpoint now uses Vertex AI instead of AI Studio
- GCP_PROJECT_ID set to `phantom-dev-489603` (existing project)
- GCP_LOCATION set to `us-central1`
- Live API tries Vertex AI first, falls back to API key if needed

---

## Prerequisites

### 1. Enable Vertex AI API

```bash
gcloud services enable aiplatform.googleapis.com \
  --project=phantom-dev-489603
```

### 2. Verify Service Account Permissions

Cloud Run service account needs Vertex AI permissions:

```bash
# Get the service account email
gcloud run services describe phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --format="value(spec.template.spec.serviceAccountName)"

# Grant Vertex AI User role (if not already granted)
gcloud projects add-iam-policy-binding phantom-dev-489603 \
  --member="serviceAccount:SERVICE_ACCOUNT_EMAIL" \
  --role="roles/aiplatform.user"
```

---

## Deploy Updated Voice Gateway

### 1. Build and Push Docker Image

```bash
cd voice
docker build --platform linux/amd64 \
  -t us-central1-docker.pkg.dev/phantom-dev-489603/phantom-dev/voice:latest .

docker push us-central1-docker.pkg.dev/phantom-dev-489603/phantom-dev/voice:latest
```

**Note:** Update Artifact Registry path if different for project `phantom-dev-489603`.

### 2. Deploy to Cloud Run

```bash
gcloud run deploy phantom-voice \
  --image=us-central1-docker.pkg.dev/phantom-dev-489603/phantom-dev/voice:latest \
  --platform=managed \
  --region=us-central1 \
  --allow-unauthenticated \
  --port=8000 \
  --set-env-vars="GCP_PROJECT_ID=phantom-dev-489603,GCP_LOCATION=us-central1,AGENT_URL=https://phantom-agent-874381233509.us-central1.run.app,TEXT_MODEL=gemini-2.5-flash,LIVE_MODEL=gemini-2.5-flash-native-audio-preview-12-2025,LOG_LEVEL=DEBUG" \
  --project=phantom-dev-489603
```

**Important:** 
- Removed `GEMINI_API_KEY` from env vars (not needed for Vertex AI)
- Added `GCP_PROJECT_ID` and `GCP_LOCATION`

### 3. Verify Deployment

```bash
# Check health
curl https://phantom-voice-874381233509.us-central1.run.app/health

# Check logs
gcloud run services logs read phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --limit=20
```

Look for:
- `[/stt-task] Using Vertex AI — project=phantom-dev-489603 location=us-central1`
- No more 429 errors

---

## Test

1. **Open voice-test.html:**
   - `http://localhost:3000/voice-test.html`

2. **Say a command:**
   - "Hey Phantom, test task"

3. **Check logs:**
   - Should see Vertex AI usage
   - No 429 errors
   - Task should be created successfully

---

## Troubleshooting

### Vertex AI API not enabled

**Error:** `aiplatform.googleapis.com` not enabled

**Fix:**
```bash
gcloud services enable aiplatform.googleapis.com --project=phantom-dev-489603
```

### Permission denied

**Error:** Service account doesn't have Vertex AI permissions

**Fix:**
```bash
# Get service account
SERVICE_ACCOUNT=$(gcloud run services describe phantom-voice \
  --region=us-central1 \
  --project=phantom-dev-489603 \
  --format="value(spec.template.spec.serviceAccountName)")

# Grant permission
gcloud projects add-iam-policy-binding phantom-dev-489603 \
  --member="serviceAccount:${SERVICE_ACCOUNT}" \
  --role="roles/aiplatform.user"
```

### Wrong project ID

**Error:** Project not found or wrong region

**Fix:** Verify project ID and region:
```bash
gcloud projects list
gcloud config get-value project
```

---

## Benefits

✅ **No more rate limits** — Vertex AI has much higher quotas  
✅ **Better for production** — Designed for cloud workloads  
✅ **Cost tracking** — Usage visible in GCP console  
✅ **Scalability** — Handles more concurrent requests

---

## After Deployment

1. ✅ Test voice command
2. ✅ Verify no 429 errors
3. ✅ Check Vertex AI usage in GCP console
4. ✅ Continue integration testing

**Ready to deploy!** 🚀
