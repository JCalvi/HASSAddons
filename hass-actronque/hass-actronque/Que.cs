using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
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
			Logging.WriteDebugLog("Que.Que(v2026.1.6.9)");
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

		private static async Task<bool> GeneratePairingToken()
		{
			HttpResponseMessage httpResponse = null;
			CancellationTokenSource cancellationToken = null;
			Dictionary<string, string> dtFormContent = new Dictionary<string, string>();
			long lRequestId = RequestManager.GetRequestId();
			string strPageURL = "api/v0/client/user-devices";
			string strResponse;
			bool bRetVal = true;

			Logging.WriteDebugLog("Que.GeneratePairingToken()");

			if (_strDeviceUniqueIdentifier == "")
			{
				_strDeviceUniqueIdentifier = GenerateDeviceId();
				Logging.WriteDebugLog("Que.GeneratePairingToken() Device Id: {0}", _strDeviceUniqueIdentifier);

				// Update Device Id File
				try
				{
					await File.WriteAllTextAsync(_strDeviceIdFile, JsonConvert.SerializeObject(_strQueUser + "," + _strDeviceUniqueIdentifier)).ConfigureAwait(false);
				}
				catch (Exception eException)
				{
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", eException, "Unable to update device id json file.");
				}
			}

			dtFormContent.Add("username", _strQueUser);
			dtFormContent.Add("password", _strQuePassword);
			dtFormContent.Add("deviceName", _strDeviceName);
			dtFormContent.Add("client", "ios");
			dtFormContent.Add("deviceUniqueIdentifier", _strDeviceUniqueIdentifier);

			try
			{
				cancellationToken = new CancellationTokenSource();
				cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

				// Use resilient helper with retries
				httpResponse = await SendWithRetriesAsync(() =>
				{
					var req = new HttpRequestMessage(HttpMethod.Post, strPageURL)
					{
						Content = new FormUrlEncodedContent(dtFormContent)
					};
					return req;
				}, _httpClientAuth, -1, cancellationToken.Token).ConfigureAwait(false);

				if (httpResponse.IsSuccessStatusCode)
				{
					strResponse = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);

					var jsonResponse = JObject.Parse(strResponse);
					var pairingTokenValue = (string)jsonResponse["pairingToken"];
					if (!string.IsNullOrEmpty(pairingTokenValue))
					{
						_pairingToken = new PairingToken(pairingTokenValue);

						// Update Token File
						try
						{
							await File.WriteAllTextAsync(_strPairingTokenFile, JsonConvert.SerializeObject(_pairingToken)).ConfigureAwait(false);
						}
						catch (Exception eException)
						{
							Logging.WriteDebugLogError("Que.GeneratePairingToken()", eException, "Unable to update pairing token json file.");
						}
					}
					else
					{
						Logging.WriteDebugLogError("Que.GeneratePairingToken()", lRequestId, "pairingToken not found in response.");
						bRetVal = false;
					}
				}
				else
				{
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", lRequestId, $"Unable to process API response: {httpResponse.StatusCode}/{httpResponse.ReasonPhrase}");
					bRetVal = false;
					goto Cleanup;
				}
			}
			catch (OperationCanceledException eException)
			{
				Logging.WriteDebugLogError("Que.GeneratePairingToken()", eException, "HTTP operation timed out.");
				bRetVal = false;
				goto Cleanup;
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", lRequestId, eException.InnerException, "Exception in HTTP response processing.");
				else
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", lRequestId, eException, "Exception in HTTP response processing.");

				bRetVal = false;
				goto Cleanup;
			}

		Cleanup:
			cancellationToken?.Dispose();
			httpResponse?.Dispose();

			if (!bRetVal)
				_pairingToken = null;

			return bRetVal;
		}

		private static async Task<bool> GenerateBearerToken()
		{
			HttpResponseMessage httpResponse = null;
			CancellationTokenSource cancellationToken = null;
			Dictionary<string, string> dtFormContent = new Dictionary<string, string>();
			QueToken queToken = null;
			long lRequestId = RequestManager.GetRequestId();
			string strPageURL = "api/v0/oauth/token";
			string strResponse;
			bool bRetVal = true;

			Logging.WriteDebugLog("Que.GenerateBearerToken()");

			dtFormContent.Add("grant_type", "refresh_token");
			dtFormContent.Add("refresh_token", _pairingToken.Token);
			dtFormContent.Add("client_id", "app");

			try
			{
				cancellationToken = new CancellationTokenSource();
				cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

				httpResponse = await SendWithRetriesAsync(() =>
				{
					var req = new HttpRequestMessage(HttpMethod.Post, strPageURL)
					{
						Content = new FormUrlEncodedContent(dtFormContent)
					};
					return req;
				}, _httpClientAuth, -1, cancellationToken.Token).ConfigureAwait(false);

				if (httpResponse.IsSuccessStatusCode)
				{
					strResponse = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);

					var jsonResponse = JObject.Parse(strResponse);

					queToken = new QueToken();
					queToken.BearerToken = (string)jsonResponse["access_token"];
					var expiresInStr = (string)jsonResponse["expires_in"];
					if (int.TryParse(expiresInStr, out int expiresIn))
						queToken.TokenExpires = DateTime.Now.AddSeconds(expiresIn);
					else
						queToken.TokenExpires = DateTime.Now.AddSeconds(3600); // fallback

					_queToken = queToken;

					_httpClient.DefaultRequestHeaders.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", _queToken.BearerToken);
					_httpClientCommands.DefaultRequestHeaders.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", _queToken.BearerToken);

					// Update Token File
					try
					{
						await File.WriteAllTextAsync(_strBearerTokenFile, JsonConvert.SerializeObject(_queToken)).ConfigureAwait(false);
					}
					catch (Exception eException)
					{
						Logging.WriteDebugLogError("Que.GenerateBearerToken()", eException, "Unable to update bearer token json file.");
					}
				}
				else
				{
					if (httpResponse.StatusCode == System.Net.HttpStatusCode.Unauthorized)
					{
						Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, "Unauthorized - refreshing pairing token.");
						_pairingToken = null;
					}
					else if (httpResponse.StatusCode == System.Net.HttpStatusCode.BadRequest)
					{
						System.Threading.Interlocked.Increment(ref _iFailedBearerRequests);

						if (_iFailedBearerRequests == _iFailedBearerRequestMaximum)
						{
							Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, "BadRequest - reached max failed attempts, clearing pairing token.");
							_pairingToken = null;
						}
						else
							Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, $"BadRequest attempt {_iFailedBearerRequests} of {_iFailedBearerRequestMaximum}");
					}
					else
						Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, $"HTTP error: {httpResponse.StatusCode}/{httpResponse.ReasonPhrase}");

					bRetVal = false;
					goto Cleanup;
				}
			}
			catch (OperationCanceledException eException)
			{
				Logging.WriteDebugLogError("Que.GenerateBearerToken()", eException, "HTTP operation timed out.");
				bRetVal = false;
				goto Cleanup;
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, eException.InnerException, "Exception in HTTP response processing.");
				else
					Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, eException, "Exception in HTTP response processing.");

				bRetVal = false;
				goto Cleanup;
			}

			// Reset Failed Request Counter
			_iFailedBearerRequests = 0;

		Cleanup:
			cancellationToken?.Dispose();
			httpResponse?.Dispose();

			if (!bRetVal)
				_queToken = null;

			return bRetVal;
		}

		private static async Task TokenMonitor()
		{
			WaitHandle[] waitHandles = new WaitHandle[] { _eventStop, _eventAuthenticationFailure };
			int iWaitHandle = 0;
			bool bExit = false;

			Logging.WriteDebugLog("Que.TokenMonitor()");

			if (_pairingToken == null)
			{
				if (await GeneratePairingToken().ConfigureAwait(false))
					await GenerateBearerToken().ConfigureAwait(false);
			}
			else
				await GenerateBearerToken().ConfigureAwait(false);

			while (!bExit)
			{
				iWaitHandle = WaitHandle.WaitAny(waitHandles, TimeSpan.FromSeconds(_iAuthenticationInterval));

				switch (iWaitHandle)
				{
					case 0: // Stop
						bExit = true;
						break;

					case 1: // Authentication Failure
						if (_pairingToken == null)
						{
							if (await GeneratePairingToken().ConfigureAwait(false))
								await GenerateBearerToken().ConfigureAwait(false);
						}
						else
							await GenerateBearerToken().ConfigureAwait(false);
						break;

					case WaitHandle.WaitTimeout: // Wait Timeout
						if (_pairingToken == null)
						{
							if (await GeneratePairingToken().ConfigureAwait(false))
								await GenerateBearerToken().ConfigureAwait(false);
						}
						else if (_queToken == null)
							await GenerateBearerToken().ConfigureAwait(false);
						else if (_queToken != null && _queToken.TokenExpires <= DateTime.Now.Add(TimeSpan.FromMinutes(5)))
						{
							Logging.WriteDebugLog("Que.TokenMonitor() Refreshing expiring bearer token");
							await GenerateBearerToken().ConfigureAwait(false);
						}
						break;
				}
			}

			Logging.WriteDebugLog("Que.TokenMonitor() Complete");
		}

		private async static Task<bool> GetAirConditionerSerial()
		{
			AirConditionerUnit unit;
			HttpResponseMessage httpResponse = null;
			CancellationTokenSource cancellationToken = null;
			long lRequestId = RequestManager.GetRequestId();
			string strPageURL = "api/v0/client/ac-systems?includeAcms=true&includeNeo=true";
			string strResponse;
			bool bRetVal = true;
			string strSerial, strDescription, strType;

			Logging.WriteDebugLog("Que.GetAirConditionerSerial()");

			if (!IsTokenValid())
			{
				bRetVal = false;
				goto Cleanup;
			}

			try
			{
				cancellationToken = new CancellationTokenSource();
				cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

				httpResponse = await SendWithRetriesAsync(() =>
				{
					return new HttpRequestMessage(HttpMethod.Get, strPageURL);
				}, _httpClient, -1, cancellationToken.Token).ConfigureAwait(false);

				if (httpResponse.IsSuccessStatusCode)
				{
					strResponse = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);

					// normalize key name that might differ
					strResponse = strResponse.Replace("ac-system", "acsystem");

					if (!strResponse.Contains("acsystem"))
					{
						Logging.WriteDebugLog("Que.GetAirConditionerSerial() No data returned from Que service - check credentials.");
						bRetVal = false;
						goto Cleanup;
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
				else
				{
					if (httpResponse.StatusCode == System.Net.HttpStatusCode.Unauthorized)
					{
						Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, "Unauthorized response.");
						_eventAuthenticationFailure.Set();
					}
					else
						Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, $"HTTP error {httpResponse.StatusCode}");

					bRetVal = false;
					goto Cleanup;
				}
			}
			catch (OperationCanceledException eException)
			{
				Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, eException, "Operation timed out.");
				bRetVal = false;
				goto Cleanup;
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, eException.InnerException, "Exception.");
				else
					Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, eException, "Exception.");
				bRetVal = false;
				goto Cleanup;
			}

		Cleanup:
			cancellationToken?.Dispose();
			httpResponse?.Dispose();

			return bRetVal;
		}

		private async static Task<bool> GetAirConditionerZones()
		{
			HttpResponseMessage httpResponse = null;
			CancellationTokenSource cancellationToken = null;
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
					goto Cleanup;
				}

				try
				{
					cancellationToken = new CancellationTokenSource();
					cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

					httpResponse = await SendWithRetriesAsync(() =>
					{
						return new HttpRequestMessage(HttpMethod.Get, strPageURL + unit.Serial);
					}, _httpClient, -1, cancellationToken.Token).ConfigureAwait(false);

					if (httpResponse.IsSuccessStatusCode)
					{
						strResponse = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);
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
					else
					{
						if (httpResponse.StatusCode == System.Net.HttpStatusCode.Unauthorized)
						{
							Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, "Unauthorized response.");
							_eventAuthenticationFailure.Set();
						}
						else
							Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, $"HTTP error {httpResponse.StatusCode}");

						bRetVal = false;
						goto Cleanup;
					}
				}
				catch (OperationCanceledException eException)
				{
					Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, eException, "Operation timed out.");
					bRetVal = false;
					goto Cleanup;
				}
				catch (Exception eException)
				{
					if (eException.InnerException != null)
						Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, eException.InnerException, "Exception.");
					else
						Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, eException, "Exception.");
					bRetVal = false;
					goto Cleanup;
				}

			Cleanup:
				cancellationToken?.Dispose();
				httpResponse?.Dispose();
			}

			return bRetVal;
		}

		private async static Task<UpdateItems> GetAirConditionerFullStatus(AirConditionerUnit unit)
		{
			HttpResponseMessage httpResponse = null;
			CancellationTokenSource cancellationToken = null;
			long lRequestId = RequestManager.GetRequestId();
			string strPageURL = "api/v0/client/ac-systems/status/latest?serial=";
			string strResponse;
			UpdateItems updateItems = UpdateItems.None;
			if (_bQueLogging) Logging.WriteDebugLog("Que.GetAirConditionerFullStatus() for unit {0}", unit.Serial);

			if (!IsTokenValid())
				goto Cleanup;

			try
			{
				cancellationToken = new CancellationTokenSource();
				cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

				httpResponse = await SendWithRetriesAsync(() => new HttpRequestMessage(HttpMethod.Get, strPageURL + unit.Serial), _httpClient, -1, cancellationToken.Token).ConfigureAwait(false);

				if (httpResponse.IsSuccessStatusCode)
				{
					strResponse = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);
					if (_bQueLogging) Logging.WriteDebugLog("Que.GetAirConditionerFullStatus() response received");

					lock (_oLockData)
					{
						unit.Data.LastUpdated = DateTime.Now;
					}

					var jsonResponse = JObject.Parse(strResponse);

					var lastKnownState = jsonResponse["lastKnownState"] as JObject ?? new JObject();

					ProcessFullStatus(lRequestId, unit, lastKnownState);

					// mark all items as updated (main + zones present)
					updateItems = UpdateItems.Main;
					for (int i = 1; i <= 8; i++)
						updateItems |= (UpdateItems)(1 << i);
				}
				else
				{
					if (httpResponse.StatusCode == System.Net.HttpStatusCode.Unauthorized)
					{
						Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, "Unauthorized response.");
						_eventAuthenticationFailure.Set();
					}
					else
						Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, $"HTTP error {httpResponse.StatusCode}");

					goto Cleanup;
				}
			}
			catch (OperationCanceledException eException)
			{
				Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, eException, "Operation timed out.");
				goto Cleanup;
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, eException.InnerException, "Exception.");
				else
					Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, eException, "Exception.");
				goto Cleanup;
			}

		Cleanup:
			cancellationToken?.Dispose();
			httpResponse?.Dispose();

			return updateItems;
		}

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

		private static void ProcessPartialStatus(long lRequestId, string strName, string strValue, ref double dblTarget)
		{
			double dblTemp = 0.0;

			if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessPartialStatus() Change: {0}", strName);

			if (!double.TryParse(strValue ?? "", out dblTemp))
				Logging.WriteDebugLog("Que.ProcessPartialStatus() Unable to read state information: {0}", strName);
			else
			{
				lock (_oLockData)
				{
					dblTarget = dblTemp;
				}
			}
		}

		private static void ProcessPartialStatus(long lRequestId, string strName, string strValue, ref string strTarget)
		{
			if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessPartialStatus() Change: {0}", strName);

			if ((strValue ?? "") == "")
				Logging.WriteDebugLog("Que.ProcessPartialStatus() Unable to read state information: {0}", strName);
			else
			{
				lock (_oLockData)
				{
					strTarget = strValue;
				}
			}
		}

		private static void ProcessPartialStatus(long lRequestId, string strName, string strValue, ref bool bTarget)
		{
			bool bTemp;

			if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessPartialStatus() Change: {0}", strName);

			if (!bool.TryParse(strValue ?? "", out bTemp))
				Logging.WriteDebugLog("Que.ProcessPartialStatus() Unable to read state information: {0}", strName);
			else
			{
				lock (_oLockData)
				{
					bTarget = bTemp;
				}
			}
		}

		private async static Task<UpdateItems> GetAirConditionerEvents(AirConditionerUnit unit)
		{
			HttpResponseMessage httpResponse = null;
			CancellationTokenSource cancellationToken = null;
			long lRequestId = RequestManager.GetRequestId();
			string strPageURL, strPageURLFirstEvent = "api/v0/client/ac-systems/events/latest?serial=";
			string strResponse;
			bool bRetVal = true;
			string strEventType;
			int iIndex = 0;
			UpdateItems updateItems = UpdateItems.None;

			strPageURL = string.IsNullOrEmpty(unit.NextEventURL) ? strPageURLFirstEvent + unit.Serial : unit.NextEventURL;

			Logging.WriteDebugLog("Que.GetAirConditionerEvents() Unit: {0}", unit.Serial);

			if (!IsTokenValid())
			{
				bRetVal = false;
				goto Cleanup;
			}

			try
			{
				cancellationtoken: ;
				cancellationToken = new CancellationTokenSource();
				cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

				httpResponse = await SendWithRetriesAsync(() => new HttpRequestMessage(HttpMethod.Get, strPageURL), _httpClient, -1, cancellationToken.Token).ConfigureAwait(false);

				if (httpResponse.IsSuccessStatusCode)
				{
					strResponse = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);

					lock (_oLockData)
					{
						unit.Data.LastUpdated = DateTime.Now;
					}

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
						strEventType = (string)ev?["type"];

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

										// use the ProcessPartialStatus mapping as in original
										if (change.Name == "LiveAircon.CompressorMode")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.CompressorState);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "LiveAircon.CompressorCapacity")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.CompressorCapacity);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "LiveAircon.OutdoorUnit.CompPower")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.CompressorPower);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "UserAirconSettings.Mode")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.Mode);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "UserAirconSettings.FanMode")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.FanMode);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "UserAirconSettings.isOn")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.On);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "UserAirconSettings.AwayMode")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.AwayMode);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "UserAirconSettings.QuietMode")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.QuietMode);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "MasterInfo.ControlAllZones")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.ControlAllZones);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "MasterInfo.LiveTemp_oC")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.Temperature);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "MasterInfo.LiveOutdoorTemp_oC")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.OutdoorTemperature);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "MasterInfo.LiveHumidity_pc")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.Humidity);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "UserAirconSettings.TemperatureSetpoint_Cool_oC")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.SetTemperatureCooling);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "UserAirconSettings.TemperatureSetpoint_Heat_oC")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.SetTemperatureHeating);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "LiveAircon.CoilInlet")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.CoilInletTemperature);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "LiveAircon.FanPWM")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.FanPWM);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "LiveAircon.FanRPM")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.FanRPM);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "Alerts.CleanFilter")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.CleanFilter);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name == "ACStats.NV_FanRunTime_10m")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.FanTSFC);
											updateItems |= UpdateItems.Main;
										}
										else if (change.Name.StartsWith("RemoteZoneInfo["))
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
										}
										else if (change.Name.StartsWith("UserAirconSettings.EnabledZones["))
										{
											iIndex = ExtractIndexFromBracket(change.Name);
											if (iIndex >= 0 && unit.Zones.ContainsKey(iIndex + 1))
											{
												ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Zones[iIndex + 1].State);
												updateItems |= UpdateItems.Main;
												updateItems |= (UpdateItems)(1 << (iIndex + 1));
											}
										}
									}
								}
								break;

							case "full-status-broadcast":
								var dataFull = ev["data"] as JObject ?? new JObject();
								ProcessFullStatus(lRequestId, unit, dataFull);

								updateItems |= UpdateItems.Main;
								for (int i = 1; i <= 8; i++)
									updateItems |= (UpdateItems)(1 << i);
								break;
						}
					}
				}
				else
				{
					if (httpResponse.StatusCode == System.Net.HttpStatusCode.NotFound)
						Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, "NotFound - check serial.");
					else if (httpResponse.StatusCode == System.Net.HttpStatusCode.Unauthorized)
					{
						Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, "Unauthorized response.");
						_eventAuthenticationFailure.Set();
					}
					else
						Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, $"HTTP error {httpResponse.StatusCode}");

					bRetVal = false;
					goto Cleanup;
				}
			}
			catch (OperationCanceledException eException)
			{
				Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, eException, "Operation timed out.");
				bRetVal = false;
				goto Cleanup;
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, eException.InnerException, "Exception.");
				else
					Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, eException, "Exception.");

				bRetVal = false;
				goto Cleanup;
			}

		Cleanup:
			cancellationToken?.Dispose();
			httpResponse?.Dispose();

			if (!bRetVal)
				unit.NextEventURL = "";

			return updateItems;
		}

		private static async Task AirConditionerMonitor()
		{
			WaitHandle[] waitHandles = new WaitHandle[] { _eventStop, _eventUpdate };
			int iWaitHandle = 0, iWaitInterval = 5;
			bool bExit = false;
			UpdateItems updateItems = UpdateItems.None;

			Logging.WriteDebugLog("Que.AirConditionerMonitor()");

			while (!bExit)
			{
				updateItems = UpdateItems.None;

				iWaitHandle = WaitHandle.WaitAny(waitHandles, TimeSpan.FromSeconds(iWaitInterval));

				switch (iWaitHandle)
				{
					case 0: // Stop
						bExit = true;
						break;

					case 1: // Pull Update
						Logging.WriteDebugLog("Que.AirConditionerMonitor() Quick Update");

						await Task.Delay(_iPostCommandSleepTimerNeoNoEventsMode * 1000).ConfigureAwait(false);

						foreach (AirConditionerUnit unit in _airConditionerUnits.Values)
						{
							updateItems = await GetAirConditionerFullStatus(unit).ConfigureAwait(false);
							if (updateItems != UpdateItems.None)
							{
								MQTTUpdateData(unit, updateItems);
								MQTT.Update(null);
							}
						}
						break;

					case WaitHandle.WaitTimeout: // Wait Timeout
						if (_airConditionerUnits.Count == 0)
						{
							if (!await GetAirConditionerSerial().ConfigureAwait(false))
								continue;
						}

						if (_iZoneCount == 0)
						{
							if (!await GetAirConditionerZones().ConfigureAwait(false))
								continue;
							else
								MQTTRegister();
						}

						foreach (AirConditionerUnit unit in _airConditionerUnits.Values)
						{
							updateItems = await GetAirConditionerFullStatus(unit).ConfigureAwait(false);
							if (updateItems != UpdateItems.None)
							{
								MQTTUpdateData(unit, updateItems);
								MQTT.Update(null);
							}
						}
						break;
				}
				iWaitInterval = _iPollInterval;
			}

			Logging.WriteDebugLog("Que.AirConditionerMonitor() Complete");
		}

		private static async Task QueueMonitor()
		{
			WaitHandle[] waitHandles = new WaitHandle[] { _eventStop, _eventQueue };
			int iWaitHandle = 0;
			bool bExit = false;

			Logging.WriteDebugLog("Que.QueueMonitor()");

			while (!bExit)
			{
				iWaitHandle = WaitHandle.WaitAny(waitHandles, TimeSpan.FromSeconds(_iQueueInterval));

				switch (iWaitHandle)
				{
					case 0: // Stop
						bExit = true;
						break;

					case 1: // Queue Updated
						if (!IsTokenValid())
							continue;

						if (await ProcessQueue().ConfigureAwait(false))
							_eventUpdate.Set();

						break;

					case WaitHandle.WaitTimeout: // Wait Timeout
						if (!IsTokenValid())
							continue;

						if (await ProcessQueue().ConfigureAwait(false))
							_eventUpdate.Set();

						break;
				}
			}

			Logging.WriteDebugLog("Que.QueueMonitor() Complete");
		}

		private static async Task<bool> ProcessQueue()
		{
			QueueCommand command;
			bool bRetVal = false;
			if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessQueue()");

			while (true)
			{
				lock (_oLockQueue)
				{
					if (_queueCommands.Count > 0)
					{
						command = _queueCommands.Peek();
						if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessQueue() Attempting Command: 0x{0}", command.RequestId.ToString("X8"));

						if (command.Expires <= DateTime.Now)
						{
							Logging.WriteDebugLog("Que.ProcessQueue() Command Expired: 0x{0}", command.RequestId.ToString("X8"));

							SendMQTTFailedCommandAlert(command);

							_queueCommands.Dequeue();

							continue;
						}
					}
					else
						command = null;
				}

				if (command == null)
					break;

				if (await SendCommand(command).ConfigureAwait(false))
				{
					lock (_oLockQueue)
					{
						Logging.WriteDebugLog("Que.ProcessQueue() Command Complete: 0x{0}", command.RequestId.ToString("X8"));
						_queueCommands.Dequeue();

						bRetVal = true;
					}
				}
			}
			if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessQueue() Complete");

			return bRetVal;
		}

		private static bool IsTokenValid()
		{
			return _queToken != null && _queToken.TokenExpires > DateTime.Now;
		}

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
						current_hvac_action_topic = $"actronque{unit. Serial}/compressor",
						modes = new[] { "off", "auto", "cool", "heat", "fan_only" },
						fan_modes = new[] { "auto", "low", "medium", "high" },
						min_temp = 10,
						max_temp = 32,
						temp_step = 0.5,
						temperature_unit = "C",
						device = deviceInfo
					}));

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
						payload_on = "on",
						payload_off = "off",
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
						payload_on = "on",
						payload_off = "off",
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
						payload_on = "on",
						payload_off = "off",
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
						payload_on = "on",
						payload_off = "off",
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
						payload_on = "on",
						payload_off = "off",
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
								payload_on = "on",
								payload_off = "off",
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
							MQTT.SendMessage(string.Format("homeassistant/climate/actronque{0}/zone{1}/config", strHANameModifier, iZone),
								JsonConvert.SerializeObject(new
								{
									name = $"{zone.Name}",
									unique_id = $"{unit.Serial}-z{iZone}-climate",
									default_entity_id = $"climate.actronque_{unit.Serial}_zone_{iZone}",
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
											default_entity_id = $"sensor.actronque_{unit.Serial}_zone_{iZone}_sensor_{sensor}_battery",
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
				MQTT.SendMessage(string.Format("actronque{0}/cleanfilter", unit.Serial), unit.Data.CleanFilter ? "on" : "off");
				MQTT.SendMessage(string.Format("actronque{0}/fantsfc", unit.Serial), (unit.Data.FanTSFC / 6).ToString("F0"));

				// Control/Away/Quiet/Constant Fan
				MQTT.SendMessage(string.Format("actronque{0}/controlallzones", unit.Serial), unit.Data.ControlAllZones ? "on" : "off");
				MQTT.SendMessage(string.Format("actronque{0}/awaymode", unit.Serial), unit.Data.AwayMode ? "on" : "off");
				MQTT.SendMessage(string.Format("actronque{0}/quietmode", unit.Serial), unit.Data.QuietMode ? "on" : "off");
				MQTT.SendMessage(string.Format("actronque{0}/constantfanmode", unit.Serial), unit.Data.ConstantFanMode ? "on" : "off");
			}

			// Zones
			foreach (int iIndex in unit.Zones.Keys)
			{
				if (unit.Zones[iIndex].Exists && items.HasFlag((UpdateItems)(1 << iIndex)))
				{
					MQTT.SendMessage(string.Format("actronque{0}/zone{1}", unit.Serial, iIndex), unit.Zones[iIndex].State ? "on" : "off");
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
		
		private static string SanitizeName(string name)
		{
			// Convert to lowercase, replace spaces/special chars with underscores, trim extra underscores
			return System. Text.RegularExpressions. Regex.Replace(name.ToLower(), @"[^a-z0-9_]", "_").Trim('_');
		}		

		private static void AddCommandToQueue(QueueCommand command)
		{
			if (_bQueLogging) Logging.WriteDebugLog("Que.AddCommandToQueue() New Command ID: 0x{0}", command.RequestId.ToString("X8"));

			// add pending expectations & optimistic publishes
			AddPendingFromCommand(command);

			lock (_oLockQueue)
			{
				_queueCommands.Enqueue(command);
				_eventQueue.Set();
			}
		}

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

		private static async Task<bool> SendCommand(QueueCommand command)
		{
			HttpResponseMessage httpResponse = null;
			CancellationTokenSource cancellationToken = null;
			long lRequestId = RequestManager.GetRequestId(command.RequestId);
			string strPageURL = "api/v0/client/ac-systems/cmds/send?serial=";
			bool bRetVal = true;

			if (_bQueLogging) Logging.WriteDebugLog("Que.SendCommand() Original Request ID: 0x{0}", command.OriginalRequestId.ToString("X8"));
			if (_bQueLogging) Logging.WriteDebugLog("Que.SendCommand() Sending to serial {0}", command.Unit.Serial);

			try
			{
				cancellationToken = new CancellationTokenSource();
				cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

				httpResponse = await SendWithRetriesAsync(() =>
				{
					var req = new HttpRequestMessage(HttpMethod.Post, strPageURL + command.Unit.Serial)
					{
						Content = new StringContent(JsonConvert.SerializeObject(command.Data), Encoding.UTF8, "application/json")
					};
					return req;
				}, _httpClientCommands, -1, cancellationToken.Token).ConfigureAwait(false);

				if (httpResponse.IsSuccessStatusCode)
					Logging.WriteDebugLog("Que.SendCommand() Response OK");
				else
				{
					if (httpResponse.StatusCode == System.Net.HttpStatusCode.NotFound)
						Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, "NotFound - check serial.");
					else if (httpResponse.StatusCode == System.Net.HttpStatusCode.Unauthorized)
					{
						Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, "Unauthorized response.");
						_eventAuthenticationFailure.Set();
					}
					else
						Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, $"HTTP error {httpResponse.StatusCode}");

					bRetVal = false;
					goto Cleanup;
				}
			}
			catch (OperationCanceledException eException)
			{
				Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, eException, "Operation timed out.");
				bRetVal = false;
				goto Cleanup;
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, eException.InnerException, "Exception.");
				else
					Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, eException, "Exception.");
				bRetVal = false;
				goto Cleanup;
			}

		Cleanup:
			cancellationToken?.Dispose();
			httpResponse?.Dispose();

			return bRetVal;
		}

		private static void SendMQTTFailedCommandAlert(QueueCommand command)
		{
			Logging.WriteDebugLog("Que.SendMQTTFailedCommandAlert() Command failed: {0}", command.RequestId.ToString());
			MQTT.SendMessage(string.Format("actronque{0}/lastfailedcommand", command.Unit.Serial), command.RequestId.ToString());
		}

		private static string GenerateDeviceId()
		{
			Random random = new Random();
			int iLength = 25;

			StringBuilder sbDeviceId = new StringBuilder();

			for (int iIndex = 0; iIndex < iLength; iIndex++)
				sbDeviceId.Append(random.Next(0, 9));

			return sbDeviceId.ToString();
		}
	}
}