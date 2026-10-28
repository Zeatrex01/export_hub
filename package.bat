@echo off
REM Package Export Hub into a Blender-installable zip. The work is done by package.py (Python 3), which writes the
REM archive with forward slashes so it installs on Windows, macOS and Linux alike.
where py >nul 2>nul
if %errorlevel%==0 (py -3 "%~dp0package.py") else (python "%~dp0package.py")
exit /b %errorlevel%
