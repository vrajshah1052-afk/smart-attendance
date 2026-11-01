@echo off
rem Start the FastAPI backend in this window (Ctrl+C to stop) -> http://localhost:8000/docs
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start-backend.ps1"
