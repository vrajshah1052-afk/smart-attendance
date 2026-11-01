@echo off
rem Print the tables and enrolled faces, then leave a MySQL prompt open for queries.
call "%~dp0show-data.cmd"
echo.
echo MySQL prompt on attendance_db - type  exit  to leave. Try:  SELECT * FROM students LIMIT 5;
call "%~dp0mysql-shell.cmd"
