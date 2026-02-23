#!/bin/bash
# Rolling Update Script for EC2 Instances
# Performs zero-downtime deployment by deregistering from ALB, updating, and re-registering
#
# Prerequisites:
# - AWS CLI configured with appropriate IAM permissions
# - Instance must be registered with the target group
#
# Usage: sudo ./rolling-update.sh

set -euo pipefail

# Configuration
APP_DIR="/opt/ragapp"
APP_USER="ragapp"
TARGET_GROUP_ARN="${TARGET_GROUP_ARN:-}"
AWS_REGION="${AWS_REGION:-us-east-1}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $(date '+%Y-%m-%d %H:%M:%S') $1"; }

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (sudo)"
    exit 1
fi

# Get instance ID from metadata
INSTANCE_ID=$(curl -s http://169.254.169.254/latest/meta-data/instance-id)
if [[ -z "$INSTANCE_ID" ]]; then
    log_error "Failed to get instance ID from metadata service"
    exit 1
fi

log_info "Starting rolling update for instance: $INSTANCE_ID"

# =============================================================================
# Step 1: Deregister from ALB Target Group (if configured)
# =============================================================================
if [[ -n "$TARGET_GROUP_ARN" ]]; then
    log_info "Deregistering from target group..."

    aws elbv2 deregister-targets \
        --target-group-arn "$TARGET_GROUP_ARN" \
        --targets Id="$INSTANCE_ID" \
        --region "$AWS_REGION"

    log_info "Waiting for connection draining (30s)..."
    sleep 30

    # Wait until fully deregistered
    while true; do
        STATUS=$(aws elbv2 describe-target-health \
            --target-group-arn "$TARGET_GROUP_ARN" \
            --targets Id="$INSTANCE_ID" \
            --region "$AWS_REGION" \
            --query 'TargetHealthDescriptions[0].TargetHealth.State' \
            --output text 2>/dev/null || echo "draining")

        if [[ "$STATUS" == "draining" ]] || [[ "$STATUS" == "None" ]] || [[ -z "$STATUS" ]]; then
            log_info "Instance deregistered from target group"
            break
        fi

        log_info "Waiting for deregistration... (current status: $STATUS)"
        sleep 5
    done
else
    log_warn "TARGET_GROUP_ARN not set, skipping ALB deregistration"
fi

# =============================================================================
# Step 2: Stop Application
# =============================================================================
log_info "Stopping application service..."
systemctl stop ragapp || true

# =============================================================================
# Step 3: Pull Latest Code
# =============================================================================
log_info "Pulling latest code..."

cd "$APP_DIR/app"
git fetch --all
git reset --hard origin/main  # or your deployment branch

# =============================================================================
# Step 4: Update Python Dependencies
# =============================================================================
log_info "Updating Python dependencies..."

source "$APP_DIR/venv/bin/activate"
pip install --upgrade pip wheel
pip install -r requirements.txt --upgrade

# =============================================================================
# Step 5: Rebuild Frontend
# =============================================================================
log_info "Rebuilding frontend..."

cd "$APP_DIR/app/frontend"
npm ci
npm run build
cd "$APP_DIR/app"

# =============================================================================
# Step 6: Run Database Migrations (if any)
# =============================================================================
log_info "Checking for database migrations..."

# Export environment
export $(grep -v '^#' "$APP_DIR/.env" | xargs)

# Run any pending migrations
# Add your migration command here if using Alembic or similar
# alembic upgrade head

# =============================================================================
# Step 7: Update Configuration Files
# =============================================================================
log_info "Updating configuration files..."

# Update nginx config if changed
if ! diff -q "$APP_DIR/app/final_app/deploy/nginx/ragapp.conf" /etc/nginx/conf.d/ragapp.conf > /dev/null 2>&1; then
    cp "$APP_DIR/app/final_app/deploy/nginx/ragapp.conf" /etc/nginx/conf.d/
    nginx -t && systemctl reload nginx
    log_info "nginx configuration updated"
fi

# Update systemd service if changed
if ! diff -q "$APP_DIR/app/final_app/deploy/systemd/ragapp.service" /etc/systemd/system/ragapp.service > /dev/null 2>&1; then
    cp "$APP_DIR/app/final_app/deploy/systemd/ragapp.service" /etc/systemd/system/
    systemctl daemon-reload
    log_info "systemd service updated"
fi

# =============================================================================
# Step 8: Fix Permissions
# =============================================================================
log_info "Fixing permissions..."

chown -R "$APP_USER:$APP_USER" "$APP_DIR/app"
chown -R "$APP_USER:$APP_USER" "$APP_DIR/logs"

# =============================================================================
# Step 9: Start Application
# =============================================================================
log_info "Starting application service..."
systemctl start ragapp

# Wait for application to be ready
log_info "Waiting for application to be ready..."
MAX_RETRIES=30
RETRY_COUNT=0

while [[ $RETRY_COUNT -lt $MAX_RETRIES ]]; do
    if curl -s http://localhost/health | grep -q '"status"'; then
        log_info "Application is ready"
        break
    fi

    RETRY_COUNT=$((RETRY_COUNT + 1))
    log_info "Waiting for application... (attempt $RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done

if [[ $RETRY_COUNT -eq $MAX_RETRIES ]]; then
    log_error "Application failed to start within timeout"
    log_error "Check logs: journalctl -u ragapp -n 100"
    exit 1
fi

# =============================================================================
# Step 10: Re-register with ALB Target Group
# =============================================================================
if [[ -n "$TARGET_GROUP_ARN" ]]; then
    log_info "Re-registering with target group..."

    aws elbv2 register-targets \
        --target-group-arn "$TARGET_GROUP_ARN" \
        --targets Id="$INSTANCE_ID" \
        --region "$AWS_REGION"

    # Wait for healthy status
    log_info "Waiting for target to become healthy..."
    while true; do
        STATUS=$(aws elbv2 describe-target-health \
            --target-group-arn "$TARGET_GROUP_ARN" \
            --targets Id="$INSTANCE_ID" \
            --region "$AWS_REGION" \
            --query 'TargetHealthDescriptions[0].TargetHealth.State' \
            --output text)

        if [[ "$STATUS" == "healthy" ]]; then
            log_info "Instance is healthy in target group"
            break
        fi

        log_info "Waiting for healthy status... (current: $STATUS)"
        sleep 5
    done
else
    log_warn "TARGET_GROUP_ARN not set, skipping ALB registration"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
log_info "=========================================="
log_info "Rolling update completed successfully!"
log_info "=========================================="
echo ""
echo "Instance: $INSTANCE_ID"
echo "Health: $(curl -s http://localhost/health | jq -r '.status' 2>/dev/null || echo 'unknown')"
echo ""
