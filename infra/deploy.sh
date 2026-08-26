#!/bin/bash
# ──────────────────────────────────────────────────────────────
# LaunchPad-AI — Cloud Run Deploy Script
# ──────────────────────────────────────────────────────────────

set -euo pipefail

PROJECT="launchpad-ai-506616"
REGION="asia-south1"
SERVICE_NAME="launchpad-ai"

echo "=== Deploying $SERVICE_NAME to Cloud Run ($REGION) ==="

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080 \
  --memory 512Mi \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=$PROJECT,GOOGLE_CLOUD_LOCATION=$REGION,GOOGLE_GENAI_USE_VERTEXAI=1,GEMINI_MODEL=gemini-3.5-flash,GITHUB_APP_ID=4721900,IMAGE_MOCK_MODE=0,IMAGEN_MODEL=imagen-3.0-generate-002" \
  --quiet

echo ""
echo "=== Deployment complete ==="
gcloud run services describe "$SERVICE_NAME" --project "$PROJECT" --region "$REGION" --format="value(status.url)"
