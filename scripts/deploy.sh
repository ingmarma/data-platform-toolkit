#!/bin/bash
# ============================================================
# Data Platform Toolkit — Deploy Script
# ============================================================
# Usage:
#   ./scripts/deploy.sh                    # Deploy to dev
#   ./scripts/deploy.sh staging            # Deploy to staging
#   ./scripts/deploy.sh prod us-east-1     # Deploy to prod in us-east-1
# ============================================================

set -euo pipefail

ENVIRONMENT="${1:-dev}"
REGION="${2:-us-east-1}"
STACK_NAME="data-platform-toolkit-${ENVIRONMENT}"
DATA_BUCKET="${STACK_NAME}-data"
RESULTS_BUCKET="${STACK_NAME}-results"

echo "╔══════════════════════════════════════════╗"
echo "║   Data Platform Toolkit — Deploy         ║"
echo "╠══════════════════════════════════════════╣"
echo "║  Environment: ${ENVIRONMENT}"
echo "║  Region:      ${REGION}"
echo "║  Stack:       ${STACK_NAME}"
echo "╚══════════════════════════════════════════╝"
echo ""

# Check prerequisites
command -v sam >/dev/null 2>&1 || { echo "❌ AWS SAM CLI required. Install: pip install aws-sam-cli"; exit 1; }
command -v aws >/dev/null 2>&1 || { echo "❌ AWS CLI required. Install: pip install awscli"; exit 1; }

# Verify AWS credentials
echo "→ Verifying AWS credentials..."
aws sts get-caller-identity --region "$REGION" > /dev/null 2>&1 || {
    echo "❌ AWS credentials not configured. Run: aws configure"
    exit 1
}

echo "→ Building..."
sam build \
    --template-file infra/template.yaml \
    --build-dir .aws-sam/build \
    --region "$REGION"

echo ""
echo "→ Deploying to ${ENVIRONMENT}..."
sam deploy \
    --template-file .aws-sam/build/template.yaml \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND \
    --parameter-overrides \
        "Environment=${ENVIRONMENT}" \
        "DataBucket=${DATA_BUCKET}" \
        "ResultsBucket=${RESULTS_BUCKET}" \
    --no-confirm-changeset \
    --no-fail-on-empty-changeset

echo ""
echo "→ Deployment outputs:"
aws cloudformation describe-stacks \
    --stack-name "$STACK_NAME" \
    --region "$REGION" \
    --query "Stacks[0].Outputs" \
    --output table

echo ""
echo "✅ Deployed successfully to ${ENVIRONMENT}!"
