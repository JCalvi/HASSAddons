FROM mcr.microsoft.com/dotnet/runtime-deps:9.0-alpine3.22 AS base
RUN apk add --update --no-cache icu-libs tzdata && rm -rf /var/cache/apk/*

ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=false
WORKDIR /app

FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:9.0-alpine3.22 AS build
ARG TARGETARCH
WORKDIR /src
COPY hass-actronque/hass-actronque.csproj hass-actronque/
RUN dotnet restore hass-actronque/hass-actronque.csproj -a $TARGETARCH
COPY . .
WORKDIR /src/hass-actronque
RUN dotnet build  hass-actronque.csproj -c Release -o /app -a $TARGETARCH 

FROM build AS publish
RUN dotnet publish hass-actronque.csproj -c Release -o /app -a $TARGETARCH --self-contained true /p:PublishTrimmed=true /p:TrimMode=partial /p:PublishSingleFile=true

FROM base AS final
WORKDIR /app
COPY --from=publish /app .

ENV ASPNETCORE_HTTP_PORTS=8080
ENTRYPOINT ["./hass-actronque"]
