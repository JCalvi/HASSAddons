using System;
using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Threading;
using System.Threading.Tasks;

namespace HMX.HASSActronQue
{
	/// <summary>
	/// DelegatingHandler that attaches bearer tokens to requests and handles 401 responses
	/// by refreshing the token and retrying once.
	/// </summary>
	public class BearerTokenHandler : DelegatingHandler
	{
		private readonly TokenProvider _tokenProvider;

		public BearerTokenHandler(TokenProvider tokenProvider)
		{
			_tokenProvider = tokenProvider ?? throw new ArgumentNullException(nameof(tokenProvider));
		}

		protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
		{
			// Get current token and attach to request
			var token = await _tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(false);
			
			if (!string.IsNullOrEmpty(token))
			{
				request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
			}

			// Send the request
			var response = await base.SendAsync(request, cancellationToken).ConfigureAwait(false);

			// If we get a 401, try refreshing the token once and retry
			if (response.StatusCode == HttpStatusCode.Unauthorized)
			{
				Logging.WriteDebugLog("BearerTokenHandler.SendAsync() Received 401, attempting token refresh");

				// Dispose the failed response
				response.Dispose();

				// Force refresh the token
				try
				{
					var newToken = await _tokenProvider.ForceRefreshAsync(cancellationToken).ConfigureAwait(false);
					
					if (!string.IsNullOrEmpty(newToken))
					{
						// Clone the request (can't reuse the original)
						var retryRequest = await CloneHttpRequestMessageAsync(request).ConfigureAwait(false);
						retryRequest.Headers.Authorization = new AuthenticationHeaderValue("Bearer", newToken);

						Logging.WriteDebugLog("BearerTokenHandler.SendAsync() Retrying request with new token");
						response = await base.SendAsync(retryRequest, cancellationToken).ConfigureAwait(false);
					}
				}
				catch (Exception ex)
				{
					Logging.WriteDebugLogError("BearerTokenHandler.SendAsync()", ex, "Failed to refresh token on 401");
				}
			}

			return response;
		}

		private static async Task<HttpRequestMessage> CloneHttpRequestMessageAsync(HttpRequestMessage request)
		{
			var clone = new HttpRequestMessage(request.Method, request.RequestUri)
			{
				Version = request.Version
			};

			// Copy headers
			foreach (var header in request.Headers)
			{
				// Skip Authorization header as we'll set it fresh
				if (header.Key == "Authorization")
					continue;
					
				clone.Headers.TryAddWithoutValidation(header.Key, header.Value);
			}

			// Copy content if present
			if (request.Content != null)
			{
				var originalContent = await request.Content.ReadAsByteArrayAsync().ConfigureAwait(false);
				var contentClone = new ByteArrayContent(originalContent);

				// Copy content headers
				foreach (var header in request.Content.Headers)
				{
					contentClone.Headers.TryAddWithoutValidation(header.Key, header.Value);
				}

				clone.Content = contentClone;
			}

			return clone;
		}
	}
}
