#!/bin/bash
# ──────────────────────────────────────────────────────────────
# LaunchPad-AI — Pub/Sub OIDC Push Auth & DLQ Setup Script
# ──────────────────────────────────────────────────────────────
# Configures secure OIDC authentication for Pub/Sub push subscription
# to Cloud Run, and sets up dead-letter queue (DLQ) retention.

set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:-launchpad-ai-506616}"
REGION="${GOOGLE_CLOUD_LOCATION:-asia-south1}"
SERVICE_NAME="launchpad-ai"
TOPIC_NAME="launchpad-ai-events"
SUB_NAME="launchpad-ai-events-push"
DLQ_TOPIC="launchpad-ai-dead-letter"
DLQ_SUB="launchpad-ai-dead-letter-sub"
SA_NAME="pubsub-invoker"
SA_EMAIL="${SA_NAME}@${PROJECT}.iam.gserviceaccount.com"

echo "=== Configuring Pub/Sub OIDC Auth for $PROJECT ($REGION) ==="

# 1. Ensure service account exists
if ! gcloud iam service-accounts describe "$SA_EMAIL" --project="$PROJECT" &>/dev/null; then
  echo "Creating service account: $SA_EMAIL"
  gcloud iam service-accounts create "$SA_NAME" \
    --display-name="LaunchPad-AI Pub/Sub Invoker" \
    --project="$PROJECT"
  sleep 5
fi

# 2. Grant Cloud Run Invoker role to the service account
echo "Granting roles/run.invoker to $SA_EMAIL on Cloud Run service $SERVICE_NAME..."
gcloud run services add-iam-policy-binding "$SERVICE_NAME" \
  --region="$REGION" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.invoker" \
  --project="$PROJECT" \
  --quiet

# 3. Get Cloud Run endpoint URL
SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" --region="$REGION" --project="$PROJECT" --format="value(status.url)")
PROCESS_ENDPOINT="${SERVICE_URL}/process"

# 4. Update Pub/Sub push subscription with OIDC Token and DLQ policy
echo "Updating push subscription $SUB_NAME to endpoint $PROCESS_ENDPOINT with OIDC..."
gcloud pubsub subscriptions update "$SUB_NAME" \
  --push-endpoint="$PROCESS_ENDPOINT" \
  --push-auth-service-account="$SA_EMAIL" \
  --dead-letter-topic="$DLQ_TOPIC" \
  --max-delivery-attempts=5 \
  --project="$PROJECT"

# 5. Ensure DLQ pull subscription exists for poison message inspection
if ! gcloud pubsub subscriptions describe "$DLQ_SUB" --project="$PROJECT" &>/dev/null; then
  echo "Creating DLQ pull subscription: $DLQ_SUB..."
  gcloud pubsub subscriptions create "$DLQ_SUB" \
    --topic="$DLQ_TOPIC" \
    --message-retention-duration=7d \
    --project="$PROJECT"
fi

echo "=== Pub/Sub OIDC Push Auth & DLQ Setup Complete ==="
