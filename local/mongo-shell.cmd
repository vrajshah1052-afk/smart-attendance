@echo off
rem Open mongosh on attendance_logs (local MongoDB service, no auth).
rem Extra arguments are passed through:  mongo-shell.cmd --eval "db.face_embeddings.countDocuments()"
setlocal
set "MONGOSH="
for /f "delims=" %%P in ('where mongosh 2^>nul') do if not defined MONGOSH set "MONGOSH=%%P"
if not defined MONGOSH if exist "%LOCALAPPDATA%\Programs\mongosh\mongosh.exe" set "MONGOSH=%LOCALAPPDATA%\Programs\mongosh\mongosh.exe"
if not defined MONGOSH if exist "C:\Program Files\mongosh\mongosh.exe" set "MONGOSH=C:\Program Files\mongosh\mongosh.exe"
if not defined MONGOSH (
  echo mongosh not found. Install it with:  winget install MongoDB.Shell
  echo Meanwhile "%~dp0show-data.cmd" prints both databases.
  exit /b 1
)
"%MONGOSH%" "mongodb://127.0.0.1:27017/attendance_logs" %*
