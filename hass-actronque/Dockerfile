FROM mcr.microsoft.com/dotnet/runtime-deps:10.0-alpine AS base
RUN apk add --update --no-cache icu-libs tzdata && rm -rf /var/cache/apk/*

ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=false
WORKDIR /app

FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:10.0-alpine AS build
ARG TARGETARCH
WORKDIR /src
COPY hass-actronque/hass-actronque.csproj hass-actronque/
RUN dotnet restore hass-actronque/hass-actronque.csproj -a $TARGETARCH
COPY . .
WORKDIR /src/hass-actronque
RUN dotnet build  hass-actronque.csproj -c Release -o /app -a $TARGETARCH --warnaserror

FROM build AS publish
# Using TrimMode=partial for stability (standard for .NET 10 apps)
# Added DebuggerSupport=false to strip debug symbols and reduce RAM
RUN dotnet publish hass-actronque.csproj -c Release -o /app -a $TARGETARCH \
    --self-contained true \
    /p:PublishTrimmed=true \
    /p:TrimMode=partial \
    /p:PublishSingleFile=true \
    /p:DebuggerSupport=false \
    /p:EnableUnsafeBinaryFormatterSerialization=false

FROM base AS final
WORKDIR /app
COPY --from=publish /app .

# Disable Server GC (uses 1 heap per CPU core) in favour of Workstation GC (1 heap total)
ENV DOTNET_gcServer=0

# Limit the GC Heap size. (0x400000 = 64MB). 
# This prevents the app from growing indefinitely until the container is killed.
ENV DOTNET_GCHeapHardLimit=0x4000000

# More aggressive GC
ENV DOTNET_GCConserveMemory=9
ENV DOTNET_GCHighMemPercent=50

# Tell the GC to release virtual memory back to the OS immediately
ENV DOTNET_GCRetainVM=0

# Globalization Invariant mode saves ~20-30MB by not loading culture data but is required to load en-AU in this package.
ENV DOTNET_SYSTEM_GLOBALIZATION_INVARIANT=false

ENV ASPNETCORE_HTTP_PORTS=8080
ENTRYPOINT ["./hass-actronque"]
