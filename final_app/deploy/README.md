# AWS Deployment Configuration

This directory contains all configuration files needed to deploy the Agentic RAG application to AWS.

## Directory Structure

```
deploy/
├── nginx/
│   └── ragapp.conf          # nginx reverse proxy configuration
├── systemd/
│   └── ragapp.service       # systemd service unit file
├── scripts/
│   ├── initial-deploy.sh    # First-time deployment script
│   └── rolling-update.sh    # Zero-downtime update script
├── env.production.template  # Environment variables template
└── README.md               # This file
```

## Quick Start

### Prerequisites

1. **AWS Resources Created:**
   - VPC with public/private subnets
   - RDS PostgreSQL instance
   - ElastiCache Redis cluster
   - Application Load Balancer with target group
   - EC2 instances (c6i.2xlarge recommended)
   - Secrets in AWS Secrets Manager

2. **Secrets Manager Structure:**
   Create a secret named `ragapp/production` with:
   ```json
   {
     "POSTGRES_PASSWORD": "your-db-password",
     "OPENAI_API_KEY": "sk-...",
     "COHERE_API_KEY": "...",
     "QDRANT_API_KEY": "...",
     "QDRANT_URL": "https://your-cluster.qdrant.io"
   }
   ```

### Initial Deployment

SSH into each EC2 instance and run:

```bash
# Download and run the initial deployment script
curl -O https://raw.githubusercontent.com/<your-repo>/main/final_app/deploy/scripts/initial-deploy.sh
chmod +x initial-deploy.sh
sudo ./initial-deploy.sh https://github.com/<your-repo>.git
```

After the script completes, update the environment file with your RDS and ElastiCache endpoints:

```bash
sudo nano /opt/ragapp/.env
# Update POSTGRES_HOST and REDIS_HOST

sudo systemctl restart ragapp
```

### Rolling Updates

For zero-downtime deployments:

```bash
# Set the target group ARN
export TARGET_GROUP_ARN="arn:aws:elasticloadbalancing:us-east-1:..."
export AWS_REGION="us-east-1"

# Run the rolling update
sudo -E ./rolling-update.sh
```

## Configuration Details

### nginx (`ragapp.conf`)

- Reverse proxy to uvicorn on port 8000
- SSE streaming support (proxy_buffering off, 300s timeout)
- Static file serving for React frontend
- Gzip compression enabled
- Security headers configured

**Install:**
```bash
sudo cp nginx/ragapp.conf /etc/nginx/conf.d/
sudo nginx -t && sudo systemctl reload nginx
```

### systemd (`ragapp.service`)

- Runs uvicorn with 4 workers
- Uses uvloop and httptools for performance
- Graceful shutdown with 30s timeout
- Security hardening enabled
- Logs to `/opt/ragapp/logs/uvicorn.log`

**Install:**
```bash
sudo cp systemd/ragapp.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ragapp
```

### Environment Variables (`env.production.template`)

Copy to `/opt/ragapp/.env` and replace placeholders:

```bash
sudo cp env.production.template /opt/ragapp/.env
sudo chmod 600 /opt/ragapp/.env
sudo chown ragapp:ragapp /opt/ragapp/.env
```

## Monitoring

### Check Service Status
```bash
sudo systemctl status ragapp nginx
```

### View Logs
```bash
# Application logs
sudo journalctl -u ragapp -f

# nginx access logs
sudo tail -f /var/log/nginx/ragapp_access.log

# nginx error logs
sudo tail -f /var/log/nginx/ragapp_error.log
```

### Health Check
```bash
curl http://localhost/health | jq
```

## Troubleshooting

### Application won't start
```bash
# Check for configuration errors
sudo journalctl -u ragapp -n 50

# Verify environment file
sudo cat /opt/ragapp/.env

# Test Python environment
sudo -u ragapp /opt/ragapp/venv/bin/python -c "from final_app.config import get_settings; print(get_settings())"
```

### nginx returns 502
```bash
# Check if uvicorn is running
sudo systemctl status ragapp

# Check uvicorn is listening
sudo ss -tlnp | grep 8000
```

### Database connection issues
```bash
# Test PostgreSQL connectivity
sudo -u ragapp /opt/ragapp/venv/bin/python -c "
from final_app.database import engine
import asyncio
async def test():
    async with engine.begin() as conn:
        result = await conn.execute('SELECT 1')
        print('Database connected!')
asyncio.run(test())
"
```

### Redis connection issues
```bash
# Test Redis connectivity
redis-cli -h <redis-host> -p 6379 PING
```
