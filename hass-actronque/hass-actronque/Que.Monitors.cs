using System;
using System.Collections.Generic;
using System.IO;
using System.Text;
using System.Threading;
using System.Threading.Tasks;

namespace HMX.HASSActronQue
{
	public static partial class Que
	{
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
						else if (_queToken == null)
							await GenerateBearerToken().ConfigureAwait(false);
						else if (_queToken != null && _queToken.TokenExpires <= DateTime.UtcNow.Add(TimeSpan.FromMinutes(5))) // use UTC for comparison
						{
							Logging.WriteDebugLog("Que.TokenMonitor() Refreshing expiring bearer token");
							await GenerateBearerToken().ConfigureAwait(false);
						}
						break;

					case WaitHandle.WaitTimeout: // Wait Timeout
						if (_pairingToken == null)
						{
							if (await GeneratePairingToken().ConfigureAwait(false))
								await GenerateBearerToken().ConfigureAwait(false);
						}
						else if (_queToken == null)
							await GenerateBearerToken().ConfigureAwait(false);
						else if (_queToken != null && _queToken.TokenExpires <= DateTime.UtcNow.Add(TimeSpan.FromMinutes(5))) // use UTC for comparison
						{
							Logging.WriteDebugLog("Que.TokenMonitor() Refreshing expiring bearer token");
							await GenerateBearerToken().ConfigureAwait(false);
						}
						break;
				}
			}

			Logging.WriteDebugLog("Que.TokenMonitor() Complete");
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
	}
}