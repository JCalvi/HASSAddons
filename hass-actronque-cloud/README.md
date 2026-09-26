# Actron QUE Cloud

Cloud-based ActronAir QUE integration for Home Assistant.

This add-on controls an Actron QUE air conditioner through the Actron Cloud Service. It is the cloud-based counterpart to **Actron QUE Local**, which communicates directly with the QUE wall controller over the local network.

The add-on requires an MQTT broker, normally the Home Assistant Mosquitto add-on, with MQTT discovery enabled using the default `homeassistant` prefix.

Home Assistant Add-on Repository: https://github.com/JCalvi/HASSAddons

This add-on was originally forked from work by Mike McGuire:
https://blog.mikejmcguire.com/2021/02/11/actron-neo-and-home-assistant/

## Configuration

### MQTTBroker
Set this to `core-mosquitto` to use the Home Assistant Mosquitto MQTT add-on. Otherwise, specify the host or `host:port` of another MQTT broker.

### MQTTLogs
Set to `false` to reduce MQTT logging.

### MQTTTLS
Set to `true` to require TLS when connecting to the MQTT broker.

### PerZoneControls
If your Actron system has controllers in individual zones, enable this to create a climate entity for each zone.

### QueSerial
If multiple QUE systems are associated with the same Actron account, set this optional field to the serial number of the system this add-on instance should use. Leave blank to use all detected systems.

### SeparateHeatCoolTargets
Uses independent heating and cooling targets introduced in Home Assistant 2023.9 instead of a single target temperature.

### ShowBatterySensors
Controls whether battery level entities are created for zone temperature sensors when `PerZoneControls` is enabled.

### DeviceName
Custom device name used when authorising against the Actron cloud. Defaults to `HASSActronQue`.

## Events

### Command Failed
If a command is not accepted by the Actron cloud service, an MQTT message is sent after the configured retries are exhausted. The event is published to:

`actronqueXXXX/lastfailedcommand`

where `XXXX` is the QUE serial number.

## Cloud vs Local

Use **Actron QUE Cloud** when you want to retain cloud-based control through Actron's service.

Use **Actron QUE Local** when you want direct local WallLink control without depending on the Actron cloud service.
