using System;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Threading;
using System.Threading.Tasks;

namespace HMX.HASSActronQue
{
    public partial class Que
    {
        // Tunables
        private static readonly TimeSpan DefaultPerRequestTimeout = TimeSpan.FromSeconds(30);
        private static readonly object _httpClientInitLock = new object();

        // Helper to initialize HttpClient instances from IHttpClientFactory.
        // Called once during startup after DI is configured.
        private static void InitializeHttpClientsFromFactory()
        {
            lock (_httpClientInitLock)
            {
                if (_httpClientFactory == null)
                {
                    throw new InvalidOperationException("IHttpClientFactory not initialized. Call ConfigureHttpClients first.");
                }

                // Create named clients from factory
                // All three fields point to factory-managed clients (can be the same or different based on configuration)
                _httpClient = _httpClientFactory.CreateClient("ActronQueApi");
                _httpClientAuth = _httpClientFactory.CreateClient("ActronQueAuth");
                _httpClientCommands = _httpClientFactory.CreateClient("ActronQueApi");

                Logging.WriteDebugLog("InitializeHttpClientsFromFactory() HttpClient instances created from factory");
                Logging.WriteDebugLog("  _httpClient hash: {0}", _httpClient.GetHashCode());
                Logging.WriteDebugLog("  _httpClientAuth hash: {0}", _httpClientAuth.GetHashCode());
                Logging.WriteDebugLog("  _httpClientCommands hash: {0}", _httpClientCommands.GetHashCode());
            }
        }

        // Utility to determine whether an exception is transient and can be retried.
        // Note: Polly handles most retries now, but we keep this for diagnostics.
        private static bool IsTransientNetworkError(Exception ex)
        {
            if (ex is HttpRequestException) return true;
            if (ex is IOException) return true;
            if (ex is TaskCanceledException) return true; // may be a timeout
            if (ex.InnerException is SocketException) return true;
            return false;
        }

        // Send a request with per-request timeout and cancellation support.
        // Polly policies (retry, circuit-breaker) are applied via IHttpClientFactory configuration.
        // Returns the HttpResponseMessage for caller to process; caller MUST dispose it.
        private static async Task<HttpResponseMessage> SendWithRetriesAsync(Func<HttpRequestMessage> requestFactory, HttpClient client, int maxRetries = -1, CancellationToken cancel = default)
        {
            // Create per-request cancellation token with timeout
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(cancel);
            cts.CancelAfter(DefaultPerRequestTimeout);

            try
            {
                var request = requestFactory();
                
                // Send request - Polly policies handle retries and circuit-breaking automatically
                var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cts.Token).ConfigureAwait(false);
                
                return response;
            }
            catch (Exception ex)
            {
                // Log the final exception after all Polly retries exhausted
                if (ex.InnerException is SocketException sockEx)
                {
                    Logging.WriteDebugLog("SendWithRetriesAsync() SocketException: {0} ({1})", sockEx.SocketErrorCode, sockEx.Message);
                }
                else
                {
                    Logging.WriteDebugLog("SendWithRetriesAsync() Exception: {0}", ex.Message);
                }
                
                throw;
            }
        }

		private static async Task<(bool Success, string Content, System.Net.HttpStatusCode StatusCode, Exception Error)> ExecuteRequestAsync(
			Func<HttpRequestMessage> requestFactory,
			HttpClient client,
			int timeoutSeconds = -1,
			long requestId = 0)
		{
			HttpResponseMessage httpResponse = null;
			CancellationTokenSource cts = null;

			try
			{
				cts = new CancellationTokenSource();

				if (timeoutSeconds > 0)
					cts.CancelAfter(TimeSpan.FromSeconds(timeoutSeconds));
				else if (_iCancellationTime > 0)
					cts.CancelAfter(TimeSpan.FromSeconds(_iCancellationTime));

				// SendWithRetriesAsync is the repo's resilient helper (returns HttpResponseMessage)
				httpResponse = await SendWithRetriesAsync(requestFactory, client, -1, cts.Token).ConfigureAwait(false);

				if (httpResponse == null)
				{
					return (false, null, 0, new Exception("SendWithRetriesAsync returned null HttpResponseMessage"));
				}

				var content = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);
				return (httpResponse.IsSuccessStatusCode, content, httpResponse.StatusCode, null);
			}
			catch (OperationCanceledException oce)
			{
				Logging.WriteDebugLogError("Que.ExecuteRequestAsync()", requestId, oce, "HTTP operation timed out or was cancelled.");
				return (false, null, 0, oce);
			}
			catch (Exception ex)
			{
				if (ex.InnerException != null)
					Logging.WriteDebugLogError("Que.ExecuteRequestAsync()", requestId, ex.InnerException, "Exception during HTTP request.");
				else
					Logging.WriteDebugLogError("Que.ExecuteRequestAsync()", requestId, ex, "Exception during HTTP request.");

				return (false, null, 0, ex);
			}
			finally
			{
				try { httpResponse?.Dispose(); } catch { }
				try { cts?.Dispose(); } catch { }
			}
		}
		
    }
}