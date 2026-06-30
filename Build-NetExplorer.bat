rem https://github.com/dotnet/dotnet-docker/blob/main/README.aspnet.md#full-tag-listing
cd .\hass-networkexplorer

set jcversion=2026.6.01

Powershell -Command "& {(Get-Content .\config.yaml) -replace 'version: .*', 'version: %jcversion%' | Set-Content .\config.yaml}"

docker build -t jcrfc/hass-networkexplorer-amd64:latest -t jcrfc/hass-networkexplorer-amd64:%jcversion% . --platform linux/amd64
docker push jcrfc/hass-networkexplorer-amd64:latest
docker push jcrfc/hass-networkexplorer-amd64:%jcversion%

pause

docker build -t jcrfc/hass-networkexplorer-aarch64:latest -t jcrfc/hass-networkexplorer-aarch64:%jcversion% . --platform linux/arm64
docker push jcrfc/hass-networkexplorer-aarch64:latest
docker push jcrfc/hass-networkexplorer-aarch64:%jcversion%

pause