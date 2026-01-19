using System;
using System.Collections.Generic;
using System.Linq;
using Newtonsoft.Json.Linq;

namespace HMX.HASSActronQue
{
	public partial class Que
	{
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
	}
}