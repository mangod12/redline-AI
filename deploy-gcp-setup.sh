#!/bin/bash
set -e

# ============================================================================
# Google Cloud Deployment Setup Script for Redline AI
# Run this on your local machine where gcloud CLI is installed and authenticated
# ============================================================================

PROJECT_ID="redlineai-490103"
REGION="us-central1"
SERVICE_ACCOUNT="github-deployer"
GITHUB_OWNER="mangod12"
GITHUB_REPO="redline-ai"

echo "🚀 Starting GCP deployment setup for $PROJECT_ID..."
echo ""

# ============================================================================
# STEP 1: Enable Required APIs
# ============================================================================
echo "📡 STEP 1: Enabling required GCP APIs..."
gcloud services enable compute.googleapis.com \
  artifactregistry.googleapis.com \
  cloudrun.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  serviceusage.googleapis.com \
  secretmanager.googleapis.com \
  --project=$PROJECT_ID
echo "✓ APIs enabled"
echo ""

# ============================================================================
# STEP 2: Create Artifact Registry
# ============================================================================
echo "📦 STEP 2: Creating Artifact Registry..."
gcloud artifacts repositories create redline-ai \
  --repository-format=docker \
  --location=$REGION \
  --project=$PROJECT_ID || echo "⚠️ Repository may already exist (continuing...)"
echo "✓ Artifact Registry created/verified"
echo ""

# ============================================================================
# STEP 3: Set Up Workload Identity Federation
# ============================================================================
echo "🔐 STEP 3: Setting up Workload Identity Federation..."

# Create WIF pool
echo "  Creating WIF pool..."
gcloud iam workload-identity-pools create "github-pool" \
  --project=$PROJECT_ID \
  --location=global \
  --display-name="GitHub Actions" || echo "⚠️ Pool may already exist (continuing...)"

# Create WIF provider
echo "  Creating WIF provider..."
gcloud iam workload-identity-pools providers create-oidc "github-provider" \
  --project=$PROJECT_ID \
  --location=global \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.aud=assertion.aud,attribute.repository=assertion.repository" \
  --issuer-uri="https://token.actions.githubusercontent.com" || echo "⚠️ Provider may already exist (continuing...)"

# Get WIF provider resource name
echo "  Fetching WIF provider resource name..."
WIF_PROVIDER=$(gcloud iam workload-identity-pools providers describe "github-provider" \
  --project=$PROJECT_ID \
  --location=global \
  --workload-identity-pool="github-pool" \
  --format="value(name)")
echo "✓ WIF configured"
echo "  WIF Provider: $WIF_PROVIDER"
echo ""

# ============================================================================
# STEP 4: Create Service Account for GitHub Actions
# ============================================================================
echo "👤 STEP 4: Creating service account for GitHub Actions..."

# Create service account
gcloud iam service-accounts create $SERVICE_ACCOUNT \
  --project=$PROJECT_ID \
  --display-name="GitHub Actions Deployer" || echo "⚠️ Service account may already exist (continuing...)"

SERVICE_ACCOUNT_EMAIL="${SERVICE_ACCOUNT}@${PROJECT_ID}.iam.gserviceaccount.com"
echo "  Service Account: $SERVICE_ACCOUNT_EMAIL"

# Grant Cloud Run Admin access
echo "  Granting Cloud Run Admin role..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
  --role="roles/run.admin" \
  --condition=None || true

# Grant Artifact Registry Writer access
echo "  Granting Artifact Registry Writer role..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
  --role="roles/artifactregistry.writer" \
  --condition=None || true

# Grant Secret Manager Secret Accessor access
echo "  Granting Secret Manager Secret Accessor role..."
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:$SERVICE_ACCOUNT_EMAIL" \
  --role="roles/secretmanager.secretAccessor" \
  --condition=None || true

# Allow GitHub to impersonate this service account
echo "  Setting up Workload Identity binding for GitHub..."
gcloud iam service-accounts add-iam-policy-binding "$SERVICE_ACCOUNT_EMAIL" \
  --project=$PROJECT_ID \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/$PROJECT_ID/locations/global/workloadIdentityPools/github-pool/attribute.repository/${GITHUB_OWNER}/${GITHUB_REPO}" || true

