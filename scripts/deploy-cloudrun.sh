#!/usr/bin/env bash
#
# Deploy AgriSage to Google Cloud Run.
#
# Cloud Run builds the repo-root Dockerfile via Cloud Build (`--source .`), so
# you do NOT need Docker installed locally.
#
# Prerequisites:
#   - gcloud CLI installed and authenticated:   gcloud auth login
#   - a project selected:                        gcloud config set project <PROJECT_ID>
#   - the required APIs enabled (run once):
#       gcloud services enable run.googleapis.com cloudbuild.googleapis.com \
#         artifactregistry.googleapis.com
#   - OPENAI_API_KEY exported in your shell (never commit it):
#       export OPENAI_API_KEY=sk-...
#
# Usage:
#   ./scripts/deploy-cloudrun.sh
#   SERVICE=agrisage REGION=asia-northeast3 ./scripts/deploy-cloudrun.sh
#
set -euo pipefail

SERVICE="${SERVICE:-agrisage}"
REGION="${REGION:-asia-northeast3}"   # Seoul

if [[ -z "${OPENAI_API_KEY:-}" ]]; then
  echo "ERROR: export OPENAI_API_KEY before running (it is never committed)." >&2
  echo "  export OPENAI_API_KEY=sk-..." >&2
  exit 1
fi

# Run from the repo root so `--source .` picks up the Dockerfile and all code.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Env vars the container needs at runtime. MODEL_* are also baked into the image
# as defaults; passing them here keeps them explicit/overridable. Add
# OPENAI_MODEL / OPENAI_EMBEDDING_MODEL to this list to override the defaults.
ENV_VARS="OPENAI_API_KEY=${OPENAI_API_KEY}"
ENV_VARS="${ENV_VARS},MODEL_CHECKPOINT_PATH=backend/models/weights/classification_model.pth"
ENV_VARS="${ENV_VARS},MODEL_CONFIG_PATH=backend/models/config6.json"

echo "Deploying '${SERVICE}' to Cloud Run in ${REGION} ..."
gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --concurrency 8 \
  --set-env-vars "${ENV_VARS}"

echo
echo "Done. Service URL:"
gcloud run services describe "${SERVICE}" --region "${REGION}" \
  --format 'value(status.url)'
