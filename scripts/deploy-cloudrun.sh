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
#   - secrets exported in your shell (never commit them):
#       export OPENAI_API_KEY=sk-...
#       export JWT_SECRET=$(python -c "import secrets; print(secrets.token_hex(32))")
#       export ADMIN_ID=admin@agrisage.app ADMIN_PASSWORD=...
#
# Usage:
#   ./scripts/deploy-cloudrun.sh
#   SERVICE=agrisage REGION=us-central1 ./scripts/deploy-cloudrun.sh
#
set -euo pipefail

SERVICE="${SERVICE:-agrisage}"
REGION="${REGION:-asia-northeast3}"   # Seoul

for var in OPENAI_API_KEY JWT_SECRET ADMIN_ID ADMIN_PASSWORD; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: export ${var} before running (it is never committed)." >&2
    exit 1
  fi
done

# Run from the repo root so `--source .` picks up the Dockerfile and all code.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Env vars the container needs at runtime. MODEL_* are also baked into the image
# as defaults; passing them here keeps them explicit/overridable. Add
# OPENAI_MODEL / OPENAI_EMBEDDING_MODEL to this list to override the defaults.
ENV_VARS="OPENAI_API_KEY=${OPENAI_API_KEY}"
ENV_VARS="${ENV_VARS},JWT_SECRET=${JWT_SECRET}"
ENV_VARS="${ENV_VARS},ADMIN_ID=${ADMIN_ID}"
ENV_VARS="${ENV_VARS},ADMIN_PASSWORD=${ADMIN_PASSWORD}"
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
