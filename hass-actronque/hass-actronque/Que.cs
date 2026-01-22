using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace HMX.HASSActronQue
{
	public partial class Que
	{
		public static Dictionary<string, AirConditionerUnit> Units
		{
			get { return _airConditionerUnits; }
		}

		static Que()
		{
			// Use helper to create HttpClients with pooling controls
			RecreateHttpClients();

			// updated version marker for this build
			Logging.WriteDebugLog("Que.Que(v2026.1.6.20)");
		}

		// Changed to Task so callers can observe failures
		// Note: eventStop is the ManualResetEvent used elsewhere
		public static async Task Initialise(string strQueUser, string strQuePassword, string strSerialNumber, string strDeviceName, bool bQueLogs, bool bPerZoneControls, bool bSeparateHeatCool, bool bShowBatterySensors, ManualResetEvent eventStop)
		{
			string strDeviceUniqueIdentifierInput;
			string[] strTokens;

			Logging.WriteDebugLog("Que.Initialise()");

			_strQueUser = strQueUser;
			_strQuePassword = strQuePassword;
			_strSerialNumber = strSerialNumber;
			_strDeviceName = strDeviceName;
			_bQueLogging = bQueLogs;
			_bPerZoneControls = bPerZoneControls;
			_bSeparateHeatCool = bSeparateHeatCool;
			_bShowBatterySensors = bShowBatterySensors;
			_eventStop = eventStop;

			_httpClientAuth.BaseAddress = new Uri(_strBaseURLQue);
			_httpClient.BaseAddress = new Uri(_strBaseURLQue);
			_httpClientCommands.BaseAddress = new Uri(_strBaseURLQue);

			// Get Device Id
			try
			{
				if (File.Exists(_strDeviceIdFile))
				{
					strDeviceUniqueIdentifierInput = JsonConvert.DeserializeObject<string>(await File.ReadAllTextAsync(_strDeviceIdFile).ConfigureAwait(false));

					if (strDeviceUniqueIdentifierInput.Contains(","))
					{
						strTokens = strDeviceUniqueIdentifierInput.Split(new char[] { ',' });
						if (strTokens.Length == 2)
						{
							if (strTokens[0].ToLower() == _strQueUser.ToLower())
							{
								_strDeviceUniqueIdentifier = strTokens[1];

								Logging.WriteDebugLog("Que.Initialise() Device Id: {0}", _strDeviceUniqueIdentifier);
							}
							else
							{
								Logging.WriteDebugLog("Que.Initialise() Device Id: will regenerate (Que User changed)");
							}
						}
					}
					else
					{
						_strDeviceUniqueIdentifier = strDeviceUniqueIdentifierInput;

						// Update Device Id File
						try
						{
							await File.WriteAllTextAsync(_strDeviceIdFile, JsonConvert.SerializeObject(_strQueUser + "," + _strDeviceUniqueIdentifier)).ConfigureAwait(false);
						}
						catch (Exception eException)
						{
							Logging.WriteDebugLogError("Que.Initialise()", eException, "Unable to update device id json file.");
						}
					}
				}
			}
			catch (Exception eException)
			{
				Logging.WriteDebugLogError("Que.Initialise()", eException, "Unable to read device json file.");
			}

			// Get Pairing Token
			try
			{
				if (_strDeviceUniqueIdentifier != "" && File.Exists(_strPairingTokenFile))
				{
					_pairingToken = JsonConvert.DeserializeObject<PairingToken>(await File.ReadAllTextAsync(_strPairingTokenFile).ConfigureAwait(false));
					Logging.WriteDebugLog("Que.Initialise() Restored Pairing Token");
				}
			}
			catch (Exception eException)
			{
				Logging.WriteDebugLogError("Que.Initialise()", eException, "Unable to read pairing token json file.");
			}

			// Start monitors as background Tasks to integrate with async/await better.
			Task.Run(TokenMonitor);
			Task.Run(AirConditionerMonitor);
			Task.Run(QueueMonitor);
		}

		// NOTE: The following methods were intentionally moved to focused partial files:
		// - Que.Auth.cs: GeneratePairingToken, GenerateBearerToken
		// - Que.Monitors.cs: TokenMonitor, AirConditionerMonitor, QueueMonitor
		// - Que.Commands.cs: ProcessQueue, SendCommand, AddCommandToQueue, SendMQTTFailedCommandAlert
		// - Que.MQTT.cs: MQTTRegister, MQTTUpdateData
		// - Que.StatusProcessing.cs: ProcessFullStatus, ProcessPartialStatus
		//
		// Their implementations now live in the matching partial files. Calls remain in this file and refer to those implementations.

		private static bool IsTokenValid()
		{
			return _queToken != null && _queToken.TokenExpires > DateTime.Now;
		}

		private async static Task<bool> GetAirConditionerSerial()
		{
			AirConditionerUnit unit;
			long lRequestId = RequestManager.GetRequestId();
			string strPageURL = "api/v0/client/ac-systems?includeAcms=true&includeNeo=true";
			bool bRetVal = true;
			string strSerial, strDescription, strType;

			Logging.WriteDebugLog("Que.GetAirConditionerSerial()");

			if (!IsTokenValid())
			{
				bRetVal = false;
				return bRetVal;
			}

			var result = await ExecuteRequestAsync(() => new HttpRequestMessage(HttpMethod.Get, strPageURL), _httpClient, -1, lRequestId).ConfigureAwait(false);

			if (!result.Success)
			{
				if (result.StatusCode == System.Net.HttpStatusCode.Unauthorized)
				{
					Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, "Unauthorized response.");
					_eventAuthenticationFailure.Set();
				}
				else
					Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, $"HTTP error {result.StatusCode}");

				bRetVal = false;
				return bRetVal;
			}

			try
			{
				var strResponse = result.Content;

				// normalize key name that might differ
				strResponse = strResponse.Replace("ac-system", "acsystem");

				if (!strResponse.Contains("acsystem"))
				{
					Logging.WriteDebugLog("Que.GetAirConditionerSerial() No data returned from Que service - check credentials.");
					bRetVal = false;
					return bRetVal;
				}

				var jsonResponse = JObject.Parse(strResponse);
				var embedded = jsonResponse["_embedded"] as JObject;
				if (embedded != null)
				{
					var acsystems = embedded["acsystem"] as JArray;
					if (acsystems != null)
					{
						for (int iIndex = 0; iIndex < acsystems.Count; iIndex++)
						{
							var ac = acsystems[iIndex];
							strSerial = (string)ac["serial"];
							strDescription = (string)ac["description"];
							strType = (string)ac["type"];

							Logging.WriteDebugLog("Que.GetAirConditionerSerial() Found AC: {0} - {1} ({2})", strSerial, strDescription, strType);

							if (_strSerialNumber == "" || _strSerialNumber == strSerial)
							{
								unit = new AirConditionerUnit(strDescription?.Trim() ?? "Unknown", strSerial);
								_airConditionerUnits.Add(strSerial, unit);

								Logging.WriteDebugLog("Que.GetAirConditionerSerial() Monitoring AC: {0}", strSerial);
							}
						}
					}
				}
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, eException.InnerException, "Exception.");
				else
					Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, eException, "Exception.");
				bRetVal = false;
			}

			return bRetVal;
		}

		private async static Task<bool> GetAirConditionerZones()
		{
			long lRequestId = RequestManager.GetRequestId();
			string strPageURL = "api/v0/client/ac-systems/status/latest?serial=";
			string strResponse;
			bool bRetVal = true;
			AirConditionerZone zone;
			AirConditionerSensor sensor;

			_iZoneCount = 0;

			foreach (AirConditionerUnit unit in _airConditionerUnits.Values)
			{
				Logging.WriteDebugLog("Que.GetAirConditionerZones() Processing unit {0}", unit.Serial);

				if (!IsTokenValid())
				{
					bRetVal = false;
					return bRetVal;
				}

				var result = await ExecuteRequestAsync(() => new HttpRequestMessage(HttpMethod.Get, strPageURL + unit.Serial), _httpClient, -1, lRequestId).ConfigureAwait(false);

				if (!result.Success)
				{
					if (result.StatusCode == System.Net.HttpStatusCode.Unauthorized)
					{
						Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, "Unauthorized response.");
						_eventAuthenticationFailure.Set();
					}
					else
						Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, $"HTTP error {result.StatusCode}");

					bRetVal = false;
					return bRetVal;
				}

				try
				{
					strResponse = result.Content;
					var jsonResponse = JObject.Parse(strResponse);

					// Zones
					if (jsonResponse.TryGetValue("lastKnownState", out JToken lastKnownStateToken) && lastKnownStateToken is JObject lastKnownState && lastKnownState.TryGetValue("RemoteZoneInfo", out JToken remoteZoneInfoToken) && remoteZoneInfoToken is JArray remoteZoneInfo)
					{
						for (int iZoneIndex = 0; iZoneIndex < remoteZoneInfo.Count; iZoneIndex++)
						{
							var zoneInfo = remoteZoneInfo[iZoneIndex];
							bool exists = false;
							var nvExistsToken = zoneInfo["NV_Exists"];
							if (nvExistsToken != null)
								bool.TryParse(nvExistsToken.ToString(), out exists);

							if (exists)
							{
								zone = new AirConditionerZone();
								zone.Sensors = new Dictionary<string, AirConditionerSensor>();
								zone.Exists = true;

								zone.Name = (string)zoneInfo["NV_Title"];
								if (string.IsNullOrEmpty(zone.Name))
									zone.Name = "Zone " + (iZoneIndex + 1);
								zone.Temperature = (double?)(zoneInfo["LiveTemp_oC"]) ?? 0.0;

								if (zoneInfo is JObject z && z.TryGetValue("Sensors", out JToken sensorsToken) && sensorsToken is JObject sensorsObj)
								{
									foreach (JProperty sensorJson in sensorsObj.Properties())
									{
										sensor = new AirConditionerSensor();
										sensor.Name = zone.Name + " Sensor " + sensorJson.Name;
										sensor.Serial = sensorJson.Name;
										zone.Sensors.Add(sensorJson.Name, sensor);
									}
								}
							}
							else
							{
								zone = new AirConditionerZone();
								zone.Sensors = new Dictionary<string, AirConditionerSensor>();
								zone.Exists = false;
							}

							unit.Zones.Add(iZoneIndex + 1, zone);
							_iZoneCount++;
						}
					}
					else
					{
						Logging.WriteDebugLog("Que.GetAirConditionerZones() No zone data returned; will retry.");
					}
				}
				catch (Exception eException)
				{
					if (eException.InnerException != null)
						Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, eException.InnerException, "Exception.");
					else
						Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, eException, "Exception.");
					bRetVal = false;
					return bRetVal;
				}
			}

			return bRetVal;
		}

		private async static Task<UpdateItems> GetAirConditionerFullStatus(AirConditionerUnit unit)
		{
			long lRequestId = RequestManager.GetRequestId();
			string strPageURL = "api/v0/client/ac-systems/status/latest?serial=";
			UpdateItems updateItems = UpdateItems.None;
			if (_bQueLogging) Logging.WriteDebugLog("Que.GetAirConditionerFullStatus() for unit {0}", unit.Serial);

			if (!IsTokenValid())
				return UpdateItems.None;

			var result = await ExecuteRequestAsync(() => new HttpRequestMessage(HttpMethod.Get, strPageURL + unit.Serial), _httpClient, -1, lRequestId).ConfigureAwait(false);

			if (!result.Success)
			{
				if (result.StatusCode == System.Net.HttpStatusCode.Unauthorized)
				{
					Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, "Unauthorized response.");
					_eventAuthenticationFailure.Set();
				}
				else
					Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, $"HTTP error {result.StatusCode}");

				return UpdateItems.None;
			}

			try
			{
				var strResponse = result.Content;
				if (_bQueLogging) Logging.WriteDebugLog("Que.GetAirConditionerFullStatus() response received");

				lock (_oLockData)
				{
					unit.Data.LastUpdated = DateTime.Now;
				}

				var jsonResponse = JObject.Parse(strResponse);
				var lastKnownState = jsonResponse["lastKnownState"] as JObject ?? new JObject();

				// ProcessFullStatus implementation moved to Que.StatusProcessing.cs
				ProcessFullStatus(lRequestId, unit, lastKnownState);

				// mark all items as updated (main + zones present)
				updateItems = UpdateItems.Main;
				for (int i = 1; i <= 8; i++)
					updateItems |= (UpdateItems)(1 << i);
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, eException.InnerException, "Exception.");
				else
					Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, eException, "Exception.");
			}

			return updateItems;
		}

		private async static Task<UpdateItems> GetAirConditionerEvents(AirConditionerUnit unit)
		{
			long lRequestId = RequestManager.GetRequestId();
			string strPageURLFirstEvent = "api/v0/client/ac-systems/events/latest?serial=";
			string strPageURL = string.IsNullOrEmpty(unit.NextEventURL) ? strPageURLFirstEvent + unit.Serial : unit.NextEventURL;
			int iIndex = 0;
			UpdateItems updateItems = UpdateItems.None;

			Logging.WriteDebugLog("Que.GetAirConditionerEvents() Unit: {0}", unit.Serial);

			if (!IsTokenValid())
			{
				return UpdateItems.None;
			}

			var result = await ExecuteRequestAsync(() => new HttpRequestMessage(HttpMethod.Get, strPageURL), _httpClient, -1, lRequestId).ConfigureAwait(false);

			if (!result.Success)
			{
				if (result.StatusCode == System.Net.HttpStatusCode.NotFound)
					Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, "NotFound - check serial.");
				else if (result.StatusCode == System.Net.HttpStatusCode.Unauthorized)
				{
					Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, "Unauthorized response.");
					_eventAuthenticationFailure.Set();
				}
				else
					Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, $"HTTP error {result.StatusCode}");

				unit.NextEventURL = "";
				return UpdateItems.None;
			}

			try
			{
				var strResponse = result.Content;

				lock (_oLockData)
				{
					unit.Data.LastUpdated = DateTime.Now;
				}

				// Normalize event key name variation from upstream
				strResponse = strResponse.Replace("ac-newer-events", "acnewerevents");

				var jsonResponse = JObject.Parse(strResponse);

				var links = jsonResponse["_links"] as JObject;
				if (links != null && links["acnewerevents"] != null)
				{
					unit.NextEventURL = (string)links["acnewerevents"]["href"] ?? "";
					if (unit.NextEventURL.StartsWith("/"))
						unit.NextEventURL = unit.NextEventURL.Substring(1);
				}

				var events = jsonResponse["events"] as JArray ?? new JArray();

				for (int iEvent = events.Count - 1; iEvent >= 0; iEvent--)
				{
					var ev = events[iEvent] as JObject;
					string strEventType = (string)ev?["type"];

					if (_bQueLogging) Logging.WriteDebugLog("Que.GetAirConditionerEvents() Event Type: {0}", strEventType);

					switch (strEventType)
					{
						case "status-change-broadcast":
							var data = ev["data"] as JObject;
							if (data != null)
							{
								foreach (JProperty change in data.Properties())
								{
									if (_bQueLogging) Logging.WriteDebugLog("Que.GetAirConditionerEvents() Incremental Update: {0}", change.Name);

									// If this change confirms a pending optimistic expectation, confirm it
									ConfirmPendingForUnit(unit.Serial, change.Name, change.Value);

									// Fast-path mapped handlers for common top-level names (moved to Que.EventHandlers.cs)
									if (_statusChangeHandlers.TryGetValue(change.Name, out var handler))
									{
										updateItems |= handler(lRequestId, unit, change.Value);
										continue;
									}

									// Zone-indexed updates: RemoteZoneInfo[...] (per-zone values)
									if (change.Name.StartsWith("RemoteZoneInfo["))
									{
										iIndex = ExtractIndexFromBracket(change.Name);
										if (iIndex >= 0 && unit.Zones.ContainsKey(iIndex + 1))
										{
											updateItems |= (UpdateItems)(1 << (iIndex + 1));

											if (change.Name.EndsWith("].LiveTemp_oC"))
												ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Zones[iIndex + 1].Temperature);
											else if (change.Name.EndsWith("].TemperatureSetpoint_Cool_oC"))
												ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Zones[iIndex + 1].SetTemperatureCooling);
											else if (change.Name.EndsWith("].TemperatureSetpoint_Heat_oC"))
												ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Zones[iIndex + 1].SetTemperatureHeating);
											else if (change.Name.EndsWith("].ZonePosition"))
												ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Zones[iIndex + 1].Position);
										}
										continue;
									}

									// EnabledZones array items (master enable flags per zone)
									if (change.Name.StartsWith("UserAirconSettings.EnabledZones["))
									{
										iIndex = ExtractIndexFromBracket(change.Name);
										if (iIndex >= 0 && unit.Zones.ContainsKey(iIndex + 1))
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Zones[iIndex + 1].State);
											updateItems |= UpdateItems.Main;
											updateItems |= (UpdateItems)(1 << (iIndex + 1));
										}
										continue;
									}

									// Unhandled change: optional debug log
									if (_bQueLogging)
										Logging.WriteDebugLog("Que.GetAirConditionerEvents() Unhandled change: {0}", change.Name);
								}
							}
							break;

						case "full-status-broadcast":
							var dataFull = ev["data"] as JObject ?? new JObject();
							// full processing uses ProcessFullStatus moved to Que.StatusProcessing.cs
							ProcessFullStatus(lRequestId, unit, dataFull);

							updateItems |= UpdateItems.Main;
							for (int i = 1; i <= 8; i++)
								updateItems |= (UpdateItems)(1 << i);
							break;
					}
				}
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, eException.InnerException, "Exception.");
				else
					Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, eException, "Exception.");

				unit.NextEventURL = "";
				return UpdateItems.None;
			}

			return updateItems;
		}

		// MQTTRegister and MQTTUpdateData moved to Que.MQTT.cs

		private static double GetSetTemperature(double dblHeating, double dblCooling)
		{
			double dblSetTemperature = 0.0;
			if (_bQueLogging) Logging.WriteDebugLog("Que.GetSetTemperature()");

			try
			{
				dblSetTemperature = dblHeating + ((dblCooling - dblHeating) / 2);
				dblSetTemperature = Math.Round(dblSetTemperature * 2, MidpointRounding.AwayFromZero) / 2;
			}
			catch (Exception eException)
			{
				Logging.WriteDebugLogError("Que.GetSetTemperature()", eException, "Unable to determine set temperature mid-point.");
			}

			return dblSetTemperature;
		}

		// Command/queue helpers moved to Que.Commands.cs (ProcessQueue, SendCommand, AddCommandToQueue, SendMQTTFailedCommandAlert)

		public static void ChangeZone(long lRequestId, AirConditionerUnit unit, int iZone, bool bState)
		{
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));

			Logging.WriteDebugLog("Que.ChangeZone() Unit: {0}, Zone {1}: {2}", unit.Serial, iZone, bState ? "On" : "Off");

			command.Data.command.Add("type", "set-settings");
			command.Data.command.Add(string.Format("UserAirconSettings.EnabledZones[{0}]", iZone - 1), bState);

			AddCommandToQueue(command);
		}

		public static void ChangeControlAllZones(long lRequestId, AirConditionerUnit unit, bool bState)
		{
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));

			Logging.WriteDebugLog("Que.ChangeControlAllZones() Unit: {0}, Control All Zones: {1}", unit.Serial, bState ? "On" : "Off");

			command.Data.command.Add("type", "set-settings");
			command.Data.command.Add("MasterInfo.ControlAllZones", bState);

			AddCommandToQueue(command);
		}

		public static void AwayMode(long lRequestId, AirConditionerUnit unit, bool bState)
		{
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));
			Logging.WriteDebugLog("Que.AwayMode() Unit: {0}, Away mode: {1}", unit.Serial, bState ? "On" : "Off");
			command.Data.command.Add("type", "set-settings");
			command.Data.command.Add("UserAirconSettings.AwayMode", bState);
			AddCommandToQueue(command);
		}

		public static void QuietMode(long lRequestId, AirConditionerUnit unit, bool bState)
		{
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));
			Logging.WriteDebugLog("Que.QuietMode() Unit: {0}, Quiet mode: {1}", unit.Serial, bState ? "On" : "Off");
			command.Data.command.Add("type", "set-settings");
			command.Data.command.Add("UserAirconSettings.QuietMode", bState);
			AddCommandToQueue(command);
		}

		public static void ConstantFanMode(long lRequestId, AirConditionerUnit unit, bool bState)
		{
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));
			Logging.WriteDebugLog("Que.ConstantFanMode() Unit: {0}, Constant Fan mode: {1}", unit.Serial, bState ? "On" : "Off");

			// Preserve base fan mode without +CONT
			string current = unit?.Data?.FanMode ?? "AUTO";
			string baseFan = StripContSuffix(current).Trim();
			if (string.IsNullOrWhiteSpace(baseFan))
				baseFan = "AUTO";

			string newFan = bState ? (baseFan + "+CONT").ToUpperInvariant() : baseFan.ToUpperInvariant();

			command.Data.command.Add("UserAirconSettings.FanMode", newFan);
			command.Data.command.Add("type", "set-settings");
			AddCommandToQueue(command);
		}

		public static void ChangeMode(long lRequestId, AirConditionerUnit unit, AirConditionerMode mode)
		{
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));
			Logging.WriteDebugLog("Que.ChangeMode() Unit: {0}, Mode: {1}", unit.Serial, mode.ToString());

			switch (mode)
			{
				case AirConditionerMode.Off:
					command.Data.command.Add("UserAirconSettings.isOn", false);
					break;
				case AirConditionerMode.Automatic:
					command.Data.command.Add("UserAirconSettings.isOn", true);
					command.Data.command.Add("UserAirconSettings.Mode", "AUTO");
					break;
				case AirConditionerMode.Cool:
					command.Data.command.Add("UserAirconSettings.isOn", true);
					command.Data.command.Add("UserAirconSettings.Mode", "COOL");
					break;
				case AirConditionerMode.Fan_Only:
					command.Data.command.Add("UserAirconSettings.isOn", true);
					command.Data.command.Add("UserAirconSettings.Mode", "FAN");
					break;
				case AirConditionerMode.Heat:
					command.Data.command.Add("UserAirconSettings.isOn", true);
					command.Data.command.Add("UserAirconSettings.Mode", "HEAT");
					break;
			}

			command.Data.command.Add("type", "set-settings");
			AddCommandToQueue(command);
		}

		public static void ChangeFanMode(long lRequestId, AirConditionerUnit unit, FanMode fanMode)
		{
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));
			Logging.WriteDebugLog("Que.ChangeFanMode() Unit: {0}, Fan Mode: {1}", unit.Serial, fanMode.ToString());

			bool hasCont = (unit?.Data?.FanMode ?? "").IndexOf("+CONT", StringComparison.OrdinalIgnoreCase) >= 0;

			switch (fanMode)
			{
				case FanMode.Automatic:
					command.Data.command.Add("UserAirconSettings.FanMode", hasCont ? "AUTO+CONT" : "AUTO");
					break;
				case FanMode.Low:
					command.Data.command.Add("UserAirconSettings.FanMode", hasCont ? "LOW+CONT" : "LOW");
					break;
				case FanMode.Medium:
					command.Data.command.Add("UserAirconSettings.FanMode", hasCont ? "MED+CONT" : "MED");
					break;
				case FanMode.High:
					command.Data.command.Add("UserAirconSettings.FanMode", hasCont ? "HIGH+CONT" : "HIGH");
					break;
			}

			command.Data.command.Add("type", "set-settings");
			AddCommandToQueue(command);
		}

		public static void ChangeTemperature(long lRequestId, AirConditionerUnit unit, double dblTemperature, int iZone, TemperatureSetType setType)
		{
			string strCommandPrefix = "";
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));

			Logging.WriteDebugLog("Que.ChangeTemperature() Unit: {0}, Zone: {1}, Temperature: {2} ({3})", unit.Serial, iZone, dblTemperature, setType.ToString());

			if (iZone == 0)
				strCommandPrefix = "UserAirconSettings";
			else
				strCommandPrefix = string.Format("RemoteZoneInfo[{0}]", iZone - 1);

			switch (setType)
			{
				case TemperatureSetType.Default:
					switch (unit.Data.Mode)
					{
						case "OFF":
						case "FAN":
							return;
						case "COOL":
							command.Data.command.Add(string.Format("{0}.TemperatureSetpoint_Cool_oC", strCommandPrefix), dblTemperature);
							break;
						case "HEAT":
							command.Data.command.Add(string.Format("{0}.TemperatureSetpoint_Heat_oC", strCommandPrefix), dblTemperature);
							break;
						case "AUTO":
							command.Data.command.Add(string.Format("{0}.TemperatureSetpoint_Heat_oC", strCommandPrefix), dblTemperature);
							command.Data.command.Add(string.Format("{0}.TemperatureSetpoint_Cool_oC", strCommandPrefix), dblTemperature);
							break;
					}
					break;

				case TemperatureSetType.Low:
					command.Data.command.Add(string.Format("{0}.TemperatureSetpoint_Heat_oC", strCommandPrefix), dblTemperature);
					break;

				case TemperatureSetType.High:
					command.Data.command.Add(string.Format("{0}.TemperatureSetpoint_Cool_oC", strCommandPrefix), dblTemperature);
					break;
			}

			command.Data.command.Add("type", "set-settings");
			AddCommandToQueue(command);

			if (iZone == 0 && !unit.Data.ControlAllZones)
			{
				Logging.WriteDebugLog("Que.ChangeTemperature() Setting Control All Zones to True due to Master temperature change");
				ChangeControlAllZones(lRequestId, unit, true);
			}
		}

		private static string GenerateDeviceId()
		{
			Random random = new Random();
			int iLength = 25;

			StringBuilder sbDeviceId = new StringBuilder();

			for (int iIndex = 0; iIndex < iLength; iIndex++)
				sbDeviceId.Append(random.Next(0, 10));

			return sbDeviceId.ToString();
		}
	}
}