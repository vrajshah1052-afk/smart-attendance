@echo off
rem Open the backend, the frontend and a database console in their own Command Prompt windows.
start "SFA backend :8000" cmd /k call "%~dp0start-backend.cmd"
start "SFA frontend :5173" cmd /k call "%~dp0start-frontend.cmd"
start "SFA database" cmd /k call "%~dp0db-console.cmd"
echo Backend:  http://localhost:8000/docs
echo Frontend: http://localhost:5173   (ready in about 10 seconds)
echo Database: tables + faces printed in the "SFA database" window, MySQL prompt left open there
