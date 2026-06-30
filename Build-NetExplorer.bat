rem https://github.com/dotnet/dotnet-docker/blob/main/README.aspnet.md#full-tag-listing
@echo off
cd /d "%~dp0\hass-networkexplorer"

set jcversion=2026.6.10

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