@echo off
rem Open the MySQL client on attendance_db as the DBA user from ..\.env.
rem Extra arguments are passed through:  mysql-shell.cmd -e "SELECT * FROM students"
setlocal
set "MYSQL_EXE=C:\Program Files\MySQL\MySQL Server 9.7\bin\mysql.exe"
for /f "usebackq tokens=1,* delims==" %%A in ("%~dp0..\.env") do (
  if "%%A"=="MYSQL_ADMIN_USER" set "DB_USER=%%B"
  if "%%A"=="MYSQL_ADMIN_PASSWORD" set "MYSQL_PWD=%%B"
)
"%MYSQL_EXE%" -u%DB_USER% -h127.0.0.1 -P3306 --default-character-set=utf8mb4 attendance_db %*
