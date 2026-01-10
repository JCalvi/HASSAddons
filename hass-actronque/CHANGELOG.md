# Changelog
All notable changes to this project will be documented in this file.

## [v2026.1.2] - 2026-01-10

### Added
- Added Options Setting
	- Constant Fan Mode

### Removed
- 

## Changed
- Added default entity id to new switches.
- Removed more of the unused events mode code.

## [v2026.1.1] - 2026-01-07

### Added
- Added Options Settings
	- Away Mode
	- Quiet Mode

### Removed
- arm7 Builds

## Changed
- Build with latest Alpine (3.22)


## [v2025.7.5] - 2025-07-23

### Added
- Polling now dynamically changes depending on circumstances.
	- 5 seconds if a command is active (In original MJM code).
	- 30 seconds if AC unit is on
	- 300 seconds if AC unit is off

### Removed
- Removed PollInterval from input config.

## Changed
- Reverted base images to Alpine 3.21 in case cause of instability issues.


## [v2025.7.4] - 2025-07-22

### Changed
- Returned to v2025.7.1 baseline to try and address stability issues.
- Removed Neo Code - hard coded to Que only.
- Removed unused variables


## [v2025.7.3] - 2025-07-22

### Changed
- Remove various logs


## [v2025.7.2] - 2025-07-18
Implement latest MJM changes below to sync with MJM v2025.7.2/1
### Added

- Added entities for Neo sensor/controller batteries.
- Added logic to ignore AC units that are offline for more than 20 hours (e.g. a que unit replaced with a neo).
- Upgraded .NET packages.

### Removed

- Removed per zone sensor configuration item. If sensors are detected, they will be registered and updated by MQTT.
- Removed system type configuration item. The add-on will now detect if each system is a Que or a Neo.
- Removed disable event based updates configuration item (added in 2025.7.0). If the events endpoint returns unauthorized, the add-on will switch automatically to full status polling.

### Changed

- Changed Base URLs to use the Neo endpoint for auth, events, and Neo commands, and the Que endpoint for Que commands.
- Fixed bug in custom device name.


## [v2025.7.1] - 2025-07-16

### Added

- Added an option to force Neo no event mode on QUE to address current cloud api issue.

### Changed
- Removed _iPollIntervalNeoNoEventsMode which was hard-coded to 30 sec, and made this equal to polling interval set in config. 
  This enables a user to reduce noeventsmode traffic which for a QUE is about 20kb per data collection, or set it below 30s if they want better response.
- Upgraded base images to Alpine 3.22


## [v2025.3.2] - 2025-03-29

### Added
Implement latest MJM changes below.
- Added additional logic to show compressor state per zone (when using Que per zone controls). Additional research by @DanielNagy.
- Added additional sensor entity for the air conditioner current temperature.
- Added configuration option to reduce MQTT logging.
- Added configuration option to reduce Que event logging.


## [v2025.3.1] - 2025-03-09

### Added
- Optional custom device name. This is what device name the add-on authorises against the Actron cloud as. Default is "HASSActronQue"



## [v2025.1.1] - 2025-01-22

### Changed
- Upgraded base images to Alpine 3.21
- Changed to self-contained-trimmed reducing size 50%
- Changed Web port to 8080 from 80 to comply with Default .NET8+
- Upgraded Microsoft.Extensions.Configuration.Json to Version 9.0.1
- Upgraded System.Text.Json to Version 9.0.1
- Package Updates from: https://www.nuget.org/packages


## [v2025.1.0] - 2025-01-05

### Changed

- First Build JC.
- Upgraded MQTT and JSON packages.
- Reduced a lot of logging not required for production.
- Changed Icon to QUE icon.
- Upgraded base images to .NET 9.
- Suppress Microsoft.AspNetCore warnings.
- Removed hard coded UseUrls 
  from webBuilder.UseStartup<ASPNETCoreStartup>().UseConfiguration(configuration).UseUrls($"http://*:80/");
  set instead from ENV variables in Dockerfile.
  
### Added
- Clean Filter Entity
- Time Since Filter Cleaned Entity

## [v2024.7.0] - 2024-07-19

### Changed

- Upgraded MQTT and JSON packages.

## [v2023.12.1] - 2023-12-19

### Added

- Added MQTT alert message/event when retried commands fail.

## [v2023.12.0] - 2023-12-17

### Added

- Added automatic retry when the Que gateway times out on new commands/changes. Any failed command should now be retried 2 - 3 times.

### Changed

- Upgraded base images to .NET 8.

## [v2023.11.3] - 2023-11-13

### Changed

- Fixed a bug causing the Control All Zones to not always be turned on upon temperature change.

## [v2023.11.2] - 2023-11-12

### Added

- Added entities to support the Control All Zones setting on the Actron Que.
- Sets Control All Zones to True automatically when the master unit temperature is adjusted.
 
### Removed

- Removing support for i386 and armhf architectures as they are no longer supported by Microsoft (.NET). The previous versions of the add-on will continue to work, however they will no longer receive updates.

## [v2023.11.1] - 2023-11-10

### Added

- Added a new configuration option to enable the new HVAC/Climate options in HA 2023.9 (setting the target heating and cooling temperatures independently).

### Changed

- Changed base images to Alpine from Debian to match the HA base images.

## [v2023.4.0] - 2023-04-30

### Changed

