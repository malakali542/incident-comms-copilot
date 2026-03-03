#!/usr/bin/env python3
"""
Incident Communications Copilot – Entry Point

Usage:
    streamlit run main.py
"""
from app.ui_streamlit import run_app

if __name__ == "__main__":
    run_app()
else:
    # Streamlit imports the module rather than running __main__
    run_app()
