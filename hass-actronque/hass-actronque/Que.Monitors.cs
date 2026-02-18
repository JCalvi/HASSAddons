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
		// ADDED: CancellationToken parameter
		private static async Task TokenMonitor(CancellationToken cancellationToken = default)
		{
			WaitHandle[] waitHandles = new WaitHandle[] { _eventStop, _eventAuthenticationFailure };
			int iWaitHandle = 0;
			bool bExit = false;

			Logging.WriteDebugLog("Que.TokenMonitor()");

			// ADDED: Check for cancellation before starting
			cancellationToken.ThrowIfCancellationRequested();

			if (_pairingToken == null)
			{
				if (await GeneratePairingToken(cancellationToken).ConfigureAwait(false))
					await GenerateBearerToken(cancellationToken).ConfigureAwait(false);
			}
			else
				await GenerateBearerToken(cancellationToken).ConfigureAwait(false);

			while (!bExit)
			{
				// ADDED: Check for cancellation at start of each iteration
				if (cancellationToken.IsCancellationRequested)
				{
					Logging.WriteDebugLog("Que.TokenMonitor() Cancellation requested");
					break;
				}

				iWaitHandle = WaitHandle.WaitAny(waitHandles, TimeSpan.FromSeconds(_iAuthenticationInterval));

				switch (iWaitHandle)
				{
					case 0: // Stop
						bExit = true;
						break;

					case 1: // Authentication Failure
						if (_pairingToken == null)
						{
							if (await GeneratePairingToken(cancellationToken).ConfigureAwait(false))
								await GenerateBearerToken(cancellationToken).ConfigureAwait(false);
						}
						else if (_queToken == null)
							await GenerateBearerToken(cancellationToken).ConfigureAwait(false);
						else if (_queToken != null && _queToken.TokenExpires <= DateTime.UtcNow.AddSeconds(_iTokenRefreshBufferSeconds))
						{
							Logging.WriteDebugLog("Que.TokenMonitor() Refreshing expiring bearer token");
							await GenerateBearerToken(cancellationToken).ConfigureAwait(false);
						}
						break;

					case WaitHandle.WaitTimeout: // Wait Timeout
						if (_pairingToken == null)
						{
							if (await GeneratePairingToken(cancellationToken).ConfigureAwait(false))
								await GenerateBearerToken(cancellationToken).ConfigureAwait(false);
						}
						else if (_queToken == null)
							await GenerateBearerToken(cancellationToken).ConfigureAwait(false);
						else if (_queToken != null && _queToken.TokenExpires <= DateTime.UtcNow.AddSeconds(_iTokenRefreshBufferSeconds))
						{
							Logging.WriteDebugLog("Que.TokenMonitor() Refreshing expiring bearer token");
							await GenerateBearerToken(cancellationToken).ConfigureAwait(false);
						}
						break;
				}
			}

			Logging.WriteDebugLog("Que.TokenMonitor() Complete");
		}

		// ADDED: CancellationToken parameter
		private static async Task AirConditionerMonitor(CancellationToken cancellationToken = default)
		{
			WaitHandle[] waitHandles = new WaitHandle[] { _eventStop, _eventUpdate };
			int iWaitHandle = 0, iWaitInterval = 5;
			bool bExit = false;
			UpdateItems updateItems = UpdateItems.None;

			Logging.WriteDebugLog("Que.AirConditionerMonitor()");

			// ADDED: Check for cancellation before starting
			cancellationToken.ThrowIfCancellationRequested();

			while (!bExit)
			{
				// ADDED: Check for cancellation at start of each iteration
				if (cancellationToken.IsCancellationRequested)
				{
					Logging.WriteDebugLog("Que.AirConditionerMonitor() Cancellation requested");
					break;
				}

				updateItems = UpdateItems.None;

				iWaitHandle = WaitHandle.WaitAny(waitHandles, TimeSpan.FromSeconds(iWaitInterval));

				switch (iWaitHandle)
				{
					case 0: // Stop
						bExit = true;
						break;

					case 1: // Pull Update
						Logging.WriteDebugLog("Que.AirConditionerMonitor() Quick Update");

						await Task.Delay(_iPostCommandSleepTimerNeoNoEventsMode * 1000, cancellationToken).ConfigureAwait(false);

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

		// ADDED: CancellationToken parameter
		private static async Task QueueMonitor(CancellationToken cancellationToken = default)
		{
			WaitHandle[] waitHandles = new WaitHandle[] { _eventStop, _eventQueue };
			int iWaitHandle = 0;
			bool bExit = false;

			Logging.WriteDebugLog("Que.QueueMonitor()");

			// ADDED: Check for cancellation before starting
			cancellationToken.ThrowIfCancellationRequested();

			while (!bExit)
			{
				// ADDED: Check for cancellation at start of each iteration
				if (cancellationToken.IsCancellationRequested)
				{
					Logging.WriteDebugLog("Que.QueueMonitor() Cancellation requested");
					break;
				}

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