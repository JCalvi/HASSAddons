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
	public class Que
	{
		[Flags]
		public enum UpdateItems
		{
			None = 0,
			Main = 1,
			Zone1 = 2,
			Zone2 = 4,
			Zone3 = 8,
			Zone4 = 16,
			Zone5 = 32,
			Zone6 = 64,
			Zone7 = 128,
			Zone8 = 256
		}

		[Flags]
		public enum TemperatureSetType
		{
			Default,
			High,
			Low
		}

		private static string _strBaseURLQue = "https://que.actronair.com.au/";
		private static string _strDeviceName;
		private static string _strAirConditionerName = "Air Conditioner";
		private static string _strDeviceIdFile = "/data/deviceid.json";
		private static string _strPairingTokenFile = "/data/pairingtoken.json";
		private static string _strBearerTokenFile = "/data/bearertoken.json";
		private static string _strDeviceUniqueIdentifier = "";

		// centralized keys
		private static string controlAllZonesKey = "MasterInfo.ControlAllZones";
		private static string awayKey = "UserAirconSettings.AwayMode";
		private static string quietKey = "UserAirconSettings.QuietMode";

		private static string _strQueUser, _strQuePassword, _strSerialNumber;
		private static bool _bPerZoneControls = false;
		private static bool _bSeparateHeatCool = false;
		private static bool _bQueLogging = true;
		private static Queue<QueueCommand> _queueCommands = new Queue<QueueCommand>();
		private static HttpClient _httpClient = null, _httpClientAuth = null, _httpClientCommands = null;
		private static int _iCancellationTime = 15; // Seconds
		private static int _iPollInterval = 30; // Seconds
		private static int _iPollIntervalOn = 30; // Seconds
		private static int _iPollIntervalOff = 300; // Seconds		
		private static int _iAuthenticationInterval = 60; // Seconds
		private static int _iQueueInterval = 4; // Seconds
		private static int _iCommandExpiry = 12; // Seconds
		private static int _iPostCommandSleepTimerNeoNoEventsMode = 10; // Seconds
		private static int _iFailedBearerRequests = 0;
		private static int _iFailedBearerRequestMaximum = 10; // Retries
		private static int _iZoneCount = 0;
		private static ManualResetEvent _eventStop;
		private static AutoResetEvent _eventAuthenticationFailure = new AutoResetEvent(false);
		private static AutoResetEvent _eventQueue = new AutoResetEvent(false);
		private static AutoResetEvent _eventUpdate = new AutoResetEvent(false);
		private static PairingToken _pairingToken;
		private static QueToken _queToken = null;
		private static Dictionary<string, AirConditionerUnit> _airConditionerUnits = new Dictionary<string, AirConditionerUnit>();
		private static object _oLockData = new object(), _oLockQueue = new object();

		// optimistic/pending/suppression additions
		private static int _iPublishSuppressionSeconds = 6;
		public static int PublishSuppressionSeconds
		{
			get => _iPublishSuppressionSeconds;
			set
			{
				if (value < 0) value = 0;
				_iPublishSuppressionSeconds = value;
				if (_bQueLogging) Logging.WriteDebugLog("Que.PublishSuppressionSeconds set to {0}", _iPublishSuppressionSeconds);
			}
		}

		private class PendingCommand
		{
			public long RequestId;
			public string UnitSerial;
			public Dictionary<string, string> ExpectedValues = new Dictionary<string, string>(); // key -> expected stringified value
			public DateTime Expires;
		}
		private static List<PendingCommand> _pendingCommands = new List<PendingCommand>();
		private static object _oLockPending = new object();

		// per-unit suppression until times
		private static Dictionary<string, DateTime> _unitSuppressUntil = new Dictionary<string, DateTime>();
		private static object _oLockSuppress = new object();

		// helpers for pending and suppression
		private static void SetUnitSuppression(string unitSerial)
		{
			DateTime until = DateTime.Now.AddSeconds(_iPublishSuppressionSeconds);
			lock (_oLockSuppress)
			{
				_unitSuppressUntil[unitSerial] = until;
			}
			if (_bQueLogging) Logging.WriteDebugLog("Que.SetUnitSuppression() Unit: {0} suppressed until {1}", unitSerial, until);
		}

		private static bool IsUnitSuppressed(string unitSerial)
		{
			lock (_oLockSuppress)
			{
				if (_unitSuppressUntil.ContainsKey(unitSerial))
					return _unitSuppressUntil[unitSerial] > DateTime.Now;
				return false;
			}
		}

		private static void AddPendingFromCommand(QueueCommand command)
		{
			if (command == null || command.Unit == null) return;

			try
			{
				// Convert command.Data into JObject to inspect "command" properties safely
				JObject jo = JObject.FromObject(command.Data);
				JObject jCmd = jo["command"] as JObject;
				if (jCmd == null) return;

				PendingCommand pc = new PendingCommand() { RequestId = command.RequestId, UnitSerial = command.Unit.Serial, Expires = DateTime.Now.AddSeconds(_iPublishSuppressionSeconds) };

				foreach (var prop in jCmd.Properties())
				{
					string key = prop.Name;
					JToken val = prop.Value;

					// store stringified expected value
					pc.ExpectedValues[key] = val.Type == JTokenType.Null ? "" : val.ToString();

					// publish optimistic MQTT for a set of known keys
					try
					{
						PublishOptimistic(unitSerial: command.Unit.Serial, key: key, token: val);
					}
					catch (Exception ex)
					{
						Logging.WriteDebugLogError("Que.AddPendingFromCommand()", command.RequestId, ex, "Publish optimistic failed for key {0}", key);
					}
				}

				lock (_oLockPending)
				{
					_pendingCommands.Add(pc);
				}

				// suppression for unit to avoid immediate overwrites
				SetUnitSuppression(command.Unit.Serial);

				if (_bQueLogging) Logging.WriteDebugLog("Que.AddPendingFromCommand() [0x{0}] Unit: {1} Pending keys: {2}", command.RequestId.ToString("X8"), command.Unit.Serial, pc.ExpectedValues.Count);
			}
			catch (Exception e)
			{
				Logging.WriteDebugLogError("Que.AddPendingFromCommand()", command.RequestId, e, "Unable to add pending from command.");
			}
		}

		private static void PublishOptimistic(string unitSerial, string key, JToken token)
		{
			// Map known keys to MQTT topics and publish optimistic values
			if (string.IsNullOrEmpty(unitSerial) || string.IsNullOrEmpty(key)) return;

			// Helper to convert bool tokens
			string BoolToOnOff(JToken t) => (t != null && (t.Type == JTokenType.Boolean ? t.ToObject<bool>() : string.Equals(t.ToString(), "true", StringComparison.OrdinalIgnoreCase))) ? "ON" : "OFF";

			// numeric to one decimal
			string NumFmt(JToken t)
			{
				if (t == null) return "";
				if (double.TryParse(t.ToString(), out double d)) return d.ToString("N1");
				return t.ToString();
			}

			switch (key)
			{
				case string s when s == controlAllZonesKey:
					MQTT.SendMessage($"actronque{unitSerial}/controlallzones", BoolToOnOff(token));
					return;
				case string s when s == awayKey:
					MQTT.SendMessage($"actronque{unitSerial}/awaymode", BoolToOnOff(token));
					return;
				case string s when s == quietKey:
					MQTT.SendMessage($"actronque{unitSerial}/quietmode", BoolToOnOff(token));
					return;
				case "UserAirconSettings.isOn":
					// if false -> publish mode off; if true we don't set a specific mode here
					if (token != null && token.Type == JTokenType.Boolean && token.ToObject<bool>() == false)
						MQTT.SendMessage($"actronque{unitSerial}/mode", "off");
					return;
				case "UserAirconSettings.Mode":
					{
						string mode = token?.ToString() ?? "";
						switch (mode)
						{
							case "AUTO": MQTT.SendMessage($"actronque{unitSerial}/mode", "auto"); break;
							case "COOL": MQTT.SendMessage($"actronque{unitSerial}/mode", "cool"); break;
							case "HEAT": MQTT.SendMessage($"actronque{unitSerial}/mode", "heat"); break;
							case "FAN": MQTT.SendMessage($"actronque{unitSerial}/mode", "fan_only"); break;
							default: break;
						}
					}
					return;
				case "UserAirconSettings.FanMode":
					{
						// Publish both the base fan mode (auto/low/medium/high) AND the constantfanmode (ON/OFF)
						string f = token?.ToString() ?? "";
						bool hasCont = f.IndexOf("+CONT", StringComparison.OrdinalIgnoreCase) >= 0;

						// publish constantfanmode state (optimistic)
						MQTT.SendMessage($"actronque{unitSerial}/constantfanmode", hasCont ? "ON" : "OFF");

						// publish fanmode without +CONT for the fanmode topic
						if (f.StartsWith("AUTO", StringComparison.OrdinalIgnoreCase)) MQTT.SendMessage($"actronque{unitSerial}/fanmode", "auto");
						else if (f.StartsWith("LOW", StringComparison.OrdinalIgnoreCase)) MQTT.SendMessage($"actronque{unitSerial}/fanmode", "low");
						else if (f.StartsWith("MED", StringComparison.OrdinalIgnoreCase)) MQTT.SendMessage($"actronque{unitSerial}/fanmode", "medium");
						else if (f.StartsWith("HIGH", StringComparison.OrdinalIgnoreCase)) MQTT.SendMessage($"actronque{unitSerial}/fanmode", "high");
					}
					return;
				case "UserAirconSettings.TemperatureSetpoint_Cool_oC":
					MQTT.SendMessage($"actronque{unitSerial}/settemperature/high", NumFmt(token));
					// also set combined settemperature for master when available (best-effort)
					MQTT.SendMessage($"actronque{unitSerial}/settemperature", NumFmt(token));
					return;
				case "UserAirconSettings.TemperatureSetpoint_Heat_oC":
					MQTT.SendMessage($"actronque{unitSerial}/settemperature/low", NumFmt(token));
					// also set combined settemperature for master when available (best-effort)
					MQTT.SendMessage($"actronque{unitSerial}/settemperature", NumFmt(token));
					return;
				default:
					// Zone specific keys: EnabledZones[x] or RemoteZoneInfo[n].*
					if (key.StartsWith("UserAirconSettings.EnabledZones"))
					{
						// extract index
						int i = ExtractIndexFromBracket(key);
						if (i >= 0)
							MQTT.SendMessage($"actronque{unitSerial}/zone{i+1}", BoolToOnOff(token));
						return;
					}
					if (key.StartsWith("RemoteZoneInfo[") && key.Contains("TemperatureSetpoint"))
					{
						int i = ExtractIndexFromBracket(key);
						if (i >= 0)
						{
							if (key.EndsWith("TemperatureSetpoint_Cool_oC"))
								MQTT.SendMessage($"actronque{unitSerial}/zone{i+1}/settemperature/high", NumFmt(token));
							else if (key.EndsWith("TemperatureSetpoint_Heat_oC"))
								MQTT.SendMessage($"actronque{unitSerial}/zone{i+1}/settemperature/low", NumFmt(token));
						}
						return;
					}
					// fallback: do nothing
					return;
			}
		}

		private static int ExtractIndexFromBracket(string s)
		{
			try
			{
				int open = s.IndexOf("[");
				int close = s.IndexOf("]");
				if (open >= 0 && close > open)
				{
					string idx = s.Substring(open + 1, close - open - 1);
					if (int.TryParse(idx, out int i)) return i;
				}
			}
			catch { }
			return -1;
		}

		// Helper: strip trailing "+CONT" suffix (case-insensitive) if present
		private static string StripContSuffix(string fanMode)
		{
			if (string.IsNullOrEmpty(fanMode)) return fanMode ?? "";
			int idx = fanMode.IndexOf("+CONT", StringComparison.OrdinalIgnoreCase);
			if (idx >= 0)
				return fanMode.Substring(0, idx);
			return fanMode;
		}

		private static void ConfirmPendingForUnit(string unitSerial, string name, JToken value)
		{
			if (string.IsNullOrEmpty(unitSerial) || string.IsNullOrEmpty(name)) return;

			lock (_oLockPending)
			{
				bool changed = false;
				for (int i = _pendingCommands.Count - 1; i >= 0; i--)
				{
					var pc = _pendingCommands[i];
					if (pc.UnitSerial != unitSerial) continue;
					// only consider unexpired
					if (pc.Expires <= DateTime.Now)
					{
						_pendingCommands.RemoveAt(i);
						continue;
					}
					if (pc.ExpectedValues.TryGetValue(name, out string expected))
					{
						string actual = value == null ? "" : value.ToString();
						// compare normalized
						if (string.Equals(expected, actual, StringComparison.OrdinalIgnoreCase))
						{
							pc.ExpectedValues.Remove(name);
							changed = true;
						}
					}
					// if no expected values remain -> remove pending
					if (pc.ExpectedValues.Count == 0)
					{
						_pendingCommands.RemoveAt(i);
						changed = true;
					}
				}

				if (changed && _bQueLogging) Logging.WriteDebugLog("Que.ConfirmPendingForUnit() Unit: {0}, Name: {1} confirmed.", unitSerial, name);
			}

			// if no more pending for unit, clear suppression early
			bool hasAny = false;
			lock (_oLockPending)
			{
				hasAny = _pendingCommands.Any(p => p.UnitSerial == unitSerial && p.Expires > DateTime.Now);
			}
			if (!hasAny)
			{
				lock (_oLockSuppress)
				{
					if (_unitSuppressUntil.ContainsKey(unitSerial))
						_unitSuppressUntil.Remove(unitSerial);
				}
				if (_bQueLogging) Logging.WriteDebugLog("Que.ConfirmPendingForUnit() Unit: {0} cleared suppression (no pending expectations).", unitSerial);
			}
		}

		// returns true if there is any pending expectation for the unit (used optionally)
		private static bool HasAnyPendingForUnit(string unitSerial)
		{
			lock (_oLockPending)
			{
				return _pendingCommands.Any(p => p.UnitSerial == unitSerial && p.Expires > DateTime.Now);
			}
		}
		// end optimistic/pending/suppression additions

		public static Dictionary<string, AirConditionerUnit> Units
		{
			get { return _airConditionerUnits; }
		}

		static Que()
		{
			HttpClientHandler httpClientHandler = new HttpClientHandler();

			// updated version marker for this build
			Logging.WriteDebugLog("Que.Que(v2026.1.3.70.2)");

			if (httpClientHandler.SupportsAutomaticDecompression)
				httpClientHandler.AutomaticDecompression = System.Net.DecompressionMethods.All;

			_httpClientAuth = new HttpClient(httpClientHandler);
			_httpClient = new HttpClient(httpClientHandler);
			_httpClientCommands = new HttpClient(httpClientHandler);
			
		}

		public static async void Initialise(string strQueUser, string strQuePassword, string strSerialNumber, string strDeviceName, bool bQueLogs, bool bPerZoneControls, bool bSeparateHeatCool, ManualResetEvent eventStop)
		{
			Task taskMonitor;
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
							Logging.WriteDebugLogError("Que.Initialise()", eException, "Unable to update json file.");
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

			Logging.WriteDebugLog("Que.GeneratePairingToken() [0x{0}] Base: {1}{2}", lRequestId.ToString("X8"), _strBaseURLQue, strPageURL);

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
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", eException, "Unable to update json file.");
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

				httpResponse = await _httpClientAuth.PostAsync(strPageURL, new FormUrlEncodedContent(dtFormContent), cancellationToken.Token).ConfigureAwait(false);

				if (httpResponse.IsSuccessStatusCode)
				{
					strResponse = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);

					Logging.WriteDebugLog("Que.GeneratePairingToken() [0x{0}] Responded (Encoding {1}, {2} bytes)", lRequestId.ToString("X8"), httpResponse.Content.Headers.ContentEncoding.ToString() == "" ? "N/A" : httpResponse.Content.Headers.ContentEncoding.ToString(), (httpResponse.Content.Headers.ContentLength ?? 0) == 0 ? "N/A" : httpResponse.Content.Headers.ContentLength.ToString());

					// Parse to JObject safely
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
							Logging.WriteDebugLogError("Que.GeneratePairingToken()", eException, "Unable to update json file.");
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
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", lRequestId, "Unable to process API response: {0}/{1}", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);
					bRetVal = false;
					goto Cleanup;
				}
			}
			catch (OperationCanceledException eException)
			{
				Logging.WriteDebugLogError("Que.GeneratePairingToken()", lRequestId, eException, "Unable to process API HTTP response - operation timed out.");

				bRetVal = false;
				goto Cleanup;
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", lRequestId, eException.InnerException, "Unable to process API HTTP response.");
				else
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", lRequestId, eException, "Unable to process API HTTP response.");

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

			Logging.WriteDebugLog("Que.GenerateBearerToken() [0x{0}] Base: {1}{2}", lRequestId.ToString("X8"), _httpClientAuth.BaseAddress, strPageURL);

			dtFormContent.Add("grant_type", "refresh_token");
			dtFormContent.Add("refresh_token", _pairingToken.Token);
			dtFormContent.Add("client_id", "app");

			try
			{
				cancellationToken = new CancellationTokenSource();
				cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

				httpResponse = await _httpClientAuth.PostAsync(strPageURL, new FormUrlEncodedContent(dtFormContent), cancellationToken.Token).ConfigureAwait(false);

				if (httpResponse.IsSuccessStatusCode)
				{
					strResponse = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);

					Logging.WriteDebugLog("Que.GenerateBearerToken() [0x{0}] Responded (Encoding {1}, {2} bytes)", lRequestId.ToString("X8"), httpResponse.Content.Headers.ContentEncoding.ToString() == "" ? "N/A" : httpResponse.Content.Headers.ContentEncoding.ToString(), (httpResponse.Content.Headers.ContentLength ?? 0) == 0 ? "N/A" : httpResponse.Content.Headers.ContentLength.ToString());

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
						Logging.WriteDebugLogError("Que.GenerateBearerToken()", eException, "Unable to update json file.");
					}
				}
				else
				{
					if (httpResponse.StatusCode == System.Net.HttpStatusCode.Unauthorized)
					{
						Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, "Unable to process API response: {0}/{1}. Refreshing pairing token.", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);

						_pairingToken = null;
					}
					else if (httpResponse.StatusCode == System.Net.HttpStatusCode.BadRequest)
					{
						// Increment Failed Request Counter
						System.Threading.Interlocked.Increment(ref _iFailedBearerRequests);

						// Reset Pairing Token when Failed Request Counter reaches maximum.
						if (_iFailedBearerRequests == _iFailedBearerRequestMaximum)
						{
							Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, "Unable to process API response: {0}/{1}. Attempt: {2} of {3} - refreshing pairing token.", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase, _iFailedBearerRequests, _iFailedBearerRequestMaximum);

							_pairingToken = null;
						}
						else
							Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, "Unable to process API response: {0}/{1}. Attempt: {2} of {3}", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase, _iFailedBearerRequests, _iFailedBearerRequestMaximum);
					}
					else
						Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, "Unable to process API response: {0}/{1}", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);

					bRetVal = false;
					goto Cleanup;
				}
			}
			catch (OperationCanceledException eException)
			{
				Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, eException, "Unable to process API HTTP response - operation timed out.");

				bRetVal = false;
				goto Cleanup;
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, eException.InnerException, "Unable to process API HTTP response.");
				else
					Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, eException, "Unable to process API HTTP response.");

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
						else if (_queToken != null && _queToken.TokenExpires <= DateTime.Now.Subtract(TimeSpan.FromMinutes(5)))
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

			Logging.WriteDebugLog("Que.GetAirConditionerSerial() [0x{0}] Base: {1}{2}", lRequestId.ToString("X8"), _httpClient.BaseAddress, strPageURL);

			if (!IsTokenValid())
			{
				bRetVal = false;
				goto Cleanup;
			}

			try
			{
				cancellationToken = new CancellationTokenSource();
				cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

				httpResponse = await _httpClient.GetAsync(strPageURL, cancellationToken.Token).ConfigureAwait(false);

				if (httpResponse.IsSuccessStatusCode)
				{
					strResponse = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);

					Logging.WriteDebugLog("Que.GetAirConditionerSerial() [0x{0}] Responded (Encoding {1}, {2} bytes)", lRequestId.ToString("X8"), httpResponse.Content.Headers.ContentEncoding.ToString() == "" ? "N/A" : httpResponse.Content.Headers.ContentEncoding.ToString(), (httpResponse.Content.Headers.ContentLength ?? 0) == 0 ? "N/A" : httpResponse.Content.Headers.ContentLength.ToString());

					strResponse = strResponse.Replace("ac-system", "acsystem");

					if (!strResponse.Contains("acsystem"))
					{
						Logging.WriteDebugLog("Que.GetAirConditionerSerial() [0x{0}] No data returned from Que service - check Que user name and password.");
						
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

								Logging.WriteDebugLog("Que.GetAirConditionerSerial() [0x{0}] Found AC: {1} - {2} ({3})", lRequestId.ToString("X8"), strSerial, strDescription, strType);

								if (_strSerialNumber == "" || _strSerialNumber == strSerial)
								{
									unit = new AirConditionerUnit(strDescription.Trim(), strSerial);
									_airConditionerUnits.Add(strSerial, unit);

									Logging.WriteDebugLog("Que.GetAirConditionerSerial() [0x{0}] Monitoring AC: {1}", lRequestId.ToString("X8"), strSerial);
								}
							}
						}
					}
				}
				else
				{
					if (httpResponse.StatusCode == System.Net.HttpStatusCode.Unauthorized)
					{
						Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, "Unable to process API response: {0}/{1}", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);

						_eventAuthenticationFailure.Set();
					}
					else
						Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, "Unable to process API response: {0}/{1}", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);

					bRetVal = false;
					goto Cleanup;
				}
			}
			catch (OperationCanceledException eException)
			{
				Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, eException, "Unable to process API HTTP response - operation timed out.");

				bRetVal = false;
				goto Cleanup;
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, eException.InnerException, "Unable to process API HTTP response.");
				else
					Logging.WriteDebugLogError("Que.GetAirConditionerSerial()", lRequestId, eException, "Unable to process API HTTP response.");

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
				Logging.WriteDebugLog("Que.GetAirConditionerZones() [0x{0}] Base: {1}{2}{3}", lRequestId.ToString("X8"), _httpClient.BaseAddress, strPageURL, unit.Serial);

				if (!IsTokenValid())
				{
					bRetVal = false;
					goto Cleanup;
				}

				try
				{
					cancellationToken = new CancellationTokenSource();
					cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

					httpResponse = await _httpClient.GetAsync(strPageURL + unit.Serial, cancellationToken.Token).ConfigureAwait(false);

					if (httpResponse.IsSuccessStatusCode)
					{
						strResponse = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);

						Logging.WriteDebugLog("Que.GetAirConditionerZones() [0x{0}] Responded (Encoding {1}, {2} bytes)", lRequestId.ToString("X8"), httpResponse.Content.Headers.ContentEncoding.ToString() == "" ? "N/A" : httpResponse.Content.Headers.ContentEncoding.ToString(), (httpResponse.Content.Headers.ContentLength ?? 0) == 0 ? "N/A" : httpResponse.Content.Headers.ContentLength.ToString());

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

									Logging.WriteDebugLog("Que.GetAirConditionerZones() [0x{0}] Zone: {1} - {2}", lRequestId.ToString("X8"), iZoneIndex + 1, zone.Name);

									if (zoneInfo is JObject z && z.TryGetValue("Sensors", out JToken sensorsToken) && sensorsToken is JObject sensorsObj)
									{
										foreach (JProperty sensorJson in sensorsObj.Properties())
										{
											sensor = new AirConditionerSensor();
											sensor.Name = zone.Name + " Sensor " + sensorJson.Name;
											sensor.Serial = sensorJson.Name;

											Logging.WriteDebugLog("Que.GetAirConditionerZones() [0x{0}] Zone Sensor: {1}", lRequestId.ToString("X8"), sensorJson.Name);

											zone.Sensors.Add(sensorJson.Name, sensor);
										}
									}
								}
								else
								{
									zone = new AirConditionerZone();
									zone.Sensors = new Dictionary<string, AirConditionerSensor>();
									zone.Exists = false;

									Logging.WriteDebugLog("Que.GetAirConditionerZones() [0x{0}] Zone: {1} - Non Existent Zone", lRequestId.ToString("X8"), iZoneIndex + 1);
								}

								unit.Zones.Add(iZoneIndex + 1, zone);
								_iZoneCount++;
							}
						}
						else
						{
							Logging.WriteDebugLog("Que.GetAirConditionerZones() [0x{0}] Responded - No Data. Retrying.", lRequestId.ToString("X8"));
						}
					}
					else
					{
						if (httpResponse.StatusCode == System.Net.HttpStatusCode.Unauthorized)
						{
							Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, "Unable to process API response: {0}/{1}", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);

							_eventAuthenticationFailure.Set();
						}
						else
							Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, "Unable to process API response: {0}/{1}. Is the serial number correct?", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);

						bRetVal = false;
						goto Cleanup;
					}
				}
				catch (OperationCanceledException eException)
				{
					Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, eException, "Unable to process API HTTP response - operation timed out.");

					bRetVal = false;
					goto Cleanup;
				}
				catch (Exception eException)
				{
					if (eException.InnerException != null)
						Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, eException.InnerException, "Unable to process API HTTP response. Is the serial number correct?");
					else
						Logging.WriteDebugLogError("Que.GetAirConditionerZones()", lRequestId, eException, "Unable to process API HTTP response. Is the serial number correct?");

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
			if (_bQueLogging) Logging.WriteDebugLog("Que.GetAirConditionerFullStatus() [0x{0}] Base: {1}{2}{3}", lRequestId.ToString("X8"), _httpClient.BaseAddress, strPageURL, unit.Serial);

			if (!IsTokenValid())
				goto Cleanup;

			try
			{
				cancellationToken = new CancellationTokenSource();
				cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

				httpResponse = await _httpClient.GetAsync(strPageURL + unit.Serial, cancellationToken.Token).ConfigureAwait(false);

				if (httpResponse.IsSuccessStatusCode)
				{
					strResponse = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);
					if (_bQueLogging)
						Logging.WriteDebugLog("Que.GetAirConditionerFullStatus() [0x{0}] Responded (Encoding {1}, {2} bytes)", lRequestId.ToString("X8"), httpResponse.Content.Headers.ContentEncoding.ToString() == "" ? "N/A" : httpResponse.Content.Headers.ContentEncoding.ToString(), (httpResponse.Content.Headers.ContentLength ?? 0) == 0 ? "N/A" : httpResponse.Content.Headers.ContentLength.ToString());

					lock (_oLockData)
					{
						unit.Data.LastUpdated = DateTime.Now;
					}

					var jsonResponse = JObject.Parse(strResponse);

					var lastKnownState = jsonResponse["lastKnownState"] as JObject ?? new JObject();

					ProcessFullStatus(lRequestId, unit, lastKnownState);

					updateItems = UpdateItems.Main | UpdateItems.Zone1 | UpdateItems.Zone2 | UpdateItems.Zone3 | UpdateItems.Zone4 | UpdateItems.Zone5 | UpdateItems.Zone6 | UpdateItems.Zone7 | UpdateItems.Zone8;
				}
				else
				{
					if (httpResponse.StatusCode == System.Net.HttpStatusCode.Unauthorized)
					{
						Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, "Unable to process API response: {0}/{1}", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);

						_eventAuthenticationFailure.Set();
					}
					else
						Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, "Unable to process API response: {0}/{1}. Is the serial number correct?", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);

					goto Cleanup;
				}
			}
			catch (OperationCanceledException eException)
			{
				Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, eException, "Unable to process API HTTP response - operation timed out.");

				goto Cleanup;
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, eException.InnerException, "Unable to process API HTTP response. Is the serial number correct?");
				else
					Logging.WriteDebugLogError("Que.GetAirConditionerFullStatus()", lRequestId, eException, "Unable to process API HTTP response. Is the serial number correct?");

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
			if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessFullStatus() [0x{0}] Unit: {1}", lRequestId.ToString("X8"), unit.Serial);
		
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
				Logging.WriteDebugLog("Que.GetAirConditionerFullStatus() [0x{0}] Unable to read state information: {1}", lRequestId.ToString("X8"), "UserAirconSettings.EnabledZones");
			else
			{
				for (int iZoneIndex = 0; iZoneIndex < unit.Zones.Count; iZoneIndex++)
				{
					if (unit.Zones[iZoneIndex + 1].Exists)
					{
						// Enabled
						ProcessPartialStatus(lRequestId, "UserAirconSettings.EnabledZones", aEnabledZones[iZoneIndex].ToString(), ref unit.Zones[iZoneIndex + 1].State);

						// Temperature
						ProcessPartialStatus(lRequestId, string.Format("RemoteZoneInfo[{0}].LiveTemp_oC", iZoneIndex), jState["RemoteZoneInfo"]?[iZoneIndex]?["LiveTemp_oC"]?.ToString(), ref unit.Zones[iZoneIndex + 1].Temperature);

						// Cooling Set Temperature
						ProcessPartialStatus(lRequestId, string.Format("RemoteZoneInfo[{0}].TemperatureSetpoint_Cool_oC", iZoneIndex), jState["RemoteZoneInfo"]?[iZoneIndex]?["TemperatureSetpoint_Cool_oC"]?.ToString(), ref unit.Zones[iZoneIndex + 1].SetTemperatureCooling);

						// Heating Set Temperature
						ProcessPartialStatus(lRequestId, string.Format("RemoteZoneInfo[{0}].TemperatureSetpoint_Heat_oC", iZoneIndex), jState["RemoteZoneInfo"]?[iZoneIndex]?["TemperatureSetpoint_Heat_oC"]?.ToString(), ref unit.Zones[iZoneIndex + 1].SetTemperatureHeating);

						// Position
						ProcessPartialStatus(lRequestId, string.Format("RemoteZoneInfo[{0}].ZonePosition", iZoneIndex), jState["RemoteZoneInfo"]?[iZoneIndex]?["ZonePosition"]?.ToString(), ref unit.Zones[iZoneIndex + 1].Position);

						// Zone Sensors Temperature
						var rti = jState["RemoteZoneInfo"]?[iZoneIndex];
						if (rti != null && rti["RemoteTemperatures_oC"] is JObject remoteTemps)
						{
							foreach (JProperty sensor in remoteTemps.Properties())
							{
								if (unit.Zones[iZoneIndex + 1].Sensors.ContainsKey(sensor.Name))
								{
									ProcessPartialStatus(lRequestId, string.Format("RemoteZoneInfo[{0}].RemoteTemperatures_oC.{1}", iZoneIndex, sensor.Name), remoteTemps[sensor.Name]?.ToString(), ref unit.Zones[iZoneIndex + 1].Sensors[sensor.Name].Temperature);
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
									ProcessPartialStatus(lRequestId, string.Format("RemoteZoneInfo[{0}].Sensors.{1}.Battery_pc", iZoneIndex, sensor.Name), sensorsObj[sensor.Name]?["Battery_pc"]?.ToString(), ref unit.Zones[iZoneIndex + 1].Sensors[sensor.Name].Battery);
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

			if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessPartialStatus() [0x{0}] Change: {1}", lRequestId.ToString("X8"), strName);

			if (!double.TryParse(strValue ?? "", out dblTemp))
				Logging.WriteDebugLog("Que.ProcessPartialStatus() [0x{0}] Unable to read state information: {1}", lRequestId.ToString("X8"), strName);
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
			if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessPartialStatus() [0x{0}] Change: {1}", lRequestId.ToString("X8"), strName);

			if ((strValue ?? "") == "")
				Logging.WriteDebugLog("Que.ProcessPartialStatus() [0x{0}] Unable to read state information: {1}", lRequestId.ToString("X8"), strName);
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

			if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessPartialStatus() [0x{0}] Change: {1}", lRequestId.ToString("X8"), strName);

			if (!bool.TryParse(strValue ?? "", out bTemp))
				Logging.WriteDebugLog("Que.ProcessPartialStatus() [0x{0}] Unable to read state information: {1}", lRequestId.ToString("X8"), strName);
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

			if (unit.NextEventURL == "")
				strPageURL = strPageURLFirstEvent + unit.Serial;
			else
				strPageURL = unit.NextEventURL;
			if (_bQueLogging) Logging.WriteDebugLog("Que.GetAirConditionerEvents() [0x{0}] Unit: {1}, Base: {2}{3}", lRequestId.ToString("X8"), unit.Serial, _httpClient.BaseAddress, strPageURL);

			if (!IsTokenValid())
			{
				bRetVal = false;
				goto Cleanup;
			}

			try
			{
				cancellationToken = new CancellationTokenSource();
				cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

				httpResponse = await _httpClient.GetAsync(strPageURL, cancellationToken.Token).ConfigureAwait(false);

				if (httpResponse.IsSuccessStatusCode)
				{
					strResponse = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);
					if (_bQueLogging)
						Logging.WriteDebugLog("Que.GetAirConditionerEvents() [0x{0}] Responded (Encoding {1}, {2} bytes)", lRequestId.ToString("X8"), httpResponse.Content.Headers.ContentEncoding.ToString() == "" ? "N/A" : httpResponse.Content.Headers.ContentEncoding.ToString(), (httpResponse.Content.Headers.ContentLength ?? 0) == 0 ? "N/A" : httpResponse.Content.Headers.ContentLength.ToString());

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

					if (_bQueLogging) Logging.WriteDebugLog("Que.GetAirConditionerEvents() [0x{0}] Next Event URL: {1}", lRequestId.ToString("X8"), unit.NextEventURL);
					if (_bQueLogging) Logging.WriteDebugLog("Que.GetAirConditionerEvents() [0x{0}] Processing {1} events", lRequestId.ToString("X8"), (jsonResponse["events"] as JArray)?.Count ?? 0);

					var events = jsonResponse["events"] as JArray ?? new JArray();

					for (int iEvent = events.Count - 1; iEvent >= 0; iEvent--)
					{
						var ev = events[iEvent] as JObject;
						strEventType = (string)ev?["type"];

						if (_bQueLogging) Logging.WriteDebugLog("Que.GetAirConditionerEvents() [0x{0}] Event Type: {1}", lRequestId.ToString("X8"), strEventType);

						switch (strEventType)
						{
							case "status-change-broadcast":
								var data = ev["data"] as JObject;
								if (data != null)
								{
									foreach (JProperty change in data.Properties())
									{
										if (_bQueLogging) Logging.WriteDebugLog("Que.GetAirConditionerEvents() [0x{0}] Incremental Update: {1}", lRequestId.ToString("X8"), change.Name);

										// If this change confirms a pending optimistic expectation, confirm it
										ConfirmPendingForUnit(unit.Serial, change.Name, change.Value);

										// Compressor Mode
										if (change.Name == "LiveAircon.CompressorMode")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.CompressorState);
											updateItems |= UpdateItems.Main;
										}
										// Compressor Capacity
										else if (change.Name == "LiveAircon.CompressorCapacity")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.CompressorCapacity);
											updateItems |= UpdateItems.Main;
										}
										// Compressor Power
										else if (change.Name == "LiveAircon.OutdoorUnit.CompPower")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.CompressorPower);
											updateItems |= UpdateItems.Main;
										}
										// Mode
										else if (change.Name == "UserAirconSettings.Mode")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.Mode);
											updateItems |= UpdateItems.Main;
										}
										// Fan Mode
										else if (change.Name == "UserAirconSettings.FanMode")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.FanMode);
											updateItems |= UpdateItems.Main;
										}
										// On
										else if (change.Name == "UserAirconSettings.isOn")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.On);
											updateItems |= UpdateItems.Main;
										}
										// Away Mode
										else if (change.Name == "UserAirconSettings.AwayMode")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.AwayMode);
											updateItems |= UpdateItems.Main;
										}
										// Quiet Mode
										else if (change.Name == "UserAirconSettings.QuietMode")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.QuietMode);
											updateItems |= UpdateItems.Main;
										}										
										// Control All Zones
										else if (change.Name == "MasterInfo.ControlAllZones")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.ControlAllZones);
											updateItems |= UpdateItems.Main;
										}
										// Live Temperature
										else if (change.Name == "MasterInfo.LiveTemp_oC")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.Temperature);
											updateItems |= UpdateItems.Main;
										}
										// Live Temperature Outside
										else if (change.Name == "MasterInfo.LiveOutdoorTemp_oC")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.OutdoorTemperature);
											updateItems |= UpdateItems.Main;
										}
										// Live Humidity
										else if (change.Name == "MasterInfo.LiveHumidity_pc")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.Humidity);
											updateItems |= UpdateItems.Main;
										}
										// Set Temperature Cooling
										else if (change.Name == "UserAirconSettings.TemperatureSetpoint_Cool_oC")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.SetTemperatureCooling);
											updateItems |= UpdateItems.Main;
										}
										// Set Temperature Heating
										else if (change.Name == "UserAirconSettings.TemperatureSetpoint_Heat_oC")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.SetTemperatureHeating);
											updateItems |= UpdateItems.Main;
										}
										// Coil Inlet Temperature
										else if (change.Name == "LiveAircon.CoilInlet")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.CoilInletTemperature);
											updateItems |= UpdateItems.Main;
										}
										// Fan PWM
										else if (change.Name == "LiveAircon.FanPWM")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.FanPWM);
											updateItems |= UpdateItems.Main;
										}
										// Fan RPM
										else if (change.Name == "LiveAircon.FanRPM")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.FanRPM);
											updateItems |= UpdateItems.Main;
										}
										// Clean Filter
										else if (change.Name == "Alerts.CleanFilter")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.CleanFilter);
											updateItems |= UpdateItems.Main;
										}
										// Fan Time Since Filter Cleaned
										else if (change.Name == "ACStats.NV_FanRunTime_10m")
										{
											ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Data.FanTSFC);
											updateItems |= UpdateItems.Main;
										}
										// Remote Zone
										else if (change.Name.StartsWith("RemoteZoneInfo["))
										{
											iIndex = ExtractIndexFromBracket(change.Name);
											if (iIndex >= 0 && unit.Zones.ContainsKey(iIndex + 1))
											{
												updateItems |= (UpdateItems)(1 << (iIndex + 1));

												// Live Temperature
												if (change.Name.EndsWith("].LiveTemp_oC"))
													ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Zones[iIndex + 1].Temperature);
												// Cooling Set Temperature
												else if (change.Name.EndsWith("].TemperatureSetpoint_Cool_oC"))
													ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Zones[iIndex + 1].SetTemperatureCooling);
												// Heating Set Temperature
												else if (change.Name.EndsWith("].TemperatureSetpoint_Heat_oC"))
													ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Zones[iIndex + 1].SetTemperatureHeating);
												// Zone Position
												else if (change.Name.EndsWith("].ZonePosition"))
													ProcessPartialStatus(lRequestId, change.Name, change.Value.ToString(), ref unit.Zones[iIndex + 1].Position);
											}
										}
										// Enabled Zone
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

								updateItems |= UpdateItems.Main | UpdateItems.Zone1 | UpdateItems.Zone2 | UpdateItems.Zone3 | UpdateItems.Zone4 | UpdateItems.Zone5 | UpdateItems.Zone6 | UpdateItems.Zone7 | UpdateItems.Zone8;

								break;
						}
					}
				}
				else
				{
					if (httpResponse.StatusCode == System.Net.HttpStatusCode.NotFound)
						Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, "Unable to process API response: {0}/{1} - check the Que Serial number.", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);
					else if (httpResponse.StatusCode == System.Net.HttpStatusCode.Unauthorized)
					{
						Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, "Unable to process API response: {0}/{1}", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);

						_eventAuthenticationFailure.Set();
					}
					else
						Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, "Unable to process API HTTP response: {0}/{1}", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);

					bRetVal = false;
					goto Cleanup;
				}
			}
			catch (OperationCanceledException eException)
			{
				Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, eException, "Unable to process API HTTP response - operation timed out.");

				bRetVal = false;
				goto Cleanup;
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, eException.InnerException, "Unable to process API HTTP response.");
				else
					Logging.WriteDebugLogError("Que.GetAirConditionerEvents()", lRequestId, eException, "Unable to process API HTTP response.");

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


						// No Events Mode

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
							if (!await GetAirConditionerSerial().ConfigureAwait(false))
								continue;

						if (_iZoneCount == 0)
						{
							if (!await GetAirConditionerZones().ConfigureAwait(false))
								continue;
							else
								MQTTRegister();
						}

						// No Events Mode

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
			if (_queToken != null && _queToken.TokenExpires > DateTime.Now)
				return true;
			else
				return false;
		}

		private static void MQTTRegister()
		{
			AirConditionerZone zone;
			int iDeviceIndex = 0;
			string strHANameModifier = "", strDeviceNameModifier = "";
			string strAirConditionerName = "", strAirConditionerNameMQTT = "";

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

				strAirConditionerName = string.Format("{0} ({1})", _strAirConditionerName, unit.Name);
				strAirConditionerNameMQTT = string.Format("{0} ({1})", Service.DeviceNameMQTT, unit.Name);

				if (!_bSeparateHeatCool) // Default
					MQTT.SendMessage(string.Format("homeassistant/climate/actronque{0}/config", strHANameModifier), "{{\"name\":\"{1}\",\"unique_id\":\"{0}-AC\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"modes\":[\"off\",\"auto\",\"cool\",\"fan_only\",\"heat\"],\"fan_modes\":[\"high\",\"medium\",\"low\",\"auto\"],\"mode_command_topic\":\"actronque{3}/mode/set\",\"temperature_command_topic\":\"actronque{3}/temperature/set\",\"fan_mode_command_topic\":\"actronque{3}/fan/set\",\"min_temp\":\"12\",\"max_temp\":\"30\",\"temp_step\":\"0.5\",\"fan_mode_state_topic\":\"actronque{3}/fanmode\",\"action_topic\":\"actronque{3}/compressor\",\"temperature_state_topic\":\"actronque{3}/settemperature\",\"mode_state_topic\":\"actronque{3}/mode\",\"current_temperature_topic\":\"actronque{3}/temperature\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial, unit.Name);
				else
					MQTT.SendMessage(string.Format("homeassistant/climate/actronque{0}/config", strHANameModifier), "{{\"name\":\"{1}\",\"unique_id\":\"{0}-AC\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"modes\":[\"off\",\"auto\",\"cool\",\"fan_only\",\"heat\"],\"fan_modes\":[\"high\",\"medium\",\"low\",\"auto\"],\"mode_command_topic\":\"actronque{3}/mode/set\",\"temperature_high_command_topic\":\"actronque{3}/temperature/high/set\",\"temperature_low_command_topic\":\"actronque{3}/temperature/low/set\",\"fan_mode_command_topic\":\"actronque{3}/fan/set\",\"min_temp\":\"12\",\"max_temp\":\"30\",\"temp_step\":\"0.5\",\"fan_mode_state_topic\":\"actronque{3}/fanmode\",\"action_topic\":\"actronque{3}/compressor\",\"temperature_high_state_topic\":\"actronque{3}/settemperature/high\",\"temperature_low_state_topic\":\"actronque{3}/settemperature/low\",\"mode_state_topic\":\"actronque{3}/mode\",\"current_temperature_topic\":\"actronque{3}/temperature\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial, unit.Name);

				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}humidity/config", strHANameModifier), "{{\"name\":\"{1} Humidity\",\"unique_id\":\"{0}-Humidity\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/humidity\",\"unit_of_measurement\":\"%\",\"device_class\":\"humidity\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}temperature/config", strHANameModifier), "{{\"name\":\"{1} Temperature\",\"unique_id\":\"{0}-Temperature\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/temperature\",\"unit_of_measurement\":\"°C\",\"device_class\":\"temperature\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);

				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}compressorcapacity/config", strHANameModifier), "{{\"name\":\"{1} Compressor Capacity\",\"unique_id\":\"{0}-CompressorCapacity\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/compressorcapacity\",\"unit_of_measurement\":\"%\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}compressorpower/config", strHANameModifier), "{{\"name\":\"{1} Compressor Power\",\"unique_id\":\"{0}-CompressorPower\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/compressorpower\",\"unit_of_measurement\":\"W\",\"device_class\":\"power\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}outdoortemperature/config", strHANameModifier), "{{\"name\":\"{1} Outdoor Temperature\",\"unique_id\":\"{0}-OutdoorTemperature\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/outdoortemperature\",\"unit_of_measurement\":\"\u00B0C\",\"device_class\":\"temperature\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}coilinlettemperature/config", strHANameModifier), "{{\"name\":\"{1} Coil Inlet Temperature\",\"unique_id\":\"{0}-CoilInletTemperature\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/coilinlettemperature\",\"unit_of_measurement\":\"\u00B0C\",\"device_class\":\"temperature\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}fanpwm/config", strHANameModifier), "{{\"name\":\"{1} Fan PWM\",\"unique_id\":\"{0}-FanPWM\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/fanpwm\",\"unit_of_measurement\":\"%\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}fanrpm/config", strHANameModifier), "{{\"name\":\"{1} Fan RPM\",\"unique_id\":\"{0}-FanRPM\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/fanrpm\",\"unit_of_measurement\":\"RPM\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}cleanfilter/config", strHANameModifier), "{{\"name\":\"{1} Clean Filter\",\"unique_id\":\"{0}-CleanFilter\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/cleanfilter\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);					
				MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}fantsfc/config", strHANameModifier), "{{\"name\":\"{1} Fan Time Since Filter Cleaned\",\"unique_id\":\"{0}-FanTSFC\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/fantsfc\",\"unit_of_measurement\":\"h\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
				
				MQTT.SendMessage(string.Format("homeassistant/switch/actronque{0}/controlallzones/config", strHANameModifier), "{{\"name\":\"Control All Zones\",\"default_entity_id\":\"controlallzones{0}\",\"unique_id\":\"{0}-CAZ\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/controlallzones\",\"command_topic\":\"actronque{3}/controlallzones/set\",\"payload_on\":\"ON\",\"payload_off\":\"OFF\",\"state_on\":\"ON\",\"state_off\":\"OFF\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
				MQTT.Subscribe("actronque{0}/controlallzones/set", unit.Serial);
				
				MQTT.SendMessage(string.Format("homeassistant/switch/actronque{0}/awaymode/config", strHANameModifier), "{{\"name\":\"Away Mode\",\"default_entity_id\":\"awaymode{0}\",\"unique_id\":\"{0}-AwayMode\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/awaymode\",\"command_topic\":\"actronque{3}/awaymode/set\",\"payload_on\":\"ON\",\"payload_off\":\"OFF\",\"state_on\":\"ON\",\"state_off\":\"OFF\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
				MQTT.Subscribe("actronque{0}/awaymode/set", unit.Serial);
				
				MQTT.SendMessage(string.Format("homeassistant/switch/actronque{0}/quietmode/config", strHANameModifier), "{{\"name\":\"Quiet Mode\",\"default_entity_id\":\"quietmode{0}\",\"unique_id\":\"{0}-QuietMode\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/quietmode\",\"command_topic\":\"actronque{3}/quietmode/set\",\"payload_on\":\"ON\",\"payload_off\":\"OFF\",\"state_on\":\"ON\",\"state_off\":\"OFF\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
				MQTT.Subscribe("actronque{0}/quietmode/set", unit.Serial);
				
				MQTT.SendMessage(string.Format("homeassistant/switch/actronque{0}/constantfanmode/config", strHANameModifier),"{{\"name\":\"Constant Fan Mode\",\"object_id\":\"constantfanmode_{0}\",\"unique_id\":\"{0}-ConstantFanMode\",\"device\":{{\"identifiers\":[\"{0}\"],\"name\":\"{2}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{3}/constantfanmode\",\"command_topic\":\"actronque{3}/constantfanmode/set\",\"payload_on\":\"ON\",\"payload_off\":\"OFF\",\"state_on\":\"ON\",\"state_off\":\"OFF\",\"availability_topic\":\"{0}/status\"}}", Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
				MQTT.Subscribe("actronque{0}/constantfanmode/set", unit.Serial);
				
				
				foreach (int iZone in unit.Zones.Keys)
				{
					zone = unit.Zones[iZone];

					// Zone
					if (zone.Exists)
					{
						MQTT.SendMessage(string.Format("homeassistant/switch/actronque{0}/airconzone{1}/config", strHANameModifier, iZone), "{{\"name\":\"{0} Zone\",\"unique_id\":\"{2}-z{1}s\",\"device\":{{\"identifiers\":[\"{2}\"],\"name\":\"{3}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{4}/zone{1}\",\"command_topic\":\"actronque{4}/zone{1}/set\",\"payload_on\":\"ON\",\"payload_off\":\"OFF\",\"state_on\":\"ON\",\"state_off\":\"OFF\",\"availability_topic\":\"{2}/status\"}}", zone.Name, iZone, Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerNameMQTT, unit.Serial);
						MQTT.Subscribe("actronque{0}/zone{1}/set", unit.Serial, iZone);

						MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}/airconzone{1}/config", strHANameModifier, iZone), "{{\"name\":\"{0}\",\"unique_id\":\"{2}-z{1}t\",\"device\":{{\"identifiers\":[\"{2}\"],\"name\":\"{3}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{4}/zone{1}/temperature\",\"unit_of_measurement\":\"\u00B0C\",\"availability_topic\":\"{2}/status\"}}", zone.Name, iZone, Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerNameMQTT, unit.Serial);
						MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}/airconzone{1}position/config", strHANameModifier, iZone), "{{\"name\":\"{0} Position\",\"unique_id\":\"{2}-z{1}p\",\"device\":{{\"identifiers\":[\"{2}\"],\"name\":\"{3}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{4}/zone{1}/position\",\"unit_of_measurement\":\"%\",\"availability_topic\":\"{2}/status\"}}", zone.Name, iZone, Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerNameMQTT, unit.Serial);

						// Per Zone Controls
						if (_bPerZoneControls)
						{
							if (!_bSeparateHeatCool) // Default
								MQTT.SendMessage(string.Format("homeassistant/climate/actronque{0}/zone{1}/config", strHANameModifier, iZone), "{{\"name\":\"{0} {3}\",\"unique_id\":\"{2}-z{1}ac\",\"device\":{{\"identifiers\":[\"{2}\"],\"name\":\"{4}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"modes\":[\"off\",\"auto\",\"cool\",\"fan_only\",\"heat\"],\"mode_command_topic\":\"actronque{5}/zone{1}/mode/set\",\"temperature_command_topic\":\"actronque{5}/zone{1}/temperature/set\",\"min_temp\":\"12\",\"max_temp\":\"30\",\"temp_step\":\"0.5\",\"temperature_state_topic\":\"actronque{5}/zone{1}/settemperature\",\"mode_state_topic\":\"actronque{5}/zone{1}/mode\",\"current_temperature_topic\":\"actronque{5}/zone{1}/temperature\",\"action_topic\":\"actronque{5}/zone{1}/compressor\",\"availability_topic\":\"{2}/status\"}}", zone.Name, iZone, Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);
							else
								MQTT.SendMessage(string.Format("homeassistant/climate/actronque{0}/zone{1}/config", strHANameModifier, iZone), "{{\"name\":\"{0} {3}\",\"unique_id\":\"{2}-z{1}ac\",\"device\":{{\"identifiers\":[\"{2}\"],\"name\":\"{4}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"modes\":[\"off\",\"auto\",\"cool\",\"fan_only\",\"heat\"],\"mode_command_topic\":\"actronque{5}/zone{1}/mode/set\",\"temperature_high_command_topic\":\"actronque{5}/zone{1}/temperature/high/set\",\"temperature_low_command_topic\":\"actronque{5}/zone{1}/temperature/low/set\",\"min_temp\":\"12\",\"max_temp\":\"30\",\"temp_step\":\"0.5\",\"temperature_high_state_topic\":\"actronque{5}/zone{1}/settemperature/high\",\"temperature_low_state_topic\":\"actronque{5}/zone{1}/settemperature/low\",\"mode_state_topic\":\"actronque{5}/zone{1}/mode\",\"current_temperature_topic\":\"actronque{5}/zone{1}/temperature\",\"action_topic\":\"actronque{5}/zone{1}/compressor\",\"availability_topic\":\"{2}/status\"}}", zone.Name, iZone, Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, unit.Serial);

							MQTT.Subscribe("actronque{0}/zone{1}/temperature/set", unit.Serial, iZone);
							MQTT.Subscribe("actronque{0}/zone{1}/temperature/high/set", unit.Serial, iZone);
							MQTT.Subscribe("actronque{0}/zone{1}/temperature/low/set", unit.Serial, iZone);
							MQTT.Subscribe("actronque{0}/zone{1}/mode/set", unit.Serial, iZone);

							foreach (string sensor in zone.Sensors.Keys)
							{
								MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}/zone{1}sensor{2}battery/config", strHANameModifier, iZone, sensor), "{{\"name\":\"{0} Battery\",\"unique_id\":\"{2}-z{1}s{5}battery\",\"device\":{{\"identifiers\":[\"{2}\"],\"name\":\"{4}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{6}/zone{1}sensor{5}/battery\",\"state_class\":\"measurement\",\"unit_of_measurement\":\"%\",\"device_class\":\"battery\",\"availability_topic\":\"{2}/status\"}}", zone.Sensors[sensor].Name, iZone, Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, sensor, unit.Serial);
							}
						}
						else
						{
							MQTT.SendMessage(string.Format("homeassistant/climate/actronque{0}/zone{1}/config", strHANameModifier, iZone), "");
						}

						// Per Zone Sensors

						foreach (string sensor in zone.Sensors.Keys)
						{
							MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}/zone{1}sensor{2}temperature/config", strHANameModifier, iZone, sensor), "{{\"name\":\"{0} Temperature\",\"unique_id\":\"{2}-z{1}s{5}temperature\",\"device\":{{\"identifiers\":[\"{2}\"],\"name\":\"{4}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{6}/zone{1}sensor{5}/temperature\",\"device_class\":\"temperature\",\"unit_of_measurement\":\"\u00B0C\",\"availability_topic\":\"{2}/status\"}}", zone.Sensors[sensor].Name, iZone, Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, sensor, unit.Serial);
							MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}/zone{1}sensor{2}battery/config", strHANameModifier, iZone, sensor), "{{\"name\":\"{0} Battery\",\"unique_id\":\"{2}-z{1}s{5}battery\",\"device\":{{\"identifiers\":[\"{2}\"],\"name\":\"{4}\",\"model\":\"Add-On\",\"manufacturer\":\"ActronAir\"}},\"state_topic\":\"actronque{6}/zone{1}sensor{5}/battery\",\"state_class\":\"measurement\",\"unit_of_measurement\":\"%\",\"device_class\":\"battery\",\"availability_topic\":\"{2}/status\"}}", zone.Sensors[sensor].Name, iZone, Service.ServiceName.ToLower() + strDeviceNameModifier, strAirConditionerName, strAirConditionerNameMQTT, sensor, unit.Serial);
						}

						foreach (string sensor in zone.Sensors.Keys)
						{
							MQTT.SendMessage(string.Format("homeassistant/sensor/actronque{0}/zone{1}sensor{2}temperature/config", strHANameModifier, iZone, sensor), "");
						}
					}
				}

				MQTT.Subscribe("actronque{0}/mode/set", unit.Serial);
				MQTT.Subscribe("actronque{0}/fan/set", unit.Serial);
				MQTT.Subscribe("actronque{0}/temperature/set", unit.Serial);
				MQTT.Subscribe("actronque{0}/temperature/high/set", unit.Serial);
				MQTT.Subscribe("actronque{0}/temperature/low/set", unit.Serial);

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
					Logging.WriteDebugLog("Que.MQTTUpdateData() Suppressed update for unit {0} until {1}", unit.Serial, _unitSuppressUntil[unit.Serial]);
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
						MQTT.SendMessage(string.Format("actronque{0}/fanmode", unit.Serial), "auto");
						break;

					case "AUTO+CONT":
						MQTT.SendMessage(string.Format("actronque{0}/fanmode", unit.Serial), "auto");
						break;

					case "LOW":
						MQTT.SendMessage(string.Format("actronque{0}/fanmode", unit.Serial), "low");
						break;

					case "LOW+CONT":
						MQTT.SendMessage(string.Format("actronque{0}/fanmode", unit.Serial), "low");
						break;

					case "MED":
						MQTT.SendMessage(string.Format("actronque{0}/fanmode", unit.Serial), "medium");
						break;

					case "MED+CONT":
						MQTT.SendMessage(string.Format("actronque{0}/fanmode", unit.Serial), "medium");
						break;

					case "HIGH":
						MQTT.SendMessage(string.Format("actronque{0}/fanmode", unit.Serial), "high");
						break;

					case "HIGH+CONT":
						MQTT.SendMessage(string.Format("actronque{0}/fanmode", unit.Serial), "high");
						break;

					default:
						Logging.WriteDebugLog("Que.MQTTUpdateData() Unexpected Fan Mode: {0}", unit.Data.FanMode);
						break;
				}

				// Temperature
				MQTT.SendMessage(string.Format("actronque{0}/temperature", unit.Serial), unit.Data.Temperature.ToString("N1"));
				MQTT.SendMessage(string.Format("actronque{0}/outdoortemperature", unit.Serial), unit.Data.OutdoorTemperature.ToString("N1"));

				// Humidity
				MQTT.SendMessage(string.Format("actronque{0}/humidity", unit.Serial), unit.Data.Humidity.ToString("N1"));

				// Power, Mode & Set Temperature
				if (!unit.Data.On)
				{
					MQTT.SendMessage(string.Format("actronque{0}/mode", unit.Serial), "off");
					MQTT.SendMessage(string.Format("actronque{0}/settemperature", unit.Serial), GetSetTemperature(unit.Data.SetTemperatureHeating, unit.Data.SetTemperatureCooling).ToString("N1"));
					
					// JC Change Polling to off value to reduce data usage.
					_iPollInterval = _iPollIntervalOff;
					if (_bQueLogging) Logging.WriteDebugLog("Que.MQTTUpdateData() Polling Rate Updated to Off Value: {0}", _iPollInterval);
					
				}
				else
				{
					// JC Change Polling to on value to increase response time.
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
							if (unit.Data.On)
								MQTT.SendMessage(string.Format("actronque{0}/compressor", unit.Serial), "idle");
							else
								MQTT.SendMessage(string.Format("actronque{0}/compressor", unit.Serial), "off");

							break;

						default:
							Logging.WriteDebugLog("Que.MQTTUpdateData() Unexpected Compressor State: {0}", unit.Data.CompressorState);

							break;
					}
				}
				else
				{
					if (unit.Data.On)
						MQTT.SendMessage(string.Format("actronque{0}/compressor", unit.Serial), "idle");
					else
						MQTT.SendMessage(string.Format("actronque{0}/compressor", unit.Serial), "off");
				}

				// Compressor Capacity
				MQTT.SendMessage(string.Format("actronque{0}/compressorcapacity", unit.Serial), unit.Data.CompressorCapacity.ToString("F1"));

				// Compressor Power
				MQTT.SendMessage(string.Format("actronque{0}/compressorpower", unit.Serial), unit.Data.CompressorPower.ToString("F2"));

				// Coil Inlet Temperature
				MQTT.SendMessage(string.Format("actronque{0}/coilinlettemperature", unit.Serial), unit.Data.CoilInletTemperature.ToString("F2"));

				// Fan PWM
				MQTT.SendMessage(string.Format("actronque{0}/fanpwm", unit.Serial), unit.Data.FanPWM.ToString("F0"));

				// Fan RPM
				MQTT.SendMessage(string.Format("actronque{0}/fanrpm", unit.Serial), unit.Data.FanRPM.ToString("F0"));
				
				// Clean Filter
				MQTT.SendMessage(string.Format("actronque{0}/cleanfilter", unit.Serial), unit.Data.CleanFilter ? "on" : "off");					

				// Fan Time Since Filter Cleaned (* 10 / 60 = /6 to get hours from 10min units)
				MQTT.SendMessage(string.Format("actronque{0}/fantsfc", unit.Serial), (unit.Data.FanTSFC/6).ToString("F0"));

				// Control All Zones
				MQTT.SendMessage(string.Format("actronque{0}/controlallzones", unit.Serial), unit.Data.ControlAllZones ? "ON" : "OFF");

				// Away Mode
				MQTT.SendMessage(string.Format("actronque{0}/awaymode", unit.Serial), unit.Data.AwayMode ? "ON" : "OFF");

				// Quiet Mode
				MQTT.SendMessage(string.Format("actronque{0}/quietmode", unit.Serial), unit.Data.QuietMode ? "ON" : "OFF");	

				// Constant Fan Mode
				MQTT.SendMessage(string.Format("actronque{0}/constantfanmode", unit.Serial), unit.Data.ConstantFanMode ? "ON" : "OFF");					

			}

			// Zones
			foreach (int iIndex in unit.Zones.Keys)
			{
				if (unit.Zones[iIndex].Exists && items.HasFlag((UpdateItems)(1 << iIndex)))
				{
					MQTT.SendMessage(string.Format("actronque{0}/zone{1}", unit.Serial, iIndex), unit.Zones[iIndex].State ? "ON" : "OFF");
					MQTT.SendMessage(string.Format("actronque{0}/zone{1}/temperature", unit.Serial, iIndex), unit.Zones[iIndex].Temperature.ToString("N1"));
					MQTT.SendMessage(string.Format("actronque{0}/zone{1}/position", unit.Serial, iIndex), (unit.Zones[iIndex].Position * 5).ToString()); // 0-20 numeric displayed as 0-100 percentage

					// Per Zone Controls
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


						// Compressor
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
									if (unit.Data.On)
										MQTT.SendMessage(string.Format("actronque{0}/zone{1}/compressor", unit.Serial, iIndex), "idle");
									else
										MQTT.SendMessage(string.Format("actronque{0}/zone{1}/compressor", unit.Serial, iIndex), "off");

									break;

								default:
									Logging.WriteDebugLog("Que.MQTTUpdateData() Unexpected Compressor State: {0}", unit.Data.CompressorState);

									break;
							}
						}
						else
						{
							if (unit.Zones[iIndex].State)
								MQTT.SendMessage(string.Format("actronque{0}/zone{1}/compressor", unit.Serial, iIndex), "idle");
							else
								MQTT.SendMessage(string.Format("actronque{0}/zone{1}/compressor", unit.Serial, iIndex), "off");
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

		private static void AddCommandToQueue(QueueCommand command)
		{
			if (_bQueLogging) Logging.WriteDebugLog("Que.AddCommandToQueue() [0x{0}] New Command ID: [0x{1}] ", command.OriginalRequestId.ToString("X8"), command.RequestId.ToString("X8"));

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

			Logging.WriteDebugLog("Que.ChangeZone() [0x{0}] Unit: {1}, Zone {2}: {3}", lRequestId.ToString("X8"), unit.Serial, iZone, bState ? "On" : "Off");

			command.Data.command.Add("type", "set-settings");

			command.Data.command.Add(string.Format("UserAirconSettings.EnabledZones[{0}]", iZone - 1), bState);

			AddCommandToQueue(command);
		}

		public static void ChangeControlAllZones(long lRequestId, AirConditionerUnit unit, bool bState)
		{
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));

			Logging.WriteDebugLog("Que.ChangeControlAllZones() [0x{0}] Unit: {1}, Control All Zones: {2}", lRequestId.ToString("X8"), unit.Serial, bState ? "On" : "Off");

			command.Data.command.Add("type", "set-settings");

			command.Data.command.Add(string.Format("MasterInfo.ControlAllZones"), bState);

			AddCommandToQueue(command);
		}

		public static void AwayMode(long lRequestId, AirConditionerUnit unit, bool bState)
		{
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));

			Logging.WriteDebugLog("Que.AwayMode() [0x{0}] Unit: {1}, Away mode: {2}", lRequestId.ToString("X8"), unit.Serial, bState ? "On" : "Off");

			command.Data.command.Add("type", "set-settings");

			command.Data.command.Add(string.Format("UserAirconSettings.AwayMode"), bState);

			AddCommandToQueue(command);
		}
		
		public static void QuietMode(long lRequestId, AirConditionerUnit unit, bool bState)
		{
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));

			Logging.WriteDebugLog("Que.QuietMode() [0x{0}] Unit: {1}, Quiet mode: {2}", lRequestId.ToString("X8"), unit.Serial, bState ? "On" : "Off");

			command.Data.command.Add("type", "set-settings");

			command.Data.command.Add(string.Format("UserAirconSettings.QuietMode"), bState);

			AddCommandToQueue(command);
		}

		public static void ConstantFanMode(long lRequestId, AirConditionerUnit unit, bool bState)
		{
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));

			Logging.WriteDebugLog("Que.ConstantFanMode() [0x{0}] Unit: {1}, Constant Fan mode: {2}", lRequestId.ToString("X8"), unit.Serial, bState ? "On" : "Off");

			// Robust handling of FanMode: compute base (without +CONT) and reapply or remove +CONT
			string current = unit?.Data?.FanMode ?? "AUTO";
			string baseFan = StripContSuffix(current).Trim();
			if (string.IsNullOrWhiteSpace(baseFan))
				baseFan = "AUTO";

			string newFan;
			if (bState)
				newFan = (baseFan + "+CONT").ToUpperInvariant();
			else
				newFan = baseFan.ToUpperInvariant();

			command.Data.command.Add("UserAirconSettings.FanMode", newFan);
			command.Data.command.Add("type", "set-settings");

			AddCommandToQueue(command);

		}


		public static void ChangeMode(long lRequestId, AirConditionerUnit unit, AirConditionerMode mode)
		{
			QueueCommand command = new QueueCommand(lRequestId, unit, DateTime.Now.AddSeconds(_iCommandExpiry));

			Logging.WriteDebugLog("Que.ChangeMode() [0x{0}] Unit: {1}, Mode: {2}", lRequestId.ToString("X8"), unit.Serial, mode.ToString());

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
			QueueCommand command = new QueueCommand(lRequestId, unit,DateTime.Now.AddSeconds(_iCommandExpiry));

			Logging.WriteDebugLog("Que.ChangeFanMode() [0x{0}] Unit: {1}, Fan Mode: {2}", lRequestId.ToString("X8"), unit.Serial, fanMode.ToString());
	

			// Preserve existing +CONT flag if present (robust, case-insensitive)
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

			Logging.WriteDebugLog("Que.ChangeTemperature() [0x{0}] Unit: {1}, Zone: {2}, Temperature ({4}): {3}", lRequestId.ToString("X8"), unit.Serial, iZone, dblTemperature, setType.ToString());

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
							return;

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
				Logging.WriteDebugLog("Que.ChangeTemperature() [0x{0}] Unit: {1}, Setting Control All Zones to True due to Master temperature change", lRequestId.ToString("X8"), unit.Serial);

				ChangeControlAllZones(lRequestId, unit, true);
			}
		}

		private static async Task<bool> SendCommand(QueueCommand command)
		{
			HttpResponseMessage httpResponse = null;
			CancellationTokenSource cancellationToken = null;
			StringContent content;
			long lRequestId = RequestManager.GetRequestId(command.RequestId);
			string strPageURL = "api/v0/client/ac-systems/cmds/send?serial=";
			bool bRetVal = true;

			if (_bQueLogging) Logging.WriteDebugLog("Que.SendCommand() [0x{0}] Original Request ID: 0x{1}", lRequestId.ToString("X8"), command.OriginalRequestId.ToString("X8"));
			if (_bQueLogging) Logging.WriteDebugLog("Que.SendCommand() [0x{0}] Base: {1}{2}{3}", lRequestId.ToString("X8"), _httpClient.BaseAddress, strPageURL, command.Unit.Serial);
			
			try
			{
				content = new StringContent(JsonConvert.SerializeObject(command.Data));

				content.Headers.ContentType = new System.Net.Http.Headers.MediaTypeHeaderValue("application/json");

				Logging.WriteDebugLog("Que.SendCommand() [0x{0}] Content: {1}", lRequestId.ToString("X8"), await content.ReadAsStringAsync().ConfigureAwait(false));
			}
			catch (Exception eException)
			{
				Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, eException, "Unable to serialize command.");

				bRetVal = false;
				goto Cleanup;
			}

			try
			{
				cancellationToken = new CancellationTokenSource();
				cancellationToken.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

				httpResponse = await _httpClientCommands.PostAsync(strPageURL + command.Unit.Serial, content, cancellationToken.Token).ConfigureAwait(false);

				if (httpResponse.IsSuccessStatusCode)
					Logging.WriteDebugLog("Que.SendCommand() [0x{0}] Response {1}/{2}", lRequestId.ToString("X8"), httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);
				else
				{
					if (httpResponse.StatusCode == System.Net.HttpStatusCode.NotFound)
						Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, "Unable to process API response: {0}/{1} - check the Que Serial number.", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);
					else if (httpResponse.StatusCode == System.Net.HttpStatusCode.Unauthorized)
					{
						Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, "Unable to process API response: {0}/{1}", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);

						_eventAuthenticationFailure.Set();
					}
					else
						Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, "Unable to process API response: {0}/{1}", httpResponse.StatusCode.ToString(), httpResponse.ReasonPhrase);

					bRetVal = false;
					goto Cleanup;
				}
			}
			catch (OperationCanceledException eException)
			{
				Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, eException, "Unable to process API HTTP response - operation timed out.");

				bRetVal = false;
				goto Cleanup;
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, eException.InnerException, "Unable to process API HTTP response.");
				else
					Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, eException, "Unable to process API HTTP response.");

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