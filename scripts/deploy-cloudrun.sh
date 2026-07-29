#!/usr/bin/env bash
#
# Deploy AgriSage to Cloud Run with version-pinned Secret Manager references.
# The default is a disposable, single-instance SQLite demo with no Cloud SQL.
# Set EPHEMERAL_DEMO=false to deploy with persistent PostgreSQL instead.
#
# Required for both modes:
#   RUN_SERVICE_ACCOUNT=agrisage-run@PROJECT_ID.iam.gserviceaccount.com
#   OPENAI_API_KEY_SECRET_REF=agrisage-openai-api-key:1
#   JWT_SECRET_SECRET_REF=agrisage-jwt-secret:1
#   ADMIN_ID_SECRET_REF=agrisage-admin-id:1
#   ADMIN_PASSWORD_SECRET_REF=agrisage-admin-password:1
#   ADMIN_CONFIG_VERSION=1
#
# Persistent mode additionally requires:
#   EPHEMERAL_DEMO=false
#   CLOUD_SQL_INSTANCE=PROJECT_ID:REGION:INSTANCE
#   DATABASE_URL_SECRET_REF=agrisage-database-url:1
#
# DATABASE_URL secret example for a Cloud SQL Unix socket:
#   postgresql://USER:PERCENT_ENCODED_PASSWORD@/agrisage?host=/cloudsql/PROJECT:REGION:INSTANCE
#
# The runtime service account needs roles/secretmanager.secretAccessor on the
# referenced secrets. Persistent mode also needs roles/cloudsql.client.
#
set -euo pipefail

SERVICE="${SERVICE:-agrisage}"
REGION="${REGION:-asia-northeast3}"
EPHEMERAL_DEMO="${EPHEMERAL_DEMO:-true}"

case "${EPHEMERAL_DEMO,,}" in
  true|1|yes|on) EPHEMERAL_DEMO=true ;;
  false|0|no|off) EPHEMERAL_DEMO=false ;;
  *)
    echo "ERROR: EPHEMERAL_DEMO must be true or false." >&2
    exit 1
    ;;
esac

if [[ "${EPHEMERAL_DEMO}" == "true" ]]; then
  MAX_INSTANCES="${MAX_INSTANCES:-1}"
  if [[ "${MAX_INSTANCES}" != "1" ]]; then
    echo "ERROR: ephemeral demo mode requires MAX_INSTANCES=1." >&2
    exit 1
  fi
else
  MAX_INSTANCES="${MAX_INSTANCES:-10}"
fi

required_vars=(
  RUN_SERVICE_ACCOUNT
  OPENAI_API_KEY_SECRET_REF
  JWT_SECRET_SECRET_REF
  ADMIN_ID_SECRET_REF
  ADMIN_PASSWORD_SECRET_REF
  ADMIN_CONFIG_VERSION
)

if [[ "${EPHEMERAL_DEMO}" == "false" ]]; then
  required_vars+=(CLOUD_SQL_INSTANCE DATABASE_URL_SECRET_REF)
fi

for var in "${required_vars[@]}"; do
  if [[ -z "${!var:-}" ]]; then
    echo "ERROR: export ${var} before deploying." >&2
    exit 1
  fi
done

secret_ref_vars=(
  OPENAI_API_KEY_SECRET_REF
  JWT_SECRET_SECRET_REF
  ADMIN_ID_SECRET_REF
  ADMIN_PASSWORD_SECRET_REF
)
if [[ "${EPHEMERAL_DEMO}" == "false" ]]; then
  secret_ref_vars+=(DATABASE_URL_SECRET_REF)
fi

for var in "${secret_ref_vars[@]}"; do
  if [[ ! "${!var}" =~ :[1-9][0-9]*$ ]]; then
    echo "ERROR: ${var} must end in a pinned numeric version such as ':1'." >&2
    exit 1
  fi
done

if [[ ! "${ADMIN_CONFIG_VERSION}" =~ ^[1-9][0-9]*$ ]]; then
  echo "ERROR: ADMIN_CONFIG_VERSION must be a positive integer." >&2
  exit 1
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

SECRETS="OPENAI_API_KEY=${OPENAI_API_KEY_SECRET_REF}"
SECRETS="${SECRETS},JWT_SECRET=${JWT_SECRET_SECRET_REF}"
SECRETS="${SECRETS},ADMIN_ID=${ADMIN_ID_SECRET_REF}"
SECRETS="${SECRETS},ADMIN_PASSWORD=${ADMIN_PASSWORD_SECRET_REF}"

database_args=()
if [[ "${EPHEMERAL_DEMO}" == "true" ]]; then
  DATABASE_ENV="ALLOW_EPHEMERAL_SQLITE=true,EPHEMERAL_SQLITE_PATH=/tmp/agrisage-demo.db"
  echo "Deploying disposable single-instance demo '${SERVICE}' in ${REGION} ..."
else
  SECRETS="DATABASE_URL=${DATABASE_URL_SECRET_REF},${SECRETS}"
  DATABASE_ENV="ALLOW_EPHEMERAL_SQLITE=false"
  database_args=(--set-cloudsql-instances "${CLOUD_SQL_INSTANCE}")
  echo "Deploying persistent service '${SERVICE}' in ${REGION} ..."
fi

gcloud run deploy "${SERVICE}" \
  --source . \
  --region "${REGION}" \
  --platform managed \
  --allow-unauthenticated \
  --service-account "${RUN_SERVICE_ACCOUNT}" \
  "${database_args[@]}" \
  --set-secrets "${SECRETS}" \
  --set-env-vars "ADMIN_CONFIG_VERSION=${ADMIN_CONFIG_VERSION},${DATABASE_ENV}" \
  --execution-environment gen2 \
  --memory 2Gi \
  --cpu 2 \
  --timeout 300 \
  --concurrency 8 \
  --max-instances "${MAX_INSTANCES}"

echo
echo "Done. Service URL:"
gcloud run services describe "${SERVICE}" --region "${REGION}" \
  --format "value(status.url)"
