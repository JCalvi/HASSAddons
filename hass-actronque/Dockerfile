FROM mcr.microsoft.com/dotnet/aspnet:9.0-alpine AS base
RUN apk add --update --no-cache icu-libs tzdata && rm -rf /var/cache/apk/*

ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=false
WORKDIR /app

FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:9.0-alpine AS build
ARG TARGETARCH
WORKDIR /src
COPY hass-actronque/hass-actronque.csproj hass-actronque/
RUN dotnet restore hass-actronque/hass-actronque.csproj -a $TARGETARCH
COPY . .
WORKDIR /src/hass-actronque
RUN dotnet build  hass-actronque.csproj -c Release -o /app -a $TARGETARCH 

FROM build AS publish
RUN dotnet publish hass-actronque.csproj -c Release -o /app -a $TARGETARCH 

FROM base AS final
WORKDIR /app
COPY --from=publish /app .

#RUN apk add --no-cache icu-libs
ENV ASPNETCORE_HTTP_PORTS=80
ENTRYPOINT ["dotnet", "hass-actronque.dll"]
