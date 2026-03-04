#!/usr/bin/env python3
"""
Incident Communications Copilot – Entry Point

Streamlit UI:
    streamlit run main.py

REST API:
    uvicorn app.api:app --reload
    Docs available at http://localhost:8000/docs
"""
from app.ui_streamlit import run_app

if __name__ == "__main__":
    run_app()
else:
    # Streamlit imports the module rather than running __main__
    run_app()
