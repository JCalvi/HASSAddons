using System;
using System.Collections.Generic;
using System.Net.Http;
using System.Threading;

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