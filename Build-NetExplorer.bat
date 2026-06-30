rem https://github.com/dotnet/dotnet-docker/blob/main/README.aspnet.md#full-tag-listing
cd .\hass-networkexplorer

set jcversion=2026.6.04

Powershell -Command "& {(Get-Content .\config.yaml) -replace 'version: .*', 'version: %jcversion%' | Set-Content .\config.yaml}"

docker build ^
  --build-arg BUILD_FROM=ghcr.io/home-assistant/amd64-base:latest ^
  -t jcrfc/hass-networkexplorer-amd64:latest ^
  -t jcrfc/hass-networkexplorer-amd64:%jcversion% ^
  . --platform linux/amd64

if errorlevel 1 goto fail

docker push jcrfc/hass-networkexplorer-amd64:latest
docker push jcrfc/hass-networkexplorer-amd64:%jcversion%

docker build ^
  --build-arg BUILD_FROM=ghcr.io/home-assistant/aarch64-base:latest ^
  -t jcrfc/hass-networkexplorer-aarch64:latest ^
  -t jcrfc/hass-networkexplorer-aarch64:%jcversion% ^
  . --platform linux/arm64

if errorlevel 1 goto fail

docker push jcrfc/hass-networkexplorer-aarch64:latest
docker push jcrfc/hass-networkexplorer-aarch64:%jcversion%

pause
exit /b 0

:fail
echo Build failed. Not pushing.
pause
exit /b 1