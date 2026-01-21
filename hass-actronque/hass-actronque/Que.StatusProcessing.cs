using System;
using Newtonsoft.Json.Linq;

namespace HMX.HASSActronQue
{
	public partial class Que
	{
		private static void ProcessFullStatus(long lRequestId, AirConditionerUnit unit, dynamic jsonResponse)
		{
			// jsonResponse is expected to be a JObject (lastKnownState)
			JObject jState = jsonResponse as JObject ?? new JObject();
			JArray aEnabledZones = jState["UserAirconSettings"]?["EnabledZones"] as JArray;
			if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessFullStatus() Unit: {0}", unit.Serial);

			// Compressor Mode
			ProcessPartialStatus(lRequestId, "LiveAircon.CompressorMode", jState["LiveAircon"]?["CompressorMode"]?.ToString(), ref unit.Data.CompressorState);

			// Compressor Capacity
			ProcessPartialStatus(lRequestId, "LiveAircon.CompressorCapacity", jState["LiveAircon"]?["CompressorCapacity"]?.ToString(), ref unit.Data.CompressorCapacity);

			// Compressor Power
			if (jState["LiveAircon"] is JObject la && la.ContainsKey("OutdoorUnit"))
				ProcessPartialStatus(lRequestId, "LiveAircon.OutdoorUnit.CompPower", la["OutdoorUnit"]?["CompPower"]?.ToString(), ref unit.Data.CompressorPower);

			// On
			ProcessPartialStatus(lRequestId, "UserAirconSettings.isOn", jState["UserAirconSettings"]?["isOn"]?.ToString(), ref unit.Data.On);

			// Mode
			ProcessPartialStatus(lRequestId, "UserAirconSettings.Mode", jState["UserAirconSettings"]?["Mode"]?.ToString(), ref unit.Data.Mode);

			// Fan Mode
			ProcessPartialStatus(lRequestId, "UserAirconSettings.FanMode", jState["UserAirconSettings"]?["FanMode"]?.ToString(), ref unit.Data.FanMode);

			// Constant Fan Mode (case-insensitive detection)
			unit.Data.ConstantFanMode = (unit.Data.FanMode ?? "").IndexOf("+CONT", StringComparison.OrdinalIgnoreCase) >= 0;

			// Away Mode
			ProcessPartialStatus(lRequestId, "UserAirconSettings.AwayMode", jState["UserAirconSettings"]?["AwayMode"]?.ToString(), ref unit.Data.AwayMode);

			// Quiet Mode
			ProcessPartialStatus(lRequestId, "UserAirconSettings.QuietMode", jState["UserAirconSettings"]?["QuietMode"]?.ToString(), ref unit.Data.QuietMode);

			// Set Cooling Temperature
			ProcessPartialStatus(lRequestId, "UserAirconSettings.TemperatureSetpoint_Cool_oC", jState["UserAirconSettings"]?["TemperatureSetpoint_Cool_oC"]?.ToString(), ref unit.Data.SetTemperatureCooling);

			// Set Heating Temperature
			ProcessPartialStatus(lRequestId, "UserAirconSettings.TemperatureSetpoint_Heat_oC", jState["UserAirconSettings"]?["TemperatureSetpoint_Heat_oC"]?.ToString(), ref unit.Data.SetTemperatureHeating);

			// Control All Zones
			ProcessPartialStatus(lRequestId, "MasterInfo.ControlAllZones", jState["MasterInfo"]?["ControlAllZones"]?.ToString(), ref unit.Data.ControlAllZones);

			// Live Temperature
			ProcessPartialStatus(lRequestId, "MasterInfo.LiveTemp_oC", jState["MasterInfo"]?["LiveTemp_oC"]?.ToString(), ref unit.Data.Temperature);

			// Live Temperature Outside
			ProcessPartialStatus(lRequestId, "MasterInfo.LiveOutdoorTemp_oC", jState["MasterInfo"]?["LiveOutdoorTemp_oC"]?.ToString(), ref unit.Data.OutdoorTemperature);

			// Live Humidity
			ProcessPartialStatus(lRequestId, "MasterInfo.LiveHumidity_pc", jState["MasterInfo"]?["LiveHumidity_pc"]?.ToString(), ref unit.Data.Humidity);

			// Coil Inlet Temperature
			ProcessPartialStatus(lRequestId, "LiveAircon.CoilInlet", jState["LiveAircon"]?["CoilInlet"]?.ToString(), ref unit.Data.CoilInletTemperature);

			// Fan PWM
			ProcessPartialStatus(lRequestId, "LiveAircon.FanPWM", jState["LiveAircon"]?["FanPWM"]?.ToString(), ref unit.Data.FanPWM);

			// Fan RPM
			ProcessPartialStatus(lRequestId, "LiveAircon.FanRPM", jState["LiveAircon"]?["FanRPM"]?.ToString(), ref unit.Data.FanRPM);

			// Filter
			ProcessPartialStatus(lRequestId, "Alerts.CleanFilter", jState["Alerts"]?["CleanFilter"]?.ToString(), ref unit.Data.CleanFilter);

			// Fan Time Since Filter Cleaned
			ProcessPartialStatus(lRequestId, "ACStats.NV_FanRunTime_10m", jState["ACStats"]?["NV_FanRunTime_10m"]?.ToString(), ref unit.Data.FanTSFC);

			// Zones
			if (aEnabledZones == null || aEnabledZones.Count != 8)
				Logging.WriteDebugLog("Que.ProcessFullStatus() Unable to read state information: UserAirconSettings.EnabledZones");
			else
			{
				for (int iZoneIndex = 0; iZoneIndex < unit.Zones.Count; iZoneIndex++)
				{
					if (unit.Zones[iZoneIndex + 1].Exists)
					{
						// Enabled
						ProcessPartialStatus(lRequestId, "UserAirconSettings.EnabledZones", aEnabledZones[iZoneIndex].ToString(), ref unit.Zones[iZoneIndex + 1].State);

						// Temperature
						ProcessPartialStatus(lRequestId, $"RemoteZoneInfo[{iZoneIndex}].LiveTemp_oC", jState["RemoteZoneInfo"]?[iZoneIndex]?["LiveTemp_oC"]?.ToString(), ref unit.Zones[iZoneIndex + 1].Temperature);

						// Cooling Set Temperature
						ProcessPartialStatus(lRequestId, $"RemoteZoneInfo[{iZoneIndex}].TemperatureSetpoint_Cool_oC", jState["RemoteZoneInfo"]?[iZoneIndex]?["TemperatureSetpoint_Cool_oC"]?.ToString(), ref unit.Zones[iZoneIndex + 1].SetTemperatureCooling);

						// Heating Set Temperature
						ProcessPartialStatus(lRequestId, $"RemoteZoneInfo[{iZoneIndex}].TemperatureSetpoint_Heat_oC", jState["RemoteZoneInfo"]?[iZoneIndex]?["TemperatureSetpoint_Heat_oC"]?.ToString(), ref unit.Zones[iZoneIndex + 1].SetTemperatureHeating);

						// Position
						ProcessPartialStatus(lRequestId, $"RemoteZoneInfo[{iZoneIndex}].ZonePosition", jState["RemoteZoneInfo"]?[iZoneIndex]?["ZonePosition"]?.ToString(), ref unit.Zones[iZoneIndex + 1].Position);

						// Zone Sensors Temperature
						var rti = jState["RemoteZoneInfo"]?[iZoneIndex];
						if (rti != null && rti["RemoteTemperatures_oC"] is JObject remoteTemps)
						{
							foreach (JProperty sensor in remoteTemps.Properties())
							{
								if (unit.Zones[iZoneIndex + 1].Sensors.ContainsKey(sensor.Name))
								{
									ProcessPartialStatus(lRequestId, $"RemoteZoneInfo[{iZoneIndex}].RemoteTemperatures_oC.{sensor.Name}", remoteTemps[sensor.Name]?.ToString(), ref unit.Zones[iZoneIndex + 1].Sensors[sensor.Name].Temperature);
								}
							}
						}

						// Zone Sensors Battery
						if (rti != null && rti["Sensors"] is JObject sensorsObj)
						{
							foreach (JProperty sensor in sensorsObj.Properties())
							{
								if (unit.Zones[iZoneIndex + 1].Sensors.ContainsKey(sensor.Name))
								{
									ProcessPartialStatus(lRequestId, $"RemoteZoneInfo[{iZoneIndex}].Sensors.{sensor.Name}.Battery_pc", sensorsObj[sensor.Name]?["Battery_pc"]?.ToString(), ref unit.Zones[iZoneIndex + 1].Sensors[sensor.Name].Battery);
								}
							}
						}
					}
				}
			}
		}

