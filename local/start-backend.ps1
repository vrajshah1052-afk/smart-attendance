# Run the FastAPI backend natively on Windows (no Docker).
# Secrets come from ..\.env; the variables below override its Docker-only values
# (uvicorn --env-file never overrides variables that are already set).
$ErrorActionPreference = 'Stop'
Set-Location (Join-Path (Split-Path -Parent $PSScriptRoot) 'backend')

$env:MYSQL_HOST = '127.0.0.1'
$env:MYSQL_PORT = '3306'
$env:MYSQL_DATABASE = 'attendance_db'
$env:MONGO_URI = 'mongodb://127.0.0.1:27017'  # local MongoDB service runs without auth
$env:MONGO_DB = 'attendance_logs'
$env:DATA_DIR = './data'
$env:INSIGHTFACE_ROOT = './models'
# buffalo_l ONNX models on onnxruntime (models\models\buffalo_l\*.onnx); the insightface
# package itself needs the MSVC C++ build tools on Windows. ArcFace thresholds come from ..\.env.
$env:FACE_ENGINE = 'arcface_onnx'
$env:EMAIL_ENABLED = 'false'       # no Mailpit container
$env:FRONTEND_URL = 'http://localhost:5173'
$env:PYTHONUTF8 = '1'

& .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --env-file ..\.env
