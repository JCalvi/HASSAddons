using System;
using System.Text;
using System.Threading.Tasks;
using System.Net.Http;
using Newtonsoft.Json;

namespace HMX.HASSActronQue
{
    public partial class Que
    {
        private static async Task<bool> SendCommand(QueueCommand command)
        {
            long lRequestId = RequestManager.GetRequestId(command.RequestId);
            string strPageURL = "api/v0/client/ac-systems/cmds/send?serial=";
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
            }, _sharedHttpClient, -1, lRequestId).ConfigureAwait(false);

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

        private static void AddCommandToQueue(QueueCommand command)
        {
            if (_bQueLogging) Logging.WriteDebugLog("Que.AddCommandToQueue() New Command ID: 0x{0}", command.RequestId.ToString("X8"));

            // add pending expectations & optimistic publishes
            AddPendingFromCommand(command);

            lock (_oLockQueue)
            {
                _queueCommands.Enqueue(command);
                _eventQueue.Set();
            }
        }

        private static void SendMQTTFailedCommandAlert(QueueCommand command)
        {
            Logging.WriteDebugLog("Que.SendMQTTFailedCommandAlert() Command failed: {0}", command.RequestId.ToString());
            MQTT.SendMessage(string.Format("actronque{0}/lastfailedcommand", command.Unit.Serial), command.RequestId.ToString());
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
    }
}