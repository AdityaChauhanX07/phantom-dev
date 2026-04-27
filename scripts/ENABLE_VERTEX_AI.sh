#!/bin/bash
# Enable Vertex AI API for phantom-dev-489603

set -e

PROJECT_ID="phantom-dev-489603"

echo "🔧 Enabling Vertex AI API for project ${PROJECT_ID}..."

gcloud services enable aiplatform.googleapis.com \
  --project=${PROJECT_ID}

echo "✅ Vertex AI API enabled!"
echo ""
echo "Next steps:"
echo "1. Build and deploy voice gateway (see DEPLOY_VERTEX_AI.md)"
echo "2. Test voice command"
echo "3. Verify no more 429 errors"
