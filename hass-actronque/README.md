# hass-actronque
Actron Que Air Conditioner Add-On for Home Assistant.

This add-on for Home Assistant enables you to control an Actron QUE Air Conditioner. 

The add-on requires you to use the Mosquitto MQTT broker on your Home Assistant device, with authentication enabled and a valid credential supplied. You'll also need to ensure that MQTT discovery is enabled with the default prefix 'homeassistant' for HA to discover the climate device and zone switches.

Home Assistant AddOn Repository: https://github.com/JCalvi/HASSAddons

Note: This add-on has been forked from Mike McGuire:  (https://blog.mikejmcguire.com/2021/02/11/actron-neo-and-home-assistant/), refer to the change log for changes made.
(https://blog.mikejmcguire.com/2021/02/11/actron-neo-and-home-assistant/)

## Configuration
### MQTTBroker: string
Set this field to core-mosquitto to use the HA Mosquitto MQTT add-on. Otherwise, specify a host or host:port for an alternative MQTT server.

### MQTTLogs: true/false
Setting this option to false will reduce the amount of MQTT logging.

### MQTTTLS: true/false
Setting this option to true will force the MQTT client to attempt a TLS connection to the MQTT broker.

### PerZoneControls: true/false
If your Actron has controllers in each zone, setting this option to true will create an air conditioner controller in HA for each zone.

### QueSerial: string
If you have multiple AC units connected to your Que, you can add this optional configuration to specify the serial number of the AC you want the add-on to use. You can find the discovered serial numbers in the log for the add-on when the add-on is starting. If you leave this field blank, the add-on will add all detected AC units.

### SeparateHeatCoolTargets: bool
This option specifies if you wish to use the new independently set target heating and cooling temperature settings introduced in HA 2023.9. This disables the single temperature set option that may impact existing automations.

### ShowBatterySensors: bool
This option controls whether battery level sensors are created for zone temperature sensors. When set to true (default), battery sensors will be created for each zone sensor when PerZoneControls is enabled. Set to false to hide these sensors if you don't need to monitor battery levels.

### DeviceName: string
This option specifies a custom device name to authorise against the Actron cloud. If not specified this defaults to "HASSActronQue".

## Events
### Command Failed
In the event that a command you send (e.g. temperature change) is not accepted by the Que cloud service (e.g. it is unavailable), an MQTT message will be sent indicating the ID number of the failed command. This can then be captured to trigger a follow on automation. All commands will be retried generally around 3 times before the failure event will be sent. The event will be sent to the MQTT topic of actronqueXXXX/lastfailedcommand (XXXX is the serial number of the unit).