using System;
using System.Collections.Generic;
using Newtonsoft.Json.Linq;

namespace HMX.HASSActronQue
{
	// Partial class file containing mapping of event name -> handler
	public partial class Que
	{
		// Handler returns UpdateItems flags to OR into the caller's updateItems variable.
		private delegate UpdateItems StatusChangeHandler(long lRequestId, AirConditionerUnit unit, JToken value);

		private static readonly Dictionary<string, StatusChangeHandler> _statusChangeHandlers =
			new Dictionary<string, StatusChangeHandler>(StringComparer.Ordinal)
		{
			["LiveAircon.CompressorMode"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "LiveAircon.CompressorMode", token?.ToString(), ref unit.Data.CompressorState);
				return UpdateItems.Main;
			},
			["LiveAircon.CompressorCapacity"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "LiveAircon.CompressorCapacity", token?.ToString(), ref unit.Data.CompressorCapacity);
				return UpdateItems.Main;
			},
			["LiveAircon.OutdoorUnit.CompPower"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "LiveAircon.OutdoorUnit.CompPower", token?.ToString(), ref unit.Data.CompressorPower);
				return UpdateItems.Main;
			},
			["UserAirconSettings.Mode"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "UserAirconSettings.Mode", token?.ToString(), ref unit.Data.Mode);
				return UpdateItems.Main;
			},
			["UserAirconSettings.FanMode"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "UserAirconSettings.FanMode", token?.ToString(), ref unit.Data.FanMode);
				return UpdateItems.Main;
			},
			["UserAirconSettings.isOn"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "UserAirconSettings.isOn", token?.ToString(), ref unit.Data.On);
				return UpdateItems.Main;
			},
			["UserAirconSettings.AwayMode"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "UserAirconSettings.AwayMode", token?.ToString(), ref unit.Data.AwayMode);
				return UpdateItems.Main;
			},
			["UserAirconSettings.QuietMode"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "UserAirconSettings.QuietMode", token?.ToString(), ref unit.Data.QuietMode);
				return UpdateItems.Main;
			},
			["MasterInfo.ControlAllZones"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "MasterInfo.ControlAllZones", token?.ToString(), ref unit.Data.ControlAllZones);
				return UpdateItems.Main;
			},
			["MasterInfo.LiveTemp_oC"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "MasterInfo.LiveTemp_oC", token?.ToString(), ref unit.Data.Temperature);
				return UpdateItems.Main;
			},
			["MasterInfo.LiveOutdoorTemp_oC"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "MasterInfo.LiveOutdoorTemp_oC", token?.ToString(), ref unit.Data.OutdoorTemperature);
				return UpdateItems.Main;
			},
			["MasterInfo.LiveHumidity_pc"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "MasterInfo.LiveHumidity_pc", token?.ToString(), ref unit.Data.Humidity);
				return UpdateItems.Main;
			},
			["UserAirconSettings.TemperatureSetpoint_Cool_oC"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "UserAirconSettings.TemperatureSetpoint_Cool_oC", token?.ToString(), ref unit.Data.SetTemperatureCooling);
				return UpdateItems.Main;
			},
			["UserAirconSettings.TemperatureSetpoint_Heat_oC"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "UserAirconSettings.TemperatureSetpoint_Heat_oC", token?.ToString(), ref unit.Data.SetTemperatureHeating);
				return UpdateItems.Main;
			},
			["LiveAircon.CoilInlet"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "LiveAircon.CoilInlet", token?.ToString(), ref unit.Data.CoilInletTemperature);
				return UpdateItems.Main;
			},
			["LiveAircon.FanPWM"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "LiveAircon.FanPWM", token?.ToString(), ref unit.Data.FanPWM);
				return UpdateItems.Main;
			},
			["LiveAircon.FanRPM"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "LiveAircon.FanRPM", token?.ToString(), ref unit.Data.FanRPM);
				return UpdateItems.Main;
			},
			["Alerts.CleanFilter"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "Alerts.CleanFilter", token?.ToString(), ref unit.Data.CleanFilter);
				return UpdateItems.Main;
			},
			["ACStats.NV_FanRunTime_10m"] = (rid, unit, token) =>
			{
				ProcessPartialStatus(rid, "ACStats.NV_FanRunTime_10m", token?.ToString(), ref unit.Data.FanTSFC);
				return UpdateItems.Main;
			}
			// Add other top-level mappings here as needed
		};
	}
}