@echo off
rem Print a snapshot of the MySQL and MongoDB data (row counts + latest rows).
"%~dp0..\backend\.venv\Scripts\python.exe" -W ignore "%~dp0show_data.py" %*
