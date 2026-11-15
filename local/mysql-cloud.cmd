@echo off
rem MySQL prompt on the Aiven database behind the deployed site (TLS, credentials
rem from ..\.env.cloud). Extra arguments pass through:
rem   mysql-cloud.cmd -t -e "SELECT prn, full_name FROM students"
setlocal enabledelayedexpansion
set "MYSQL_EXE=C:\Program Files\MySQL\MySQL Server 9.7\bin\mysql.exe"
for /f "usebackq tokens=1,* delims==" %%A in ("%~dp0..\.env.cloud") do (
  if "%%A"=="MYSQL_URI" set "URI=%%B"
)
for /f "tokens=1,2,3,4 delims=:@/" %%A in ("!URI:mysql//=!") do (
  set "DB_USER=%%B"
  set "MYSQL_PWD=%%C"
  set "DB_HOST=%%D"
)
for /f "tokens=2 delims=@" %%A in ("!URI!") do for /f "tokens=1,2 delims=:/" %%B in ("%%A") do (
  set "DB_HOST=%%B"
  set "DB_PORT=%%C"
)
"%MYSQL_EXE%" -u!DB_USER! -h!DB_HOST! -P!DB_PORT! --ssl-mode=REQUIRED --default-character-set=utf8mb4 attendance_db %*
