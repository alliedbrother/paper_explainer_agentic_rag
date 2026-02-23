#!/bin/bash
# Initial Deployment Script for EC2 Instances
# Run this script on each EC2 instance after instance launch
#
# Prerequisites:
# - EC2 instance with Amazon Linux 2023
# - IAM role with Secrets Manager access
# - Security group allowing traffic from ALB
#
# Usage: sudo ./initial-deploy.sh <git-repo-url>

set -euo pipefail

# Configuration
APP_DIR="/opt/ragapp"
APP_USER="ragapp"
GIT_REPO="${1:-}"
SECRETS_ARN="ragapp/production"
AWS_REGION="us-east-1"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if running as root
if [[ $EUID -ne 0 ]]; then
    log_error "This script must be run as root (sudo)"
    exit 1
fi

if [[ -z "$GIT_REPO" ]]; then
    log_error "Usage: $0 <git-repo-url>"
    exit 1
fi

log_info "Starting initial deployment..."

# =============================================================================
# Step 1: System Updates and Dependencies
# =============================================================================
log_info "Installing system dependencies..."

dnf update -y
dnf install -y \
    python3.11 \
    python3.11-pip \
    python3.11-devel \
    nginx \
    git \
    poppler-utils \
    tesseract \
    tesseract-langpack-eng \
    file-libs \
    gcc \
    gcc-c++ \
    make

# Install Node.js 20.x for frontend build
log_info "Installing Node.js..."
curl -fsSL https://rpm.nodesource.com/setup_20.x | bash -
dnf install -y nodejs

# =============================================================================
# Step 2: Create Application User and Directories
# =============================================================================
log_info "Creating application user and directories..."

# Create app user if not exists
if ! id "$APP_USER" &>/dev/null; then
    useradd -r -s /bin/false "$APP_USER"
fi

# Create directory structure
mkdir -p "$APP_DIR"/{app,venv,logs,data/pdfs}

# Create Python virtual environment
log_info "Creating Python virtual environment..."
python3.11 -m venv "$APP_DIR/venv"

# =============================================================================
# Step 3: Clone Repository
# =============================================================================
log_info "Cloning application repository..."

if [[ -d "$APP_DIR/app/.git" ]]; then
    log_warn "Repository already exists, pulling latest..."
    cd "$APP_DIR/app"
    git pull
else
    git clone "$GIT_REPO" "$APP_DIR/app"
fi

cd "$APP_DIR/app"

# =============================================================================
# Step 4: Install Python Dependencies
# =============================================================================
log_info "Installing Python dependencies..."

source "$APP_DIR/venv/bin/activate"
pip install --upgrade pip wheel
pip install -r requirements.txt

# Install additional production dependencies
pip install uvloop httptools

# =============================================================================
# Step 5: Build Frontend
# =============================================================================
log_info "Building frontend..."

cd "$APP_DIR/app/frontend"
npm ci
npm run build
cd "$APP_DIR/app"

# =============================================================================
# Step 6: Retrieve Secrets from AWS Secrets Manager
# =============================================================================
log_info "Retrieving secrets from AWS Secrets Manager..."

# Fetch secrets and create .env file
SECRETS=$(aws secretsmanager get-secret-value \
    --secret-id "$SECRETS_ARN" \
    --region "$AWS_REGION" \
    --query SecretString \
    --output text)

# Parse secrets and create environment file
# Start with the template
cp "$APP_DIR/app/final_app/deploy/env.production.template" "$APP_DIR/.env"

# Replace placeholders with actual secrets
POSTGRES_PASSWORD=$(echo "$SECRETS" | jq -r '.POSTGRES_PASSWORD // empty')
OPENAI_API_KEY=$(echo "$SECRETS" | jq -r '.OPENAI_API_KEY // empty')
COHERE_API_KEY=$(echo "$SECRETS" | jq -r '.COHERE_API_KEY // empty')
QDRANT_API_KEY=$(echo "$SECRETS" | jq -r '.QDRANT_API_KEY // empty')
QDRANT_URL=$(echo "$SECRETS" | jq -r '.QDRANT_URL // empty')

# Update .env with actual values (you'll need to customize these for your RDS/ElastiCache endpoints)
sed -i "s|<from-secrets-manager>|${POSTGRES_PASSWORD}|g" "$APP_DIR/.env"
sed -i "s|OPENAI_API_KEY=<from-secrets-manager>|OPENAI_API_KEY=${OPENAI_API_KEY}|g" "$APP_DIR/.env"
sed -i "s|COHERE_API_KEY=<from-secrets-manager>|COHERE_API_KEY=${COHERE_API_KEY}|g" "$APP_DIR/.env"
sed -i "s|QDRANT_API_KEY=<from-secrets-manager>|QDRANT_API_KEY=${QDRANT_API_KEY}|g" "$APP_DIR/.env"
sed -i "s|QDRANT_URL=<https://your-cluster.qdrant.io>|QDRANT_URL=${QDRANT_URL}|g" "$APP_DIR/.env"

log_warn "IMPORTANT: Update POSTGRES_HOST and REDIS_HOST in $APP_DIR/.env with your RDS and ElastiCache endpoints"

# Secure the .env file
chmod 600 "$APP_DIR/.env"
chown "$APP_USER:$APP_USER" "$APP_DIR/.env"

# =============================================================================
# Step 7: Set Permissions
# =============================================================================
log_info "Setting file permissions..."

chown -R "$APP_USER:$APP_USER" "$APP_DIR"
chmod -R 755 "$APP_DIR/app"
chmod -R 700 "$APP_DIR/logs"

# =============================================================================
# Step 8: Configure nginx
# =============================================================================
log_info "Configuring nginx..."

cp "$APP_DIR/app/final_app/deploy/nginx/ragapp.conf" /etc/nginx/conf.d/
nginx -t

# =============================================================================
# Step 9: Configure systemd
# =============================================================================
log_info "Configuring systemd service..."

cp "$APP_DIR/app/final_app/deploy/systemd/ragapp.service" /etc/systemd/system/
systemctl daemon-reload

# =============================================================================
# Step 10: Initialize Database (Run only on first instance)
# =============================================================================
log_info "Checking if database initialization is needed..."

# Export environment for Python
export $(grep -v '^#' "$APP_DIR/.env" | xargs)

# Run database initialization
cd "$APP_DIR/app"
source "$APP_DIR/venv/bin/activate"
python -c "
from final_app.database import init_db
import asyncio
asyncio.run(init_db())
print('Database initialized successfully')
" || log_warn "Database may already be initialized or connection failed"

# =============================================================================
# Step 11: Start Services
# =============================================================================
log_info "Starting services..."

systemctl enable nginx ragapp
systemctl start ragapp
systemctl start nginx

# =============================================================================
# Step 12: Health Check
# =============================================================================
log_info "Running health check..."

sleep 5  # Wait for services to start

if curl -s http://localhost/health | grep -q "healthy"; then
    log_info "Health check passed!"
else
    log_warn "Health check returned non-healthy status"
    log_warn "Check logs: journalctl -u ragapp -f"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
log_info "=========================================="
log_info "Deployment completed successfully!"
log_info "=========================================="
echo ""
echo "Next steps:"
echo "  1. Update $APP_DIR/.env with correct RDS and ElastiCache endpoints"
echo "  2. Restart the service: sudo systemctl restart ragapp"
echo "  3. Check logs: sudo journalctl -u ragapp -f"
echo "  4. Test health: curl http://localhost/health"
echo ""
