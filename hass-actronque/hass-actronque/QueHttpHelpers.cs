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
        private static readonly int DefaultMaxRetries = 3;
        private static readonly TimeSpan[] RetryDelays = new[] {
            TimeSpan.FromSeconds(1),
            TimeSpan.FromSeconds(5),
            TimeSpan.FromSeconds(15)
        };

        private static readonly object _httpClientLock = new object();

        // Recreate clients when persistent socket problems observed
        private static void RecreateHttpClients()
        {
            lock (_httpClientLock)
            {
                try
                {
                    _httpClientAuth?.Dispose();
                    _httpClient?.Dispose();
                    _httpClientCommands?.Dispose();
                }
                catch { }

                // Use SocketsHttpHandler for better pooling control where available
                var handler = new SocketsHttpHandler()
                {
                    AutomaticDecompression = DecompressionMethods.All,
                    PooledConnectionLifetime = TimeSpan.FromMinutes(2),
                    PooledConnectionIdleTimeout = TimeSpan.FromSeconds(30),
                    MaxConnectionsPerServer = 10
                };

                _httpClientAuth = new HttpClient(handler, disposeHandler: true) { BaseAddress = new Uri(_strBaseURLQue) };
                _httpClient = new HttpClient(handler, disposeHandler: false) { BaseAddress = new Uri(_strBaseURLQue) };
                _httpClientCommands = new HttpClient(handler, disposeHandler: false) { BaseAddress = new Uri(_strBaseURLQue) };

                // We will use per-request CancellationTokenSource for fine-grained timeouts.
                // leave HttpClient.Timeout unset or infinite to avoid double timeouts:
                _httpClientAuth.Timeout = Timeout.InfiniteTimeSpan;
                _httpClient.Timeout = Timeout.InfiniteTimeSpan;
                _httpClientCommands.Timeout = Timeout.InfiniteTimeSpan;
            }
        }

        // Utility to determine whether an exception is transient and can be retried.
        private static bool IsTransientNetworkError(Exception ex)
        {
            if (ex is HttpRequestException) return true;
            if (ex is IOException) return true;
            if (ex is TaskCanceledException) return true; // may be a timeout
            if (ex.InnerException is SocketException) return true;
            return false;
        }

        // Send a request with retries. Accepts a factory because HttpRequestMessage cannot be reused.
        // Returns the HttpResponseMessage for caller to process; caller MUST dispose it.
        private static async Task<HttpResponseMessage> SendWithRetriesAsync(Func<HttpRequestMessage> requestFactory, HttpClient client, int maxRetries = -1, CancellationToken cancel = default)
        {
            if (maxRetries < 0) maxRetries = DefaultMaxRetries;

            HttpResponseMessage response = null;
            Exception lastEx = null;

            for (int attempt = 1; attempt <= maxRetries; attempt++)
            {
                using var cts = CancellationTokenSource.CreateLinkedTokenSource(cancel);
                cts.CancelAfter(DefaultPerRequestTimeout);

                HttpRequestMessage request = null;
                try
                {
                    request = requestFactory();

                    // For servers that don't handle keep-alive well, allow forcing Connection: close on retries:
                    if (attempt > 1)
                        request.Headers.ConnectionClose = true;

                    response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cts.Token).ConfigureAwait(false);

                    // If 5xx or 408 -> transient server error: consider retrying
                    if ((int)response.StatusCode >= 500 || response.StatusCode == HttpStatusCode.RequestTimeout)
                    {
                        // log and retry
                        Logging.WriteDebugLog("SendWithRetriesAsync() transient HTTP status {0} on attempt {1}", response.StatusCode, attempt);
                        response.Dispose();

                        if (attempt < maxRetries)
                            await Task.Delay(RetryDelays[Math.Min(attempt - 1, RetryDelays.Length - 1)]).ConfigureAwait(false);
                        continue;
                    }

                    // For 4xx, do not retry (except maybe 429 which could be transient). Caller should handle 401/403.
                    if ((int)response.StatusCode >= 400 && (int)response.StatusCode < 500 && response.StatusCode != (HttpStatusCode)429)
                    {
                        return response;
                    }

                    // success-ish (2xx or other not transient codes)
                    return response;
                }
                catch (Exception ex) when (IsTransientNetworkError(ex))
                {
                    lastEx = ex;
                    // log details including SocketErrorCode if available
                    if (ex.InnerException is SocketException sockEx)
                    {
                        Logging.WriteDebugLog("SendWithRetriesAsync() SocketException attempt {0}: {1} ({2})", attempt, sockEx.SocketErrorCode, sockEx.Message);
                    }
                    else
                    {
                        Logging.WriteDebugLog("SendWithRetriesAsync() transient exception attempt {0}: {1}", attempt, ex.Message);
                    }

                    try { request?.Dispose(); } catch { }

                    // On persistent socket problems, recreate the clients before next attempt to avoid stuck/half-closed pooled connections
                    if (attempt == 2)
                    {
                        Logging.WriteDebugLog("SendWithRetriesAsync() recreating HttpClients after repeated errors.");
                        RecreateHttpClients();
                    }

                    if (attempt < maxRetries)
                    {
                        await Task.Delay(RetryDelays[Math.Min(attempt - 1, RetryDelays.Length - 1)]).ConfigureAwait(false);
                        continue;
                    }

                    // final attempt failed -> break and throw below
                }
            }

            // If we reach here, everything failed
            if (lastEx != null)
            {
                Logging.WriteDebugLog("SendWithRetriesAsync() all attempts failed: {0}", lastEx.Message);
                throw lastEx;
            }

            return response;
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