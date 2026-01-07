using System;
using System.Collections.Generic;
using System.Text;

namespace HMX.HASSActronQue
{
	public class AirConditionerData
	{
		public bool ControlAllZones;
		public bool AwayMode; //Away Mode
		public bool QuietMode; // Quiet Mode
		public string FanMode; // FanMode
		public string Mode; // Mode
		public bool On; // isOn
		public bool CleanFilter; // Indoor Filter Time to Clean
		public double SetTemperatureCooling; // TemperatureSetpoint_Cool_oC
		public double SetTemperatureHeating; // TemperatureSetpoint_Heat_oC
		public double Temperature; // LiveTemp_oC
		public double OutdoorTemperature; // LiveOutdoorTemp_oC
		public double Humidity; // LiveHumidity_pc
		public string CompressorState; // CompressorMode
		public double CompressorCapacity; // CompressorCapacity
		public double CompressorPower; // CompPower
		public double CoilInletTemperature; // CoilInlet
		public double FanPWM; // FanPWM
		public double FanRPM; // FanRPM
		public double FanTSFC; // Fan Time Since Filter Cleaned - Hours
		public DateTime LastUpdated;

		public AirConditionerData()
		{
			LastUpdated = DateTime.MinValue;
		}
	}
}
