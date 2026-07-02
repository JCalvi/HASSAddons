rem https://github.com/dotnet/dotnet-docker/blob/main/README.aspnet.md#full-tag-listing
@echo off

set jcversion=2026.6.21

:: 1. If the symlink already exists, jump straight to the build logic to avoid UAC popups
if exist "%USERPROFILE%\.docker\cli-plugins" (
    goto :start_build
)

:: 2. If symlink is missing, check for Administrative privileges to create it
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo Symlink missing. Requesting administrative privileges...
    powershell -Command "Start-Process '%~f0' -Verb RunAs"
    exit /b
)

:: 3. Clear old physical directory remnants if they exist before creating the symlink
if exist "%USERPROFILE%\.docker\cli-plugins" if not exist "%USERPROFILE%\.docker\cli-plugins\" (
    del /f /q "%USERPROFILE%\.docker\cli-plugins"
)
if exist "%USERPROFILE%\.docker\cli-plugins\" (
    rmdir /s /q "%USERPROFILE%\.docker\cli-plugins"
)

:: Ensure the parent .docker directory exists
if not exist "%USERPROFILE%\.docker" (
    mkdir "%USERPROFILE%\.docker"
)

:: Create the directory symlink
echo Creating Docker CLI plugins directory symlink...
mklink /D "%USERPROFILE%\.docker\cli-plugins" "C:\Program Files\Docker\Docker\resources\cli-plugins"


:start_build
cd /d "%~dp0\hass-networkexplorer"

PowerShell -Command "& {(Get-Content .\config.yaml) -replace 'version: .*', 'version: %jcversion%' | Set-Content .\config.yaml}"

docker buildx build ^
  --platform linux/amd64 ^
  --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest ^
  -t jcrfc/hass-networkexplorer-amd64:latest ^
  -t jcrfc/hass-networkexplorer-amd64:%jcversion% ^
  --push ^
  .

if errorlevel 1 goto fail

docker buildx build ^
  --platform linux/arm64 ^
  --build-arg BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest ^
  -t jcrfc/hass-networkexplorer-aarch64:latest ^
  -t jcrfc/hass-networkexplorer-aarch64:%jcversion% ^
  --push ^
  .

if errorlevel 1 goto fail

echo Build complete.
pause
exit /b 0

:fail
echo Build failed.
pause
exit /b 1