echo "✓ Service account configured"
echo ""

# ============================================================================
# STEP 5: Create Secrets in GCP Secret Manager
# ============================================================================
echo "🔒 STEP 5: Creating secrets in GCP Secret Manager..."

# Generate a random secret key
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")

# Create or update secrets
echo "$SECRET_KEY" | gcloud secrets create SECRET_KEY --data-file=- --project=$PROJECT_ID 2>/dev/null || \
  echo "$SECRET_KEY" | gcloud secrets versions add SECRET_KEY --data-file=- --project=$PROJECT_ID

echo "postgres" | gcloud secrets create POSTGRES_PASSWORD --data-file=- --project=$PROJECT_ID 2>/dev/null || \
  echo "postgres" | gcloud secrets versions add POSTGRES_PASSWORD --data-file=- --project=$PROJECT_ID

echo "postgres" | gcloud secrets create POSTGRES_USER --data-file=- --project=$PROJECT_ID 2>/dev/null || \
  echo "postgres" | gcloud secrets versions add POSTGRES_USER --data-file=- --project=$PROJECT_ID

echo "cloudsql.c.$PROJECT_ID.internal" | gcloud secrets create POSTGRES_SERVER --data-file=- --project=$PROJECT_ID 2>/dev/null || \
  echo "cloudsql.c.$PROJECT_ID.internal" | gcloud secrets versions add POSTGRES_SERVER --data-file=- --project=$PROJECT_ID

echo "5432" | gcloud secrets create POSTGRES_PORT --data-file=- --project=$PROJECT_ID 2>/dev/null || \
  echo "5432" | gcloud secrets versions add POSTGRES_PORT --data-file=- --project=$PROJECT_ID

echo "redline_db" | gcloud secrets create POSTGRES_DB --data-file=- --project=$PROJECT_ID 2>/dev/null || \
  echo "redline_db" | gcloud secrets versions add POSTGRES_DB --data-file=- --project=$PROJECT_ID

echo "redis://localhost:6379" | gcloud secrets create REDIS_URL --data-file=- --project=$PROJECT_ID 2>/dev/null || \
  echo "redis://localhost:6379" | gcloud secrets versions add REDIS_URL --data-file=- --project=$PROJECT_ID

echo "✓ Secrets created"
echo ""

# ============================================================================
# STEP 6: Get Project Number (needed for GitHub secrets)
# ============================================================================
echo "📋 STEP 6: Gathering information for GitHub secrets..."
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format='value(projectNumber)')
echo ""
echo "================================================================"
echo "✅ GCP SETUP COMPLETE"
echo "================================================================"
echo ""
echo "Save these values - you'll need them to set GitHub Actions secrets:"
echo ""
echo "GCP_PROJECT_ID:"
echo "  $PROJECT_ID"
echo ""
echo "GCP_WORKLOAD_IDENTITY_PROVIDER:"
echo "  $WIF_PROVIDER"
echo ""
echo "GCP_SERVICE_ACCOUNT:"
echo "  $SERVICE_ACCOUNT_EMAIL"
echo ""
echo "================================================================"
echo ""
echo "Next: Set GitHub Actions secrets by running:"
echo ""
echo "  gh secret set GCP_PROJECT_ID --body '$PROJECT_ID' -R mangod12/redline-ai"
echo ""
echo "  gh secret set GCP_WORKLOAD_IDENTITY_PROVIDER --body '$WIF_PROVIDER' -R mangod12/redline-ai"
echo ""
echo "  gh secret set GCP_SERVICE_ACCOUNT --body '$SERVICE_ACCOUNT_EMAIL' -R mangod12/redline-ai"
echo ""
echo "Then trigger deployment with:"
echo ""
echo "  gh workflow run deploy-gcp.yml -R mangod12/redline-ai"
echo ""
echo "================================================================"
