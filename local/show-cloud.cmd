@echo off
rem Same snapshot as show-data.cmd, but of the databases the DEPLOYED site uses
rem (Aiven MySQL + MongoDB Atlas, named in ..\.env.cloud). This is where a student
rem registered on the website shows up - the local databases never see them.
"%~dp0..\backend\.venv\Scripts\python.exe" -W ignore "%~dp0show_data.py" --env-file .env.cloud %*