		private static void ProcessPartialStatus<T>(long lRequestId, string strName, string strValue, ref T target)
		{
			if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessPartialStatus() Change: {0}", strName);

			// string handling
			if (typeof(T) == typeof(string))
			{
				if ((strValue ?? "") == "")
				{
					Logging.WriteDebugLog("Que.ProcessPartialStatus() Unable to read state information: {0}", strName);
				}
				else
				{
					lock (_oLockData)
					{
						// cast via object to avoid generic constraints
						target = (T)(object)strValue;
					}
				}
				return;
			}

			// bool handling
			if (typeof(T) == typeof(bool))
			{
				if (!bool.TryParse(strValue ?? "", out bool bTemp))
				{
					Logging.WriteDebugLog("Que.ProcessPartialStatus() Unable to read state information: {0}", strName);
				}
				else
				{
					lock (_oLockData)
					{
						target = (T)(object)bTemp;
					}
				}
				return;
			}

			// double handling
			if (typeof(T) == typeof(double))
			{
				if (!double.TryParse(strValue ?? "", out double dblTemp))
				{
					Logging.WriteDebugLog("Que.ProcessPartialStatus() Unable to read state information: {0}", strName);
				}
				else
				{
					lock (_oLockData)
					{
						target = (T)(object)dblTemp;
					}
				}
				return;
			}

			// Fallback: unsupported target type
			Logging.WriteDebugLog("Que.ProcessPartialStatus() Unsupported target type: {0} for {1}", typeof(T).FullName, strName);
		}
	}
}