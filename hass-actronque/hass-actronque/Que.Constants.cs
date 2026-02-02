using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading;
using Newtonsoft.Json;

namespace HMX.HASSActronQue
{
	public partial class Que
	{
		// Base and file paths
		private static string _strBaseURLQue = "https://que.actronair.com.au/";
		private static string _strDeviceName;
		private static string _strDeviceIdFile = "/data/deviceid.json";
		private static string _strPairingTokenFile = "/data/pairingtoken.json";
		private static string _strBearerTokenFile = "/data/bearertoken.json";
		private static string _strDeviceUniqueIdentifier = "";

		// centralized keys
		private static string controlAllZonesKey = "MasterInfo.ControlAllZones";
		private static string awayKey = "UserAirconSettings.AwayMode";
		private static string quietKey = "UserAirconSettings.QuietMode";

		// Credentials & flags
		private static string _strQueUser, _strQuePassword, _strSerialNumber;
		private static bool _bPerZoneControls = false;
		private static bool _bSeparateHeatCool = false;
		private static bool _bShowBatterySensors = true;
		private static bool _bQueLogging = true;

		// Queue & HTTP clients
		private static Queue<QueueCommand> _queueCommands = new Queue<QueueCommand>();

		// NOTE: we keep the three named HttpClient fields for compatibility with existing call sites,
		// but they will be initialized by InitializeHttpClients() to factory-managed clients.
		private static HttpClient _httpClient = null, _httpClientAuth = null, _httpClientCommands = null;

		// Token provider (DI-managed) - initialized by InitializeHttpClients()
		private static TokenProvider _tokenProvider = null;

		// Reusable JSON serializer settings to reduce memory allocations
		private static readonly JsonSerializerSettings _jsonSettings = new JsonSerializerSettings
		{
			NullValueHandling = NullValueHandling.Ignore,
			DefaultValueHandling = DefaultValueHandling.Ignore,
			Formatting = Formatting.None
		};

		// String pool for commonly used MQTT topics and format strings
		private static readonly Dictionary<string, string> _mqttTopicCache = new Dictionary<string, string>();
		private static readonly object _mqttTopicCacheLock = new object();

		// Pre-cached topic format templates (used frequently)
		private static class MqttTopicTemplates
		{
			// Main topics
			public const string Mode = "actronque{0}/mode";
			public const string FanMode = "actronque{0}/fanmode";
			public const string Temperature = "actronque{0}/temperature";
			public const string SetTemperature = "actronque{0}/settemperature";
			public const string SetTemperatureHigh = "actronque{0}/settemperature/high";
			public const string SetTemperatureLow = "actronque{0}/settemperature/low";
			public const string Humidity = "actronque{0}/humidity";
			public const string OutdoorTemperature = "actronque{0}/outdoortemperature";
			public const string Compressor = "actronque{0}/compressor";
			public const string CompressorCapacity = "actronque{0}/compressorcapacity";
			public const string CompressorPower = "actronque{0}/compressorpower";
			public const string CoilInletTemperature = "actronque{0}/coilinlettemperature";
			public const string CleanFilter = "actronque{0}/cleanfilter";
			public const string FanTSFC = "actronque{0}/fantsfc";
			public const string FanPWM = "actronque{0}/fanpwm";
			public const string FanRPM = "actronque{0}/fanrpm";
			public const string ControlAllZones = "actronque{0}/controlallzones";
			public const string AwayMode = "actronque{0}/awaymode";
			public const string QuietMode = "actronque{0}/quietmode";
			public const string ConstantFanMode = "actronque{0}/constantfanmode";
			public const string LastFailedCommand = "actronque{0}/lastfailedcommand";
			
			// Zone topics
			public const string Zone = "actronque{0}/zone{1}";
			public const string ZoneTemperature = "actronque{0}/zone{1}/temperature";
			public const string ZonePosition = "actronque{0}/zone{1}/position";
			public const string ZoneMode = "actronque{0}/zone{1}/mode";
			public const string ZoneSetTemperature = "actronque{0}/zone{1}/settemperature";
			public const string ZoneSetTemperatureHigh = "actronque{0}/zone{1}/settemperature/high";
			public const string ZoneSetTemperatureLow = "actronque{0}/zone{1}/settemperature/low";
			public const string ZoneCompressor = "actronque{0}/zone{1}/compressor";
			public const string ZoneSensorTemperature = "actronque{0}/zone{1}sensor{2}/temperature";
			public const string ZoneSensorBattery = "actronque{0}/zone{1}sensor{2}/battery";
		}

		// Helper method to get cached topic strings
		private static string GetCachedTopic(string template, params object[] args)
		{
			string key = template + ":" + string.Join(":", args);
			
			lock (_mqttTopicCacheLock)
			{
				if (_mqttTopicCache.TryGetValue(key, out string cached))
					return cached;
				
				string topic = string.Format(template, args);
				
				// Limit cache size to prevent unbounded growth
				if (_mqttTopicCache.Count < 500)
					_mqttTopicCache[key] = topic;
				
				return topic;
			}
		}

		// Diagnostic method to check cache size
		public static int GetTopicCacheSize()
		{
			lock (_mqttTopicCacheLock)
			{
				return _mqttTopicCache.Count;
			}
		}

		// Timer/default values (seconds)
		private static int _iCancellationTime = 15; // Seconds
		private static int _iPollInterval = 30; // Seconds
		private static int _iPollIntervalOn = 60; // Seconds
		private static int _iPollIntervalOff = 600; // Seconds		
		private static int _iAuthenticationInterval = 60; // Seconds
		private static int _iQueueInterval = 4; // Seconds
		private static int _iCommandExpiry = 12; // Seconds
		private static int _iPostCommandSleepTimerNeoNoEventsMode = 10; // Seconds

		// State & sync
		private static int _iZoneCount = 0;
		private static ManualResetEvent _eventStop;
		private static AutoResetEvent _eventAuthenticationFailure = new AutoResetEvent(false);
		private static AutoResetEvent _eventQueue = new AutoResetEvent(false);
		private static AutoResetEvent _eventUpdate = new AutoResetEvent(false);
		private static PairingToken _pairingToken;
		private static QueToken _queToken = null;
		private static Dictionary<string, AirConditionerUnit> _airConditionerUnits = new Dictionary<string, AirConditionerUnit>();
		private static object _oLockData = new object(), _oLockQueue = new object();
	}
}