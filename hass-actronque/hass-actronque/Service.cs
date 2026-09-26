using Microsoft.AspNetCore.Hosting;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Configuration;
using System;
using System.Threading;

namespace HMX.HASSActronQue
{
	internal class Service
	{
		private static string _strServiceName = "hass-actronque";
		private static string _strDeviceNameMQTT = "Actron QUE Cloud";
		private static string _strConfigFile = "/data/options.json";
		private static ManualResetEvent _eventStop = new ManualResetEvent(false);

		public static string ServiceName
		{
			get { return _strServiceName; }
		}

		public static string DeviceNameMQTT
		{
			get { return _strDeviceNameMQTT; }
		}

		public static void Start()
        {
			IConfigurationRoot configuration;
			IHost webHost;
			string strMQTTUser, strMQTTPassword, strMQTTBroker;
			string strQueUser, strQuePassword, strQueSerial, strDeviceName;
			bool bPerZoneControls, bQueLogging, bMQTTLogging, bMQTTTLS, bSeparateHeatCool, bShowBatterySensors;

			Logging.WriteDebugLog("Service.Start() Build Date: {0}", Properties.Resources.BuildDate);

			// Load Configuration
			try
			{
				configuration = new ConfigurationBuilder().AddJsonFile(_strConfigFile, false, true).Build();
			}
			catch (Exception eException)
			{
				Logging.WriteDebugLogError("Service.Start()", eException, "Unable to build configuration instance.");
				return;
			}

			Configuration.GetOptionalConfiguration(configuration, "MQTTUser", out strMQTTUser);
			Configuration.GetPrivateOptionalConfiguration(configuration, "MQTTPassword", out strMQTTPassword);

			// Better error messages for required config
			if (!Configuration.GetConfiguration(configuration, "MQTTBroker", out strMQTTBroker))
			{
				Logging.WriteDebugLogError("Service.Start()", "REQUIRED configuration missing: MQTTBroker. Please add this to your config file.");
				return;
			}

			Configuration.GetOptionalConfiguration(configuration, "MQTTLogs", out bMQTTLogging, true);
			Configuration.GetOptionalConfiguration(configuration, "MQTTTLS", out bMQTTTLS);

			if (!Configuration.GetConfiguration(configuration, "PerZoneControls", out bPerZoneControls))
			{
				Logging.WriteDebugLogError("Service.Start()", "REQUIRED configuration missing: PerZoneControls (true/false). Please add this to your config file.");
				return;
			}

			if (!Configuration.GetConfiguration(configuration, "QueUser", out strQueUser))
			{
				Logging.WriteDebugLogError("Service.Start()", "REQUIRED configuration missing: QueUser. Please add your Actron Que username to the config file.");
				return;
			}

			if (!Configuration.GetPrivateConfiguration(configuration, "QuePassword", out strQuePassword))
			{
				Logging.WriteDebugLogError("Service.Start()", "REQUIRED configuration missing: QuePassword. Please add your Actron Que password to the config file.");
				return;
			}

			Configuration.GetOptionalConfiguration(configuration, "QueLogs", out bQueLogging, true);
			Configuration.GetOptionalConfiguration(configuration, "QueSerial", out strQueSerial);

			Configuration.GetOptionalConfiguration(configuration, "SeparateHeatCoolTargets", out bSeparateHeatCool);
			Configuration.GetOptionalConfiguration(configuration, "ShowBatterySensors", out bShowBatterySensors, true);
			Configuration.GetOptionalConfiguration(configuration, "DeviceName", out strDeviceName);
			if (strDeviceName == "")
			{
				Logging.WriteDebugLog("Service.Start() Device Name not specified, defaulting to HASSActronQue.");
				strDeviceName = "HASSActronQue";
			}
			else
			{
				strDeviceName = strDeviceName.Trim();
			}
			try
			{
				webHost = Host.CreateDefaultBuilder().ConfigureWebHostDefaults(webBuilder =>
				{
					webBuilder.UseStartup<ASPNETCoreStartup>().UseConfiguration(configuration); 
				}).Build();
			}
			catch (Exception eException)
			{
				Logging.WriteDebugLogError("Service.Start()", eException, "Unable to build web server instance.");
				return;
			}

			MQTT.StartMQTT(strMQTTBroker, bMQTTLogging, bMQTTTLS, _strServiceName, strMQTTUser, strMQTTPassword, MQTTProcessor);

			// Ensure HTTP clients and token provider are initialized before starting Que.
			Que.InitializeHttpClients();

			// Que.Initialise is async; wait synchronously so startup failures are observed (removes CS4014).
			Que.Initialise(strQueUser, strQuePassword, strQueSerial, strDeviceName, bQueLogging, bPerZoneControls, bSeparateHeatCool, bShowBatterySensors, _eventStop)
			   .GetAwaiter().GetResult();

			webHost.Run();
		}

		public static void Stop()
		{
			Logging.WriteDebugLog("Service.Stop()");
			_eventStop.Set();
		}
	}
}
