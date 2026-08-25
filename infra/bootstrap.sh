#!/bin/bash
# ──────────────────────────────────────────────────────────────
# LaunchPad-AI — GCP Bootstrap Script
# Run this once to provision all GCP resources for the project.
# Prereqs: gcloud CLI installed + authenticated, billing linked.
# ──────────────────────────────────────────────────────────────

set -euo pipefail

PROJECT="launchpad-ai-506616"
REGION="asia-south1"

echo "=== Setting project ==="
gcloud config set project "$PROJECT"

echo "=== Enabling APIs ==="
gcloud services enable \
  run.googleapis.com \
  aiplatform.googleapis.com \
  pubsub.googleapis.com \
  firestore.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  cloudtrace.googleapis.com

echo "=== Creating Firestore database (native mode) ==="
gcloud firestore databases create --location="$REGION" || echo "Firestore already exists"

echo "=== Creating Pub/Sub topics ==="
gcloud pubsub topics create launchpad-ai-events || echo "Topic already exists"
gcloud pubsub topics create launchpad-ai-dead-letter || echo "Dead-letter topic already exists"

echo "=== Creating Secret Manager secrets (empty — fill in later) ==="
gcloud secrets create github-app-key --replication-policy=automatic || echo "Secret already exists"
gcloud secrets create github-webhook-secret --replication-policy=automatic || echo "Secret already exists"

echo "=== Setting IAM roles for default compute service account ==="
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT" --format="value(projectNumber)")
SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for role in roles/storage.objectAdmin roles/artifactregistry.writer roles/datastore.user roles/aiplatform.user roles/secretmanager.secretAccessor roles/pubsub.publisher roles/logging.logWriter roles/cloudtrace.agent; do
  gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role="$role" --quiet || true
done

echo "=== Creating Pub/Sub push subscription ==="
SERVICE_URL=$(gcloud run services describe launchpad-ai --region="$REGION" --project="$PROJECT" --format="value(status.url)" 2>/dev/null || echo "")
if [ -n "$SERVICE_URL" ]; then
  gcloud pubsub subscriptions create launchpad-ai-events-push \
    --topic=launchpad-ai-events \
    --push-endpoint="${SERVICE_URL}/process" \
    --dead-letter-topic=launchpad-ai-dead-letter \
    --max-delivery-attempts=5 \
    --ack-deadline=600 \
    --project="$PROJECT" || echo "Subscription already exists"
fi

echo ""
echo "=== Verification ==="
echo "--- Enabled APIs ---"
gcloud services list --enabled \
  --filter="config.name:(run OR aiplatform OR pubsub OR firestore OR secretmanager OR cloudbuild OR artifactregistry OR cloudtrace)" \
  --format="table(config.name)"

echo "--- Firestore ---"
gcloud firestore databases describe --format="table(name, locationId, type)"

echo "--- Pub/Sub Topics ---"
gcloud pubsub topics list --format="table(name)"

echo "--- Secrets ---"
gcloud secrets list --format="table(name)"

echo ""
echo "✅ GCP bootstrap complete."
