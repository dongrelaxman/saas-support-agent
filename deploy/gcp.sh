#!/usr/bin/env bash
# deploy/gcp.sh — Build and deploy TaskPilot to Google Cloud Run
#
# Prerequisites (one-time manual setup):
#   1. gcloud auth login && gcloud auth configure-docker <REGION>-docker.pkg.dev
#   2. gcloud projects create <PROJECT_ID>  (or use existing)
#   3. Enable APIs:
#        gcloud services enable run.googleapis.com \
#          artifactregistry.googleapis.com \
#          sqladmin.googleapis.com \
#          secretmanager.googleapis.com
#   4. Create Artifact Registry repo:
#        gcloud artifacts repositories create taskpilot \
#          --repository-format=docker --location=<REGION>
#   5. Create Cloud SQL Postgres 16 instance:
#        gcloud sql instances create taskpilot-pg \
#          --database-version=POSTGRES_16 --tier=db-f1-micro \
#          --region=<REGION>
#        gcloud sql databases create agentdb --instance=taskpilot-pg
#        gcloud sql users set-password postgres --instance=taskpilot-pg --password=<DB_PASS>
#   6. Store secrets in Secret Manager:
#        printf "your-key" | gcloud secrets create OPENAI_API_KEY --data-file=-
#        (repeat for WEAVIATE_URL, WEAVIATE_API_KEY, LANGCHAIN_API_KEY, SLACK_WEBHOOK_URL, DB_PASS)
#
# Usage:
#   export GCP_PROJECT=your-project-id
#   export DB_PASS=your-postgres-password
#   bash deploy/gcp.sh

set -euo pipefail

# ── Config (edit these or export before running) ─────────────────────────────
GCP_PROJECT="${GCP_PROJECT:?Set GCP_PROJECT}"
GCP_REGION="${GCP_REGION:-us-central1}"
DB_PASS="${DB_PASS:?Set DB_PASS}"

REPO="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT}/taskpilot"
SQL_INSTANCE="${GCP_PROJECT}:${GCP_REGION}:taskpilot-pg"
DB_URL="postgresql://postgres:${DB_PASS}@/agentdb?host=/cloudsql/${SQL_INSTANCE}"

BACKEND_IMAGE="${REPO}/backend:latest"
FRONTEND_IMAGE="${REPO}/frontend:latest"

echo "=== TaskPilot → GCP Cloud Run ==="
echo "Project : ${GCP_PROJECT}"
echo "Region  : ${GCP_REGION}"
echo ""

# ── 1. Build and push backend ─────────────────────────────────────────────────
echo "── [1/4] Building backend image..."
docker build \
  -f backend/Dockerfile \
  -t "${BACKEND_IMAGE}" \
  .

echo "── [2/4] Pushing backend image..."
docker push "${BACKEND_IMAGE}"

# ── 2. Deploy backend to Cloud Run ───────────────────────────────────────────
echo "── [3/4] Deploying backend to Cloud Run..."
gcloud run deploy taskpilot-backend \
  --image="${BACKEND_IMAGE}" \
  --region="${GCP_REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --port=8001 \
  --set-env-vars="PORT=8001,LANGCHAIN_TRACING_V2=true,LANGCHAIN_PROJECT=taskpilot-support-agent" \
  --set-secrets="\
OPENAI_API_KEY=OPENAI_API_KEY:latest,\
WEAVIATE_URL=WEAVIATE_URL:latest,\
WEAVIATE_API_KEY=WEAVIATE_API_KEY:latest,\
LANGCHAIN_API_KEY=LANGCHAIN_API_KEY:latest,\
SLACK_WEBHOOK_URL=SLACK_WEBHOOK_URL:latest" \
  --set-env-vars="DATABASE_URL=${DB_URL}" \
  --add-cloudsql-instances="${SQL_INSTANCE}" \
  --min-instances=0 \
  --max-instances=3 \
  --memory=512Mi \
  --cpu=1

# Grab the deployed backend URL
BACKEND_URL=$(gcloud run services describe taskpilot-backend \
  --region="${GCP_REGION}" \
  --format="value(status.url)")

echo "Backend live at: ${BACKEND_URL}"
echo ""

# ── 3. Build and push frontend ────────────────────────────────────────────────
echo "── [4/4] Building frontend image..."
# BACKEND_URL is injected at container start via nginx envsubst — not a build arg.
docker build \
  -f frontend/Dockerfile \
  -t "${FRONTEND_IMAGE}" \
  .

docker push "${FRONTEND_IMAGE}"

# ── 4. Deploy frontend to Cloud Run ──────────────────────────────────────────
echo "── Deploying frontend to Cloud Run..."
gcloud run deploy taskpilot-frontend \
  --image="${FRONTEND_IMAGE}" \
  --region="${GCP_REGION}" \
  --platform=managed \
  --allow-unauthenticated \
  --port=80 \
  --set-env-vars="BACKEND_URL=${BACKEND_URL}" \
  --min-instances=0 \
  --max-instances=3 \
  --memory=256Mi \
  --cpu=1

FRONTEND_URL=$(gcloud run services describe taskpilot-frontend \
  --region="${GCP_REGION}" \
  --format="value(status.url)")

echo ""
echo "=================================="
echo "  Deployment complete"
echo "  Frontend : ${FRONTEND_URL}"
echo "  Backend  : ${BACKEND_URL}"
echo "=================================="
