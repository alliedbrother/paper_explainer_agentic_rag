#!/usr/bin/env python3
"""Run the FastAPI application."""

import sys
import os

# Add parent directory to path so imports work correctly
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("final_app.main:app", host="0.0.0.0", port=8000, reload=True)
