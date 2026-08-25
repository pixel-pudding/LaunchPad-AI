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
