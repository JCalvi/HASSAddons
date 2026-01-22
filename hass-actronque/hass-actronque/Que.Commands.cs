using System;
using System.Threading;
using System.Threading.Tasks;
using System.Text;
using System.Net.Http;
using Newtonsoft.Json;

namespace HMX.HASSActronQue
{
    public partial class Que
    {
        // Sends a command to a unit. Returns true on success.
        private static async Task<bool> SendCommand(QueueCommand command)
        {
            // Request id for logging/tracing
            long lRequestId = RequestManager.GetRequestId();

            // Path for command posting (kept the same semantics as the original code).
            // If your real endpoint differs, keep the original string here.
            string strPageURL = "api/v0/aircon/commands/"; 

            bool bRetVal = true;

            if (_bQueLogging) Logging.WriteDebugLog("Que.SendCommand() Original Request ID: 0x{0}", command.OriginalRequestId.ToString("X8"));
            if (_bQueLogging) Logging.WriteDebugLog("Que.SendCommand() Sending to serial {0}", command.Unit.Serial);

            var json = JsonConvert.SerializeObject(command.Data);
            var result = await ExecuteRequestAsync(() =>
            {
                var req = new HttpRequestMessage(HttpMethod.Post, strPageURL + command.Unit.Serial)
                {
                    Content = new StringContent(json, Encoding.UTF8, "application/json")
                };
                return req;
            }, _httpClientCommands, -1, lRequestId).ConfigureAwait(false);

            if (!result.Success)
            {
                if (result.StatusCode == System.Net.HttpStatusCode.NotFound)
                    Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, "NotFound - check serial.");
                else if (result.StatusCode == System.Net.HttpStatusCode.Unauthorized)
                {
                    Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, "Unauthorized response.");
                    _eventAuthenticationFailure.Set();
                }
                else
                    Logging.WriteDebugLogError("Que.SendCommand()", lRequestId, $"HTTP error {result.StatusCode}");

                bRetVal = false;
            }
            else
            {
                if (_bQueLogging) Logging.WriteDebugLog("Que.SendCommand() Response OK");
            }

            return bRetVal;
        }

        // Adds a command to the bounded, thread-safe queue.
        private static void AddCommandToQueue(QueueCommand command)
        {
            if (_bQueLogging) Logging.WriteDebugLog("Que.AddCommandToQueue() New Command ID: 0x{0}", command.RequestId.ToString("X8"));

            // add pending expectations & optimistic publishes
            AddPendingFromCommand(command);

            // Use the thread-safe bounded enqueue helper which signals _eventQueue
            TryEnqueueQueueCommand(command);
        }

        private static void SendMQTTFailedCommandAlert(QueueCommand command)
        {
            Logging.WriteDebugLog("Que.SendMQTTFailedCommandAlert() Command failed: {0}", command.RequestId.ToString());
            MQTT.SendMessage(string.Format("actronque{0}/lastfailedcommand", command.Unit.Serial), command.RequestId.ToString());
        }

        // Process the queue: peek head, skip expired, attempt send, dequeue on success.
        private static async Task<bool> ProcessQueue()
        {
            QueueCommand command;
            bool bRetVal = false;
            if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessQueue()");

            while (true)
            {
                // Preserve single-threaded processing semantics via the existing lock
                lock (_oLockQueue)
                {
                    // TryPeek to inspect head without removing it
                    if (_queueCommands.TryPeek(out command))
                    {
                        if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessQueue() Attempting Command: 0x{0}", command.RequestId.ToString("X8"));

                        if (command.Expires <= DateTime.Now)
                        {
                            Logging.WriteDebugLog("Que.ProcessQueue() Command Expired: 0x{0}", command.RequestId.ToString("X8"));

                            SendMQTTFailedCommandAlert(command);

                            // Remove the expired head and update the counter
                            if (_queueCommands.TryDequeue(out _))
                                Interlocked.Decrement(ref _queueCount);

                            // Continue to next item
                            continue;
                        }
                    }
                    else
                    {
                        command = null;
                    }
                }

                if (command == null)
                    break;

                // Attempt to send. Do not modify queue before we know send succeeded.
                if (await SendCommand(command).ConfigureAwait(false))
                {
                    lock (_oLockQueue)
                    {
                        Logging.WriteDebugLog("Que.ProcessQueue() Command Complete: 0x{0}", command.RequestId.ToString("X8"));

                        // Remove the head (which should be the command we just processed).
                        if (_queueCommands.TryDequeue(out _))
                            Interlocked.Decrement(ref _queueCount);

                        bRetVal = true;
                    }
                }
                else
                {
                    // Send failed: keep the command on the queue (same behavior as before).
                    // Optionally add retry-limiting or move to dead-letter queue here.
                }
            }

            if (_bQueLogging) Logging.WriteDebugLog("Que.ProcessQueue() Complete");

            return bRetVal;
        }
    }
}