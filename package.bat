@echo off
REM ---------------------------------------------------------------------------
REM Package Export Hub into a Blender-installable zip.
REM
REM The file list below is a WHITELIST on purpose. A blacklist would quietly
REM start shipping every new AI doc, board file or scratch note that lands in
REM this folder; a whitelist can only ship what is named here.
REM
REM Blender needs the add-on package folder at the root of the archive, so the
REM files are staged into build\export_hub\ first and the folder is zipped --
REM zipping the loose .py files would produce an archive Blender refuses.
REM ---------------------------------------------------------------------------
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "OUT=%ROOT%build"
set "STAGE=%OUT%\export_hub"

REM Files that make up the add-on. Add here when a new module joins the package.
set "FILES=__init__.py config.py operators.py properties.py templates.py ui.py"
REM Shipped only if present.
set "OPTIONAL=README.md LICENSE LICENSE.txt"

echo.
echo  Packaging Export Hub
echo  --------------------

REM --- version straight from bl_info, so the zip name can never drift from it
for /f "usebackq delims=" %%v in (`powershell -NoProfile -Command ^
  "$m=[regex]::Match((Get-Content -Raw '%ROOT%__init__.py'),'\"version\"\s*:\s*\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)\)'); if($m.Success){'{0}.{1}.{2}' -f $m.Groups[1].Value,$m.Groups[2].Value,$m.Groups[3].Value}else{'unknown'}"`) do set "VERSION=%%v"

if "%VERSION%"=="unknown" (
    echo  ERROR: could not read the version tuple from __init__.py
    exit /b 1
)
echo  Version: %VERSION%

set "ZIP=%OUT%\export_hub-%VERSION%.zip"

REM --- clean previous build so nothing stale survives into the archive
if exist "%STAGE%" rmdir /s /q "%STAGE%"
if exist "%ZIP%" del /q "%ZIP%"
mkdir "%STAGE%" 2>nul

REM --- required files: a missing one is a build failure, not a warning
for %%f in (%FILES%) do (
    if not exist "%ROOT%%%f" (
        echo  ERROR: required file missing: %%f
        rmdir /s /q "%STAGE%"
        exit /b 1
    )
    copy /y "%ROOT%%%f" "%STAGE%\" >nul
    echo    + %%f
)

for %%f in (%OPTIONAL%) do (
    if exist "%ROOT%%%f" (
        copy /y "%ROOT%%%f" "%STAGE%\" >nul
        echo    + %%f
    )
)

REM --- zip the staged folder, not its contents, so export_hub\ is the archive root
powershell -NoProfile -Command ^
  "Compress-Archive -Path '%STAGE%' -DestinationPath '%ZIP%' -Force"
if errorlevel 1 (
    echo  ERROR: Compress-Archive failed
    exit /b 1
)

rmdir /s /q "%STAGE%"

echo.
echo  Archive contents:
powershell -NoProfile -Command ^
  "Add-Type -AssemblyName System.IO.Compression.FileSystem; $z=[IO.Compression.ZipFile]::OpenRead('%ZIP%'); $z.Entries | ForEach-Object { '    ' + $_.FullName }; $z.Dispose()"

echo.
echo  Done: %ZIP%
echo  Install in Blender via Edit ^> Preferences ^> Add-ons ^> Install...
echo.
endlocal