- Upgraded base images.

## [v2023.1.1] - 2023-01-09

### Changed

- Downgraded the base image used for Armv8 (aarch64), as the latest image failed randomly on Raspberry Pi devices.

## [v2023.1.0] - 2023-01-04

### Added

- Added support for multiple AC units controlled by a single Que controller.

### Changed

- The MQTT topics have been changed to accommodate multiple AC units.
- The device created in HA has been updated with additional AC specific information - this may impact device and entity identifiers as a result of now supporting multiple AC units.

## [v2022.10.3] - 2022-10-17

### Added

- Added logic to regenerate the pairing token and device identification files when the email address changes.
- Added logic to identify authentication issues when email addresses change.
- Added MQTT connection errors to the logs.

## [v2022.8.0] - 2022-08-09

### Added

- Added additional HA attributes to battery entities.
- Added battery entities to PerZoneControls (already in PerZoneSensors).

### Changed

- Fix for Neo Systems that don't generate Actron Events.

## [v2022.5.0] - 2022-05-30

### Changed

- Added additional logic to support non-contiguous zones.

## [v2022.2.3] - 2022-02-09

### Changed

- Rounded per zone temperature to one decimal place.
- Aligned per sensor temperature entities' units to climate entities.

## [v2022.2.2] - 2022-02-08

### Changed

- Fixed per sensor temperature entity being incorrectly shown as a percentage.

## [v2022.2.1] - 2022-02-07

### Added

- Added support for zones with multiple sensors.

### Changed

- Changed per zone battery to per sensor battery to better reflect the data model from Actron. Use the PerZoneSensors option to create the entities in HA.

### Removed

- Removed per zone humidity sensors - the zone sensors don't measure humidity, even though they sometimes report a value.

## [v2022.2.0] - 2022-02-01

### Changed

- Fix for Neo systems.
- Update to MQTT library.

## [v2022.1.4] - 2022-01-29

### Changed

- Fix for systems with less than 8 zones.

## [v2022.1.3] - 2022-01-28

### Changed

- Code efficiency updates.
- Reduction in MQTT updates - updating changed items rather than all items.

## [v2022.1.2] - 2022-01-27

### Added

- Added entities for room/zone humidity and battery.

## [v2022.1.1] - 2022-01-25

### Added

- Added entities for Coil Inlet, Fan PWM, Fan RPM.

## [v2022.1.0] - 2022-01-17

### Changed
- Check for missing outdoor unit.

## [v2021.12.2] - 2021-12-10

### Changed
- Fixed number conversion error for compressor capacity and compressor power.

## [v2021.12.1] - 2021-12-07

### Added
- Added logic to support Neo Air Conditioners that do not record change events. In this mode, the add-on will pull a full status update every 30 seconds as there aren't incremental updates available.

## [v2021.12.0] - 2021-12-02

### Changed
- Migrated from .NET 5.0 to .NET 6.0.
- Changed version numbering scheme.
- Added logic to support the bearer token request returning BadRequest instead of Unauthorised, so that after a set number of attempts, the add-on will regenerate the pairing token.

## [v0.30] - 2021-09-22

### Changed
- New entities for power, outdoor temperature and compressor capacity removed in Neo mode.

## [v0.29] - 2021-09-20

### Added
- Setting the AC to auto mode will now set the heating and cooling temperatures to the single desired temperature.

## [v0.28] - 2021-09-04

### Added
- The compressor power usage reading from the outdoor is now presented as an entity. This is an experimental entity until more data is gathered.

## [v0.27] - 2021-08-30

### Added
- The outside temperature reading from the Master Controller is now presented as an entity.
- The compressor capacity reading from the Master Controller is now presented as an entity.
- The zone position reading from each zone is now presented as an entity.

### Changed
- Zones that are off will now receive set temperature updates.

## [v0.26] - 2021-08-01

### Changed
- Decreased logging from .NET Framework.
- Updated humidity entity to better support HomeKit.

## [v0.25] - 2021-07-31

### Added
- The humidity reading from the Master Controller is now presented as an entity.

## [v0.24] - 2021-05-28

### Added
- Support for MQTT TLS (with associated configuration option).
- Support for MQTT port specification (through host:port notation).

### Changed
- Moved to .NET 5.0 host model.

## [v0.23] - 2021-02-14

### Added
- Support for fan continuous mode. If you change speed whilst in continuous mode, continuous mode will be preserved. 

## [v0.22] - 2021-02-13

### Changed
- Fixed a bug with temperature updates for the Neo system.

## [v0.21] - 2021-02-12

### Added
- Initial support for the Actron Neo module.
- New configuration item SystemType for specifying que or neo system types - defaulting to que for backward compatibility.

## [v0.20] - 2021-02-10

### Changed
- Updated add-on configuration based on schema changes from HA. This should remove the warning appearing in the supervisor logs.

## [v0.19] - 2020-12-17

### Changed
- Updated to .NET 5.0 Framework.
- Updated Device Registration MQTT information.

## [v0.18] - 2020-08-24

### Added
- MQTT entities will now appear linked to a single device under the MQTT integration.

### Changed
- The add-on now correctly displays all Que serial numbers when a user has multiple Que units on their account.
- Improved logging for errors from bad data returned by Que API (in circumstances where a user has an old Que unit on their account with no data).

## [v0.17] - 2020-02-08

First major release.
