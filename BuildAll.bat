rem https://github.com/dotnet/dotnet-docker/blob/main/README.aspnet.md#full-tag-listing
cd .\hass-actronque

set jcversion=2025.3.1

echo %date% > .\hass-actronque\Resources\BuildDate.txt

docker build -t jcrfc/hass-actronque-aarch64:latest -t jcrfc/hass-actronque-aarch64:%jcversion% . --platform linux/arm64
docker push jcrfc/hass-actronque-aarch64:latest
docker push jcrfc/hass-actronque-aarch64:%jcversion%

docker build -t jcrfc/hass-actronque-amd64:latest -t jcrfc/hass-actronque-amd64:%jcversion% . --platform linux/amd64
docker push jcrfc/hass-actronque-amd64:latest
docker push jcrfc/hass-actronque-amd64:%jcversion%


docker build -t jcrfc/hass-actronque-armv7:latest -t jcrfc/hass-actronque-armv7:%jcversion% . --platform linux/arm/v7
docker push jcrfc/hass-actronque-armv7:latest
docker push jcrfc/hass-actronque-armv7:%jcversion%

pause