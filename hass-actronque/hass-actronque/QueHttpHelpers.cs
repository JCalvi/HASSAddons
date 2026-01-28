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

        // Lock used when creating clients historically; kept for compatibility but we use IHttpClientFactory now
        private static readonly object _httpClientLock = new object();

        // When using IHttpClientFactory we should NOT dispose factory-managed clients mid-flight.
        // Keep RecreateHttpClients as a no-op to avoid use-after-dispose races.
        private static void RecreateHttpClients()
        {
            // No-op under IHttpClientFactory. Keep for compatibility with existing call sites.
            Logging.WriteDebugLog("RecreateHttpClients() invoked - no-op under IHttpClientFactory.");
        }

        // Utility to determine whether an exception is transient and can be retried.
        // (Polly configuration will handle retries; this helper is kept for diagnostics)
        private static bool IsTransientNetworkError(Exception ex)
        {
            if (ex is HttpRequestException) return true;
            if (ex is IOException) return true;
            if (ex is TaskCanceledException) return true; // may be a timeout
            if (ex.InnerException is SocketException) return true;
            return false;
        }

        // Send a single request attempt; per-request timeout is handled by creating a linked CancellationTokenSource.
        // Polly policies attached to the HttpClient will provide retries/circuit-breaker.
        // Returns the HttpResponseMessage for caller to process; caller MUST dispose it.
        private static async Task<HttpResponseMessage> SendWithRetriesAsync(Func<HttpRequestMessage> requestFactory, HttpClient client, CancellationToken cancel = default)
        {
            HttpRequestMessage request = null;
            using var cts = CancellationTokenSource.CreateLinkedTokenSource(cancel);
            cts.CancelAfter(DefaultPerRequestTimeout);

            try
            {
                request = requestFactory();
                // Send once - rely on the HttpClient's policy handlers (Polly) for retries.
                var response = await client.SendAsync(request, HttpCompletionOption.ResponseHeadersRead, cts.Token).ConfigureAwait(false);
                return response;
            }
            catch (Exception ex) when (IsTransientNetworkError(ex))
            {
                // Log transient error for diagnostics; the configured HttpClient Polly policies will also log retries.
                Logging.WriteDebugLog("SendWithRetriesAsync() transient exception: {0}", ex.Message);
                try { request?.Dispose(); } catch { }
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

				// Use SendWithRetriesAsync (single attempt) and rely on Polly attached to the HttpClient for retry/circuit-breaker.
				httpResponse = await SendWithRetriesAsync(requestFactory, client, cts.Token).ConfigureAwait(false);

				if (httpResponse == null)
				{
					return (false, null, 0, new Exception("SendWithRetriesAsync returned null HttpResponseMessage"));
				}

				var content = await httpResponse.Content.ReadAsStringAsync().ConfigureAwait(false);
				return (httpResponse.IsSuccessStatusCode, content, httpResponse.StatusCode, null);
			}
			catch (Exception e)
			{
				// Log exception details (requestId is used for correlation in existing logs)
				if (e is TaskCanceledException)
					Logging.WriteDebugLogError("Que.ExecuteRequestAsync()", requestId, e, "Request cancelled or timed out.");
				else
					Logging.WriteDebugLogError("Que.ExecuteRequestAsync()", requestId, e, "Exception during HTTP request.");

				return (false, null, 0, e);
			}
			finally
			{
				try { cts?.Dispose(); } catch { }
				try { httpResponse?.Dispose(); } catch { }
			}
		}
    }
}