#!/bin/bash
# Deploy Agent to Cloud Run
# Usage: ./deploy-agent.sh

set -e

PROJECT_ID="phantom-dev-489603"
REGION="us-central1"
SERVICE_NAME="phantom-agent"
IMAGE_NAME="us-central1-docker.pkg.dev/${PROJECT_ID}/phantom-dev/agent:latest"

echo "🔨 Building Docker image..."
cd agent
docker build --platform linux/amd64 -t ${IMAGE_NAME} .

echo "📤 Pushing to Artifact Registry..."
docker push ${IMAGE_NAME}

echo "🚀 Deploying to Cloud Run..."
gcloud run deploy ${SERVICE_NAME} \
  --image=${IMAGE_NAME} \
  --platform=managed \
  --region=${REGION} \
  --allow-unauthenticated \
  --port=8000 \
  --set-env-vars="GEMINI_API_KEY=${GEMINI_API_KEY},GCP_PROJECT_ID=${PROJECT_ID}" \
  --project=${PROJECT_ID}

echo "✅ Agent deployed!"
echo "🌐 URL: https://phantom-agent-874381233509.us-central1.run.app"
