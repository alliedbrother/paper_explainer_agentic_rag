#!/bin/bash

# Run script for Agentic RAG System

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}   Agentic RAG System - Launcher${NC}"
echo -e "${GREEN}========================================${NC}"

# Check if .env exists
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}No .env file found. Creating from .env.example...${NC}"
    if [ -f ".env.example" ]; then
        cp .env.example .env
        echo -e "${YELLOW}Please edit .env with your API keys before running.${NC}"
    fi
fi

# Function to run backend
run_backend() {
    echo -e "${GREEN}Starting FastAPI backend on http://localhost:8000${NC}"
    source venv/bin/activate 2>/dev/null || true
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload
}

# Function to run frontend
run_frontend() {
    echo -e "${GREEN}Starting React frontend on http://localhost:3000${NC}"
    cd frontend && npm run dev
}

# Function to install frontend dependencies
install_frontend() {
    echo -e "${BLUE}Installing frontend dependencies...${NC}"
    cd frontend && npm install
}

# Function to run both
run_all() {
    echo -e "${GREEN}Starting both backend and frontend...${NC}"

    # Start backend in background
    source venv/bin/activate 2>/dev/null || true
    uvicorn main:app --host 0.0.0.0 --port 8000 --reload &
    BACKEND_PID=$!

    sleep 2

    # Start frontend
    cd frontend && npm run dev &
    FRONTEND_PID=$!

    echo -e "${GREEN}Backend PID: $BACKEND_PID (http://localhost:8000)${NC}"
    echo -e "${GREEN}Frontend PID: $FRONTEND_PID (http://localhost:3000)${NC}"
    echo -e "${YELLOW}Press Ctrl+C to stop both servers${NC}"

    # Wait for interrupt
    trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null" EXIT
    wait
}

# Parse arguments
case "$1" in
    backend)
        run_backend
        ;;
    frontend)
        run_frontend
        ;;
    install)
        install_frontend
        ;;
    all|"")
        run_all
        ;;
    *)
        echo "Usage: $0 {backend|frontend|install|all}"
        echo "  backend  - Run FastAPI backend only"
        echo "  frontend - Run React frontend only"
        echo "  install  - Install frontend dependencies"
        echo "  all      - Run both (default)"
        exit 1
        ;;
esac
