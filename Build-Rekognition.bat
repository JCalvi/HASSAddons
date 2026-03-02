rem https://github.com/dotnet/dotnet-docker/blob/main/README.aspnet.md#full-tag-listing
cd .\rekognition_bridge

set jcversion=2026.3.1

Powershell -Command "& {(Get-Content .\config.json) -replace '\d{4}.\d+.\d+', '%jcversion%' | Set-Content  .\config.json}" 

rem echo %date% > .\hass-actronque\Resources\BuildDate.txt

docker build -t jcrfc/ha-rekognition-amd64:latest -t jcrfc/ha-rekognition-amd64:%jcversion% . --platform linux/amd64
docker push jcrfc/ha-rekognition-amd64:latest
docker push jcrfc/ha-rekognition-amd64:%jcversion%

docker build -t jcrfc/ha-rekognition-aarch64:latest -t jcrfc/ha-rekognition-aarch64:%jcversion% . --platform linux/arm64
docker push jcrfc/ha-rekognition-aarch64:latest
docker push jcrfc/ha-rekognition-aarch64:%jcversion%

pause