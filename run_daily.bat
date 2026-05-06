@echo off
REM Windows Task Scheduler entry — invoked daily at 08:30 MY time.
cd /d "%~dp0"
py run_daily.py
exit /b %ERRORLEVEL%
