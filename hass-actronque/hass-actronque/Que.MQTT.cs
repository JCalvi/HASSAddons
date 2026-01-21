using System;
using System.Collections.Generic;
using Newtonsoft.Json;

namespace HMX.HASSActronQue
{
	public partial class Que
	{
		private static void MQTTRegister()
		{
			AirConditionerZone zone;
			int iDeviceIndex = 0;
			string strHANameModifier = "", strDeviceNameModifier = "", strAirConditionerNameMQTT = "";

			if (_bQueLogging) Logging.WriteDebugLog("Que.MQTTRegister()");

			foreach (AirConditionerUnit unit in _airConditionerUnits.Values)
			{
				Logging.WriteDebugLog("Que.MQTTRegister() Registering Unit: {0}", unit.Serial);

				// Clear Last Failed Command
				MQTT.SendMessage(string.Format("actronque{0}/lastfailedcommand", unit.Serial), "");

				if (iDeviceIndex == 0)
				{
					strHANameModifier = "";
					strDeviceNameModifier = unit.Serial;
				}
				else
				{
					strHANameModifier = iDeviceIndex.ToString();
					strDeviceNameModifier = unit.Serial;
				}

				strAirConditionerNameMQTT = string.Format("{0} ({1})", Service.DeviceNameMQTT, unit.Name);

				// Create device info object for proper grouping in Home Assistant
				var deviceInfo = new
				{
					identifiers = new[] { $"actronque_{unit.Serial}" },
					name = strAirConditionerNameMQTT,
					manufacturer = "Actron",
					model = "Actron Que"
				};

				// Climate entity with complete configuration

				if (_bSeparateHeatCool)
				{
					MQTT.SendMessage(string.Format("homeassistant/climate/actronque{0}/config", strHANameModifier),
						JsonConvert.SerializeObject(new
						{
							name = strAirConditionerNameMQTT,
							unique_id = $"{unit.Serial}-AC",
							default_entity_id = $"climate.actronque_{unit.Serial}",
							mode_command_topic = $"actronque{strDeviceNameModifier}/mode/set",
							mode_state_topic = $"actronque{unit.Serial}/mode",
							// advertise separate high/low
							temperature_high_command_topic = $"actronque{strDeviceNameModifier}/temperature/high/set",
							temperature_low_command_topic = $"actronque{strDeviceNameModifier}/temperature/low/set",
							temperature_high_state_topic = $"actronque{unit.Serial}/settemperature/high",
							temperature_low_state_topic = $"actronque{unit.Serial}/settemperature/low",
							current_temperature_topic = $"actronque{unit.Serial}/temperature",
							fan_mode_command_topic = $"actronque{strDeviceNameModifier}/fan/set",
							fan_mode_state_topic = $"actronque{unit.Serial}/fanmode",
							current_hvac_action_topic = $"actronque{unit.Serial}/compressor",
							modes = new[] { "off", "auto", "cool", "heat", "fan_only" },
							fan_modes = new[] { "auto", "low", "medium", "high" },
							min_temp = 10,
							max_temp = 32,
							temp_step = 0.5,
							temperature_unit = "C",
							device = deviceInfo
						}));
				}
				else
				{
					// existing single-temp discovery (unchanged)
					MQTT.SendMessage(string.Format("homeassistant/climate/actronque{0}/config", strHANameModifier),
						JsonConvert.SerializeObject(new
						{
							name = strAirConditionerNameMQTT,
							unique_id = $"{unit.Serial}-AC",
							default_entity_id = $"climate.actronque_{unit.Serial}",
							mode_command_topic = $"actronque{strDeviceNameModifier}/mode/set",
							mode_state_topic = $"actronque{unit.Serial}/mode",
							temperature_command_topic = $"actronque{strDeviceNameModifier}/temperature/set",
							temperature_state_topic = $"actronque{unit.Serial}/settemperature",
							current_temperature_topic = $"actronque{unit.Serial}/temperature",
							fan_mode_command_topic = $"actronque{strDeviceNameModifier}/fan/set",
							fan_mode_state_topic = $"actronque{unit.Serial}/fanmode",
							current_hvac_action_topic = $"actronque{unit.Serial}/compressor",
							modes = new[] { "off", "auto", "cool", "heat", "fan_only" },
							fan_modes = new[] { "auto", "low", "medium", "high" },
							min_temp = 10,
							max_temp = 32,
							temp_step = 0.5,
							temperature_unit = "C",
							device = deviceInfo
						}));
				}

				// Humidity sensor
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}humidity/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Humidity",
						unique_id = $"{unit.Serial}-Humidity",
						default_entity_id = $"sensor.actronque_{unit.Serial}_humidity",
						state_topic = $"actronque{unit.Serial}/humidity",
						device_class = "humidity",
						unit_of_measurement = "%",
						value_template = "{{ value | round(1) }}",
						device = deviceInfo
					}));

				// Temperature sensor
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}temperature/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Temperature",
						unique_id = $"{unit.Serial}-Temperature",
						default_entity_id = $"sensor.actronque_{unit.Serial}_temperature",
						state_topic = $"actronque{unit.Serial}/temperature",
						device_class = "temperature",
						unit_of_measurement = "°C",
						value_template = "{{ value | round(1) }}",
						device = deviceInfo
					}));

				// Outdoor temperature sensor
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}outdoortemperature/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Outdoor Temperature",
						unique_id = $"{unit.Serial}-OutdoorTemperature",
						default_entity_id = $"sensor.actronque_{unit.Serial}_outdoor_temperature",
						state_topic = $"actronque{unit.Serial}/outdoortemperature",
						device_class = "temperature",
						unit_of_measurement = "°C",
						value_template = "{{ value | round(1) }}",
						device = deviceInfo
					}));

				// Compressor capacity sensor
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}compressorcapacity/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Compressor Capacity",
						unique_id = $"{unit.Serial}-CompressorCapacity",
						default_entity_id = $"sensor.actronque_{unit.Serial}_compressor_capacity",
						state_topic = $"actronque{unit.Serial}/compressorcapacity",
						unit_of_measurement = "%",
						value_template = "{{ value | round(1) }}",
						icon = "mdi:gauge",
						device = deviceInfo
					}));

				// Compressor power sensor
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}compressorpower/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Compressor Power",
						unique_id = $"{unit.Serial}-CompressorPower",
						default_entity_id = $"sensor.actronque_{unit.Serial}_compressor_power",
						state_topic = $"actronque{unit.Serial}/compressorpower",
						device_class = "power",
						unit_of_measurement = "kW",
						value_template = "{{ value | round(2) }}",
						device = deviceInfo
					}));

				// Coil inlet temperature sensor
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}coilinlettemperature/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Coil Inlet Temperature",
						unique_id = $"{unit.Serial}-CoilInletTemperature",
						default_entity_id = $"sensor.actronque_{unit.Serial}_coil_inlet_temperature",
						state_topic = $"actronque{unit.Serial}/coilinlettemperature",
						device_class = "temperature",
						unit_of_measurement = "°C",
						value_template = "{{ value | round(2) }}",
						device = deviceInfo
					}));

				// Filter needs cleaning sensor
				MQTT. SendMessage(string.Format("homeassistant/binary_sensor/actronque{0}/cleanfilter/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Clean Filter",
						unique_id = $"{unit. Serial}-CleanFilter",
						default_entity_id = $"binary_sensor.actronque_{unit.Serial}_clean_filter",
						state_topic = $"actronque{unit.Serial}/cleanfilter",
						payload_on = "ON",
						payload_off = "OFF",
						state_on = "ON",
						state_off = "OFF",
						device_class = "problem",
						icon = "mdi:air-filter",
						device = deviceInfo
					}));

				// Filter hours since clean sensor
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}/fantsfc/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Fan Time Since Filter Cleaned",
						unique_id = $"{unit.Serial}-FanTSFC",
						default_entity_id = $"sensor.actronque_{unit.Serial}_fan_time_since_filter_cleaned",
						state_topic = $"actronque{unit.Serial}/fantsfc",
						device_class = "duration",
						unit_of_measurement = "h",
						state_class = "total_increasing",
						icon = "mdi:clock-outline",
						device = deviceInfo
					}));

				// Fan PWM sensor
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}fanpwm/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Fan PWM",
						unique_id = $"{unit.Serial}-FanPWM",
						default_entity_id = $"sensor.actronque_{unit.Serial}_fan_pwm",
						state_topic = $"actronque{unit.Serial}/fanpwm",
						unit_of_measurement = "%",
						value_template = "{{ value | round(0) }}",
						icon = "mdi:fan",
						device = deviceInfo
					}));

				// Fan RPM sensor
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}fanrpm/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Fan RPM",
						unique_id = $"{unit.Serial}-FanRPM",
						default_entity_id = $"sensor.actronque_{unit.Serial}_fan_rpm",
						state_topic = $"actronque{unit.Serial}/fanrpm",
						unit_of_measurement = "RPM",
						value_template = "{{ value | round(0) }}",
						icon = "mdi:fan",
						device = deviceInfo
					}));

				// Control All Zones switch
				MQTT.SendMessage(string.Format("homeassistant/switch/actronque{0}/controlallzones/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Control All Zones",
						unique_id = $"{unit.Serial}-ControlAllZones",
						default_entity_id = $"switch.actronque_{unit.Serial}_control_all_zones",
						state_topic = $"actronque{unit.Serial}/controlallzones",
						command_topic = $"actronque{strDeviceNameModifier}/controlallzones/set",
						payload_on = "ON",
						payload_off = "OFF",
						state_on = "ON",
						state_off = "OFF",
						icon = "mdi:home-group",
						device = deviceInfo
					}));
				MQTT.Subscribe($"actronque{strDeviceNameModifier}/controlallzones/set", unit.Serial);

				// Away Mode switch
				MQTT.SendMessage(string.Format("homeassistant/switch/actronque{0}/awaymode/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Away Mode",
						unique_id = $"{unit.Serial}-AwayMode",
						default_entity_id = $"switch.actronque_{unit.Serial}_away_mode",
						state_topic = $"actronque{unit.Serial}/awaymode",
						command_topic = $"actronque{strDeviceNameModifier}/awaymode/set",
						payload_on = "ON",
						payload_off = "OFF",
						state_on = "ON",
						state_off = "OFF",						
						icon = "mdi:home-export-outline",
						device = deviceInfo
					}));
				MQTT.Subscribe($"actronque{strDeviceNameModifier}/awaymode/set", unit.Serial);

				// Quiet Mode switch
				MQTT.SendMessage(string.Format("homeassistant/switch/actronque{0}/quietmode/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Quiet Mode",
						unique_id = $"{unit.Serial}-QuietMode",
						default_entity_id = $"switch.actronque_{unit.Serial}_quiet_mode",
						state_topic = $"actronque{unit.Serial}/quietmode",
						command_topic = $"actronque{strDeviceNameModifier}/quietmode/set",
						payload_on = "ON",
						payload_off = "OFF",
						state_on = "ON",
						state_off = "OFF",						
						icon = "mdi:volume-off",
						device = deviceInfo
					}));
				MQTT.Subscribe($"actronque{strDeviceNameModifier}/quietmode/set", unit.Serial);

				// Constant Fan Mode switch
				MQTT.SendMessage(string.Format("homeassistant/switch/actronque{0}/constantfanmode/config", strHANameModifier),
					JsonConvert.SerializeObject(new
					{
						name = $"{strAirConditionerNameMQTT} Constant Fan Mode",
						unique_id = $"{unit.Serial}-ConstantFanMode",
						default_entity_id = $"switch.actronque_{unit.Serial}_constant_fan_mode",
						state_topic = $"actronque{unit.Serial}/constantfanmode",
						command_topic = $"actronque{strDeviceNameModifier}/constantfanmode/set",
						payload_on = "ON",
						payload_off = "OFF",
						state_on = "ON",
						state_off = "OFF",						
						icon = "mdi:fan-auto",
						device = deviceInfo
					}));
				MQTT.Subscribe($"actronque{strDeviceNameModifier}/constantfanmode/set", unit.Serial);

				foreach (int iZone in unit.Zones.Keys)
				{
					zone = unit.Zones[iZone];

					if (zone.Exists)
					{
						// Zone switch
						MQTT.SendMessage(string.Format("homeassistant/switch/actronque{0}/airconzone{1}/config", strHANameModifier, iZone),
							JsonConvert.SerializeObject(new
							{
								name = $"{zone.Name}",
								unique_id = $"{unit.Serial}-z{iZone}s",
								default_entity_id = $"switch.actronque_{unit.Serial}_zone_{iZone}_{SanitizeName(zone.Name)}",
								state_topic = $"actronque{unit.Serial}/zone{iZone}",
								command_topic = $"actronque{strDeviceNameModifier}/zone{iZone}/set",
								payload_on = "ON",
								payload_off = "OFF",
								state_on = "ON",
								state_off = "OFF",
								icon = "mdi:home-thermometer",
								device = deviceInfo
							}));
						MQTT.Subscribe($"actronque{strDeviceNameModifier}/zone{iZone}/set", unit.Serial, iZone);

						// Zone temperature sensor
						MQTT.SendMessage(string. Format("homeassistant/sensor/actronque{0}/airconzone{1}/config", strHANameModifier, iZone),
							JsonConvert.SerializeObject(new
							{
								name = $"{zone.Name} Temperature",
								unique_id = $"{unit.Serial}-z{iZone}t",
								default_entity_id = $"sensor.actronque_{unit. Serial}_zone_{iZone}_{SanitizeName(zone.Name)}_temperature",
								state_topic = $"actronque{unit. Serial}/zone{iZone}/temperature",
								device_class = "temperature",
								unit_of_measurement = "°C",
								value_template = "{{ value | round(1) }}",
								device = deviceInfo
							}));
							
						// Zone damper position sensor
						MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}/zone{1}position/config", strHANameModifier, iZone),
							JsonConvert.SerializeObject(new
							{
								name = $"{zone.Name} Damper Position",
								unique_id = $"{unit.Serial}-z{iZone}-position",
								default_entity_id = $"sensor.actronque_{unit.Serial}_zone_{iZone}_{SanitizeName(zone.Name)}_damper_position",
								state_topic = $"actronque{unit.Serial}/zone{iZone}/position",
								unit_of_measurement = "%",
								icon = "mdi:valve",
								device = deviceInfo
							}));							

						if (_bPerZoneControls)
						{
							MQTT.Subscribe($"actronque{strDeviceNameModifier}/zone{iZone}/temperature/set", unit.Serial, iZone);
							MQTT.Subscribe($"actronque{strDeviceNameModifier}/zone{iZone}/temperature/high/set", unit.Serial, iZone);
							MQTT.Subscribe($"actronque{strDeviceNameModifier}/zone{iZone}/temperature/low/set", unit.Serial, iZone);
							MQTT.Subscribe($"actronque{strDeviceNameModifier}/zone{iZone}/mode/set", unit.Serial, iZone);

							// Per-zone climate entity
							if (_bSeparateHeatCool)
							{
								MQTT.SendMessage(string.Format("homeassistant/climate/actronque{0}/zone{1}/config", strHANameModifier, iZone),
									JsonConvert.SerializeObject(new
									{
										name = $"{zone.Name}",
										unique_id = $"{unit.Serial}-z{iZone}-climate",
										default_entity_id = $"climate.actronque_{unit.Serial}_zone_{iZone}_{SanitizeName(zone.Name)}",
										mode_command_topic = $"actronque{strDeviceNameModifier}/zone{iZone}/mode/set",
										mode_state_topic = $"actronque{unit.Serial}/zone{iZone}/mode",
										// advertise separate high/low setpoint command & state topics
										temperature_high_command_topic = $"actronque{strDeviceNameModifier}/zone{iZone}/temperature/high/set",
										temperature_low_command_topic = $"actronque{strDeviceNameModifier}/zone{iZone}/temperature/low/set",
										temperature_high_state_topic = $"actronque{unit.Serial}/zone{iZone}/settemperature/high",
										temperature_low_state_topic = $"actronque{unit.Serial}/zone{iZone}/settemperature/low",
										current_temperature_topic = $"actronque{unit.Serial}/zone{iZone}/temperature",
										current_hvac_action_topic = $"actronque{unit.Serial}/zone{iZone}/compressor",
										modes = new[] { "off", "auto", "cool", "heat", "fan_only" },
										min_temp = 10,
										max_temp = 32,
										temp_step = 0.5,
										temperature_unit = "C",
										device = deviceInfo
									}));
							}
							else
							{
								// existing single-temperature discovery (unchanged)
								MQTT.SendMessage(string.Format("homeassistant/climate/actronque{0}/zone{1}/config", strHANameModifier, iZone),
									JsonConvert.SerializeObject(new
									{
										name = $"{zone.Name}",
										unique_id = $"{unit.Serial}-z{iZone}-climate",
										default_entity_id = $"climate.actronque_{unit.Serial}_zone_{iZone}_{SanitizeName(zone.Name)}",
										mode_command_topic = $"actronque{strDeviceNameModifier}/zone{iZone}/mode/set",
										mode_state_topic = $"actronque{unit.Serial}/zone{iZone}/mode",
										temperature_command_topic = $"actronque{strDeviceNameModifier}/zone{iZone}/temperature/set",
										temperature_state_topic = $"actronque{unit.Serial}/zone{iZone}/settemperature",
										current_temperature_topic = $"actronque{unit.Serial}/zone{iZone}/temperature",
										current_hvac_action_topic = $"actronque{unit.Serial}/zone{iZone}/compressor",
										modes = new[] { "off", "auto", "cool", "heat", "fan_only" },
										min_temp = 10,
										max_temp = 32,
										temp_step = 0.5,
										temperature_unit = "C",
										device = deviceInfo
									}));
							}

							if (_bShowBatterySensors)
							{
								foreach (string sensor in zone.Sensors.Keys)
								{
									// Zone sensor battery level
									MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}/zone{1}sensor{2}battery/config", strHANameModifier, iZone, sensor),
										JsonConvert.SerializeObject(new
										{
											name = $"{zone.Name} Sensor {sensor} Battery",
											unique_id = $"{unit.Serial}-z{iZone}-sensor{sensor}-battery",
											default_entity_id = $"sensor.actronque_{unit.Serial}_zone_{iZone}_{SanitizeName(zone.Name)}_sensor_{sensor}_battery",
											state_topic = $"actronque{unit.Serial}/zone{iZone}sensor{sensor}/battery",
											device_class = "battery",
											unit_of_measurement = "%",
											value_template = "{{ value | round(1) }}",
											device = deviceInfo
										}));
								}
							}
						}
					}
				}

				MQTT.Subscribe($"actronque{strDeviceNameModifier}/mode/set", unit.Serial);
				MQTT.Subscribe($"actronque{strDeviceNameModifier}/fan/set", unit.Serial);
				MQTT.Subscribe($"actronque{strDeviceNameModifier}/temperature/set", unit.Serial);
				MQTT.Subscribe($"actronque{strDeviceNameModifier}/temperature/high/set", unit.Serial);
				MQTT.Subscribe($"actronque{strDeviceNameModifier}/temperature/low/set", unit.Serial);

				iDeviceIndex++;
			}
		}

		private static void MQTTUpdateData(AirConditionerUnit unit, UpdateItems items)
		{
			if (_bQueLogging) Logging.WriteDebugLog("Que.MQTTUpdateData() Unit: {0}, Items: {1}", unit.Serial, items.ToString());

			// If the unit is currently suppressed because we published optimistic values, skip the update (prevents overwriting optimistic state).
			if (IsUnitSuppressed(unit.Serial))
			{
				if (_bQueLogging)
					Logging.WriteDebugLog("Que.MQTTUpdateData() Suppressed update for unit {0}", unit.Serial);
				return;
			}

			if (unit.Data.LastUpdated == DateTime.MinValue)
			{
				if (_bQueLogging)
					Logging.WriteDebugLog("Que.MQTTUpdateData() Skipping update, No data received");
				return;
			}

			if (items.HasFlag(UpdateItems.Main))
			{
				// Fan Mode
				switch (unit.Data.FanMode)
				{
					case "AUTO":
					case "AUTO+CONT":
						MQTT.SendMessage(string.Format("actronque{0}/fanmode", unit.Serial), "auto");
						break;
					case "LOW":
					case "LOW+CONT":
						MQTT.SendMessage(string.Format("actronque{0}/fanmode", unit.Serial), "low");
						break;
					case "MED":
					case "MED+CONT":
						MQTT.SendMessage(string.Format("actronque{0}/fanmode", unit.Serial), "medium");
						break;
					case "HIGH":
					case "HIGH+CONT":
						MQTT.SendMessage(string.Format("actronque{0}/fanmode", unit.Serial), "high");
						break;
					default:
						Logging.WriteDebugLog("Que.MQTTUpdateData() Unexpected Fan Mode: {0}", unit.Data.FanMode);
						break;
				}

				// Temperature / humidity / power / mode
				MQTT.SendMessage(string.Format("actronque{0}/temperature", unit.Serial), unit.Data.Temperature.ToString("N1"));
				MQTT.SendMessage(string.Format("actronque{0}/outdoortemperature", unit.Serial), unit.Data.OutdoorTemperature.ToString("N1"));
				MQTT.SendMessage(string.Format("actronque{0}/humidity", unit.Serial), unit.Data.Humidity.ToString("N1"));

				if (!unit.Data.On)
				{
					MQTT.SendMessage(string.Format("actronque{0}/mode", unit.Serial), "off");
					MQTT.SendMessage(string.Format("actronque{0}/settemperature", unit.Serial), GetSetTemperature(unit.Data.SetTemperatureHeating, unit.Data.SetTemperatureCooling).ToString("N1"));

					// Change polling to off value
					_iPollInterval = _iPollIntervalOff;
					if (_bQueLogging) Logging.WriteDebugLog("Que.MQTTUpdateData() Polling Rate Updated to Off Value: {0}", _iPollInterval);
				}
				else
				{
					// Change polling to on value
					_iPollInterval = _iPollIntervalOn;
					if (_bQueLogging) Logging.WriteDebugLog("Que.MQTTUpdateData() Polling Rate Updated to On Value: {0}", _iPollInterval);

					switch (unit.Data.Mode)
					{
						case "AUTO":
							MQTT.SendMessage(string.Format("actronque{0}/mode", unit.Serial), "auto");
							MQTT.SendMessage(string.Format("actronque{0}/settemperature", unit.Serial), GetSetTemperature(unit.Data.SetTemperatureHeating, unit.Data.SetTemperatureCooling).ToString("N1"));
							break;
						case "COOL":
							MQTT.SendMessage(string.Format("actronque{0}/mode", unit.Serial), "cool");
							MQTT.SendMessage(string.Format("actronque{0}/settemperature", unit.Serial), unit.Data.SetTemperatureCooling.ToString("N1"));
							break;
						case "HEAT":
							MQTT.SendMessage(string.Format("actronque{0}/mode", unit.Serial), "heat");
							MQTT.SendMessage(string.Format("actronque{0}/settemperature", unit.Serial), unit.Data.SetTemperatureHeating.ToString("N1"));
							break;
						case "FAN":
							MQTT.SendMessage(string.Format("actronque{0}/mode", unit.Serial), "fan_only");
							MQTT.SendMessage(string.Format("actronque{0}/settemperature", unit.Serial), "");
							break;
						default:
							Logging.WriteDebugLog("Que.MQTTUpdateData() Unexpected Mode: {0}", unit.Data.Mode);
							break;
					}
				}

				MQTT.SendMessage(string.Format("actronque{0}/settemperature/high", unit.Serial), unit.Data.SetTemperatureCooling.ToString("N1"));
				MQTT.SendMessage(string.Format("actronque{0}/settemperature/low", unit.Serial), unit.Data.SetTemperatureHeating.ToString("N1"));

				// Compressor
				if (unit.Data.CompressorCapacity > 0)
				{
					switch (unit.Data.CompressorState)
					{
						case "HEAT":
							MQTT.SendMessage(string.Format("actronque{0}/compressor", unit.Serial), "heating");
							break;
						case "COOL":
							MQTT.SendMessage(string.Format("actronque{0}/compressor", unit.Serial), "cooling");
							break;
						case "OFF":
							MQTT.SendMessage(string.Format("actronque{0}/compressor", unit.Serial), "off");
							break;
						case "IDLE":
							MQTT.SendMessage(string.Format("actronque{0}/compressor", unit.Serial), unit.Data.On ? "idle" : "off");
							break;
						default:
							Logging.WriteDebugLog("Que.MQTTUpdateData() Unexpected Compressor State: {0}", unit.Data.CompressorState);
							break;
					}
				}
				else
				{
					MQTT.SendMessage(string.Format("actronque{0}/compressor", unit.Serial), unit.Data.On ? "idle" : "off");
				}

				// Compressor Capacity & Power
				MQTT.SendMessage(string.Format("actronque{0}/compressorcapacity", unit.Serial), unit.Data.CompressorCapacity.ToString("F1"));
				MQTT.SendMessage(string.Format("actronque{0}/compressorpower", unit.Serial), unit.Data.CompressorPower.ToString("F2"));

				// Other sensors
				MQTT.SendMessage(string.Format("actronque{0}/coilinlettemperature", unit.Serial), unit.Data.CoilInletTemperature.ToString("F2"));
				MQTT.SendMessage(string.Format("actronque{0}/fanpwm", unit.Serial), unit.Data.FanPWM.ToString("F0"));
				MQTT.SendMessage(string.Format("actronque{0}/fanrpm", unit.Serial), unit.Data.FanRPM.ToString("F0"));
				MQTT.SendMessage(string.Format("actronque{0}/cleanfilter", unit.Serial), unit.Data.CleanFilter ? "ON" : "OFF");
				MQTT.SendMessage(string.Format("actronque{0}/fantsfc", unit.Serial), (unit.Data.FanTSFC / 6).ToString("F0"));

				// Control/Away/Quiet/Constant Fan
				MQTT.SendMessage(string.Format("actronque{0}/controlallzones", unit.Serial), unit.Data.ControlAllZones ? "ON" : "OFF");
				MQTT.SendMessage(string.Format("actronque{0}/awaymode", unit.Serial), unit.Data.AwayMode ? "ON" : "OFF");
				MQTT.SendMessage(string.Format("actronque{0}/quietmode", unit.Serial), unit.Data.QuietMode ? "ON" : "OFF");
				MQTT.SendMessage(string.Format("actronque{0}/constantfanmode", unit.Serial), unit.Data.ConstantFanMode ? "ON" : "OFF");
			}

			// Zones
			foreach (int iIndex in unit.Zones.Keys)
			{
				if (unit.Zones[iIndex].Exists && items.HasFlag((UpdateItems)(1 << iIndex)))
				{
					MQTT.SendMessage(string.Format("actronque{0}/zone{1}", unit.Serial, iIndex), unit.Zones[iIndex].State ? "ON" : "OFF");
					MQTT.SendMessage(string.Format("actronque{0}/zone{1}/temperature", unit.Serial, iIndex), unit.Zones[iIndex].Temperature.ToString("N1"));
					MQTT.SendMessage(string.Format("actronque{0}/zone{1}/position", unit.Serial, iIndex), (unit.Zones[iIndex].Position * 5).ToString());

					if (_bPerZoneControls)
					{
						if (!unit.Data.On)
						{
							MQTT.SendMessage(string.Format("actronque{0}/zone{1}/mode", unit.Serial, iIndex), "off");
							MQTT.SendMessage(string.Format("actronque{0}/zone{1}/settemperature", unit.Serial, iIndex), GetSetTemperature(unit.Zones[iIndex].SetTemperatureHeating, unit.Zones[iIndex].SetTemperatureCooling).ToString("N1"));
						}
						else
						{
							switch (unit.Data.Mode)
							{
								case "AUTO":
									MQTT.SendMessage(string.Format("actronque{0}/zone{1}/mode", unit.Serial, iIndex), (unit.Zones[iIndex].State ? "auto" : "off"));
									MQTT.SendMessage(string.Format("actronque{0}/zone{1}/settemperature", unit.Serial, iIndex), GetSetTemperature(unit.Zones[iIndex].SetTemperatureHeating, unit.Zones[iIndex].SetTemperatureCooling).ToString("N1"));
									break;
								case "COOL":
									MQTT.SendMessage(string.Format("actronque{0}/zone{1}/mode", unit.Serial, iIndex), (unit.Zones[iIndex].State ? "cool" : "off"));
									MQTT.SendMessage(string.Format("actronque{0}/zone{1}/settemperature", unit.Serial, iIndex), unit.Zones[iIndex].SetTemperatureCooling.ToString("N1"));
									break;
								case "HEAT":
									MQTT.SendMessage(string.Format("actronque{0}/zone{1}/mode", unit.Serial, iIndex), (unit.Zones[iIndex].State ? "heat" : "off"));
									MQTT.SendMessage(string.Format("actronque{0}/zone{1}/settemperature", unit.Serial, iIndex), unit.Zones[iIndex].SetTemperatureHeating.ToString("N1"));
									break;
								case "FAN":
									MQTT.SendMessage(string.Format("actronque{0}/zone{1}/mode", unit.Serial, iIndex), (unit.Zones[iIndex].State ? "fan_only" : "off"));
									MQTT.SendMessage(string.Format("actronque{0}/zone{1}/settemperature", unit.Serial, iIndex), GetSetTemperature(unit.Zones[iIndex].SetTemperatureHeating, unit.Zones[iIndex].SetTemperatureCooling).ToString("N1"));
									break;
								default:
									Logging.WriteDebugLog("Que.MQTTUpdateData() Unexpected Mode: {0}", unit.Data.Mode);
									break;
							}
						}

						MQTT.SendMessage(string.Format("actronque{0}/zone{1}/settemperature/high", unit.Serial, iIndex), unit.Zones[iIndex].SetTemperatureCooling.ToString("N1"));
						MQTT.SendMessage(string.Format("actronque{0}/zone{1}/settemperature/low", unit.Serial, iIndex), unit.Zones[iIndex].SetTemperatureHeating.ToString("N1"));

						if (unit.Data.CompressorCapacity > 0 && unit.Zones[iIndex].Position > 0)
						{
							switch (unit.Data.CompressorState)
							{
								case "HEAT":
									MQTT.SendMessage(string.Format("actronque{0}/zone{1}/compressor", unit.Serial, iIndex), "heating");
									break;
								case "COOL":
									MQTT.SendMessage(string.Format("actronque{0}/zone{1}/compressor", unit.Serial, iIndex), "cooling");
									break;
								case "OFF":
									MQTT.SendMessage(string.Format("actronque{0}/zone{1}/compressor", unit.Serial, iIndex), "off");
									break;
								case "IDLE":
									MQTT.SendMessage(string.Format("actronque{0}/zone{1}/compressor", unit.Serial, iIndex), unit.Data.On ? "idle" : "off");
									break;
								default:
									Logging.WriteDebugLog("Que.MQTTUpdateData() Unexpected Compressor State: {0}", unit.Data.CompressorState);
									break;
							}
						}
						else
						{
							MQTT.SendMessage(string.Format("actronque{0}/zone{1}/compressor", unit.Serial, iIndex), unit.Zones[iIndex].State ? "idle" : "off");
						}
					}

					// Per Zone Sensors
					foreach (AirConditionerSensor sensor in unit.Zones[iIndex].Sensors.Values)
					{
						MQTT.SendMessage(string.Format("actronque{0}/zone{1}sensor{2}/temperature", unit.Serial, iIndex, sensor.Serial), sensor.Temperature.ToString("N1"));
					}

					// Per Zone Sensors/Controls
					if (_bPerZoneControls)
					{
						foreach (AirConditionerSensor sensor in unit.Zones[iIndex].Sensors.Values)
						{
							MQTT.SendMessage(string.Format("actronque{0}/zone{1}sensor{2}/battery", unit.Serial, iIndex, sensor.Serial), sensor.Battery.ToString("N1"));
						}
					}
				}
			}
		}
	}
}