cd .\hass-actronque

docker build -t jcrfc/hass-actronque-aarch64:latest -t jcrfc/hass-actronque-aarch64:2025.1.0 . --platform linux/arm64
docker push jcrfc/hass-actronque-aarch64:latest
docker push jcrfc/hass-actronque-aarch64:2025.1.0

docker build -t jcrfc/hass-actronque-amd64:latest -t jcrfc/hass-actronque-amd64:2025.1.0 . --platform linux/amd64
docker push jcrfc/hass-actronque-amd64:latest
docker push jcrfc/hass-actronque-amd64:2025.1.0

docker build -t jcrfc/hass-actronque-armv7:latest -t jcrfc/hass-actronque-armv7:2025.1.0 . --platform linux/arm/v7
docker push jcrfc/hass-actronque-armv7:latest
docker push jcrfc/hass-actronque-armv7:2025.1.0

pause


rem docker tag jcrfc/hass-actronque-aarch64 jcrfc/hass-actronque-aarch64
rem docker tag jcrfc/hass-actronque-amd64 jcrfc/hass-actronque-amd64
rem docker tag jcrfc/hass-actronque-armv7 jcrfc/hass-actronque-armv7