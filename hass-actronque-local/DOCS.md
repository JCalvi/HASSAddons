# Actron QUE Local — Configuration

This app connects directly to the QUE master wall controller. It does not use the
Actron cloud.

The synthetic controller must already be paired with the QUE master.

For the current system:

- Master IP: `192.168.1.218`
- Master serial: `18A01392`
- Real secondary: `18A01391`
- Synthetic secondary: `FA000001`
- WallLink TCP port: `19296`
- Firmware: `1.456.1.598`

The default app configuration is already set to these values.

## Requirements

The Home Assistant MQTT service must be available. The app obtains the MQTT
connection details from Supervisor automatically; no broker username/password
needs to be entered in the app configuration.

## First start

1. Install and start the app.
2. Open its **Logs** tab.
3. A successful start should include messages similar to:

   - `MQTT connected`
   - `Connecting WallLink to 192.168.1.218:19296 as FA000001`
   - `WallLink accepted by master 18A01392`
   - `Initial Data_All received`
   - `WallLink online`

4. Home Assistant MQTT Discovery should create a device named
   **Actron QUE Home**.

## MQTT topics

Default prefix: `actronque_local`

- `actronque_local/status` — WallLink `online` / `offline`
- `actronque_local/bridge/status` — app MQTT status
- `actronque_local/raw/state` — complete current QUE state when enabled
- `actronque_local/event/change` — latest incoming WallLink Data_Change
- `actronque_local/quiet_mode/set` — command topic for Quiet Mode

## Safety

Version 0.1.0 only exposes a writable control that has already been verified on
the target QUE system: `UserAirconSettings.QuietMode`.

Other writable HVAC controls will be added only after their exact WallLink paths
and values are captured or verified.
