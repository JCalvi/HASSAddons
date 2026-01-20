    // Adding default_entity_id to all MQTT discovery configurations
    // Assuming 'unit' is defined and has a 'Serial' property

    // Climate
    var climateConfig = new { /* other properties */ default_entity_id = $"climate.actronque_{unit.Serial}" };
    string climateJson = JsonConvert.SerializeObject(climateConfig);

    // Humidity sensor
    var humidityConfig = new { /* other properties */ default_entity_id = $"sensor.actronque_{unit.Serial}_humidity" };
    string humidityJson = JsonConvert.SerializeObject(humidityConfig);

    // Temperature sensor
    var temperatureConfig = new { /* other properties */ default_entity_id = $"sensor.actronque_{unit.Serial}_temperature" };
    string temperatureJson = JsonConvert.SerializeObject(temperatureConfig);

    // Outdoor temperature
    var outdoorTemperatureConfig = new { /* other properties */ default_entity_id = $"sensor.actronque_{unit.Serial}_outdoor_temperature" };
    string outdoorTemperatureJson = JsonConvert.SerializeObject(outdoorTemperatureConfig);

    // Compressor capacity
    var compressorCapacityConfig = new { /* other properties */ default_entity_id = $"sensor.actronque_{unit.Serial}_compressor_capacity" };
    string compressorCapacityJson = JsonConvert.SerializeObject(compressorCapacityConfig);

    // Compressor power
    var compressorPowerConfig = new { /* other properties */ default_entity_id = $"sensor.actronque_{unit.Serial}_compressor_power" };
    string compressorPowerJson = JsonConvert.SerializeObject(compressorPowerConfig);

    // Coil inlet temp
    var coilInletTempConfig = new { /* other properties */ default_entity_id = $"sensor.actronque_{unit.Serial}_coil_inlet_temperature" };
    string coilInletTempJson = JsonConvert.SerializeObject(coilInletTempConfig);

    // Fan PWM
    var fanPwmConfig = new { /* other properties */ default_entity_id = $"sensor.actronque_{unit.Serial}_fan_pwm" };
    string fanPwmJson = JsonConvert.SerializeObject(fanPwmConfig);

    // Fan RPM
    var fanRpmConfig = new { /* other properties */ default_entity_id = $"sensor.actronque_{unit.Serial}_fan_rpm" };
    string fanRpmJson = JsonConvert.SerializeObject(fanRpmConfig);

    // Control all zones switch
    var controlAllZonesSwitchConfig = new { /* other properties */ default_entity_id = $"switch.actronque_{unit.Serial}_control_all_zones" };
    string controlAllZonesSwitchJson = JsonConvert.SerializeObject(controlAllZonesSwitchConfig);

    // Away mode switch
    var awayModeSwitchConfig = new { /* other properties */ default_entity_id = $"switch.actronque_{unit.Serial}_away_mode" };
    string awayModeSwitchJson = JsonConvert.SerializeObject(awayModeSwitchConfig);

    // Quiet mode switch
    var quietModeSwitchConfig = new { /* other properties */ default_entity_id = $"switch.actronque_{unit.Serial}_quiet_mode" };
    string quietModeSwitchJson = JsonConvert.SerializeObject(quietModeSwitchConfig);

    // Constant fan mode switch
    var constantFanModeSwitchConfig = new { /* other properties */ default_entity_id = $"switch.actronque_{unit.Serial}_constant_fan_mode" };
    string constantFanModeSwitchJson = JsonConvert.SerializeObject(constantFanModeSwitchConfig);

    // Zone switches
    for (int iZone = 0; iZone < numberOfZones; iZone++)
    {
        var zoneSwitchConfig = new { /* other properties */ default_entity_id = $"switch.actronque_{unit.Serial}_zone_{iZone}" };
        string zoneSwitchJson = JsonConvert.SerializeObject(zoneSwitchConfig);
    }

    // Zone temperature sensors
    for (int iZone = 0; iZone < numberOfZones; iZone++)
    {
        var zoneTemperatureConfig = new { /* other properties */ default_entity_id = $"sensor.actronque_{unit.Serial}_zone_{iZone}_temperature" };
        string zoneTemperatureJson = JsonConvert.SerializeObject(zoneTemperatureConfig);
    }

    // Zone sensor battery
    for (int iZone = 0; iZone < numberOfZones; iZone++)
    {
        var zoneSensorBatteryConfig = new { /* other properties */ default_entity_id = $"sensor.actronque_{unit.Serial}_zone_{iZone}_sensor_{sensor}_battery" };
        string zoneSensorBatteryJson = JsonConvert.SerializeObject(zoneSensorBatteryConfig);
    }