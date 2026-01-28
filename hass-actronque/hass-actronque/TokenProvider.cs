using System;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace HMX.HASSActronQue
{
	/// <summary>
	/// Thread-safe token provider that caches bearer tokens and refreshes them when expired.
	/// Uses SemaphoreSlim to serialize token refresh operations.
	/// </summary>
	public class TokenProvider
	{
		private readonly SemaphoreSlim _refreshLock = new SemaphoreSlim(1, 1);
		private readonly IHttpClientFactory _httpClientFactory;
		private readonly string _bearerTokenFile;
		private readonly PairingToken _pairingToken;
		
		private QueToken _cachedToken;
		private DateTime _tokenExpiry = DateTime.MinValue;

		public TokenProvider(IHttpClientFactory httpClientFactory, string bearerTokenFile, PairingToken pairingToken)
		{
			_httpClientFactory = httpClientFactory ?? throw new ArgumentNullException(nameof(httpClientFactory));
			_bearerTokenFile = bearerTokenFile;
			_pairingToken = pairingToken;
		}

		/// <summary>
		/// Gets a valid bearer token, refreshing if necessary.
		/// </summary>
		public async Task<string> GetTokenAsync(CancellationToken cancellationToken = default)
		{
			// Fast path: return cached token if still valid
			if (_cachedToken != null && _tokenExpiry > DateTime.Now)
			{
				return _cachedToken.BearerToken;
			}

			// Slow path: acquire lock and refresh token
			await _refreshLock.WaitAsync(cancellationToken).ConfigureAwait(false);
			try
			{
				// Double-check after acquiring lock (another thread may have refreshed)
				if (_cachedToken != null && _tokenExpiry > DateTime.Now)
				{
					return _cachedToken.BearerToken;
				}

				Logging.WriteDebugLog("TokenProvider.GetTokenAsync() Refreshing bearer token");

				// Refresh the token
				var newToken = await RefreshTokenAsync(cancellationToken).ConfigureAwait(false);
				if (newToken != null)
				{
					_cachedToken = newToken;
					// Apply safety margin of 30 seconds to avoid edge cases
					_tokenExpiry = newToken.TokenExpires.AddSeconds(-30);
					
					Logging.WriteDebugLog("TokenProvider.GetTokenAsync() Token refreshed successfully, expires at {0}", newToken.TokenExpires);
					return newToken.BearerToken;
				}

				throw new InvalidOperationException("Failed to refresh bearer token");
			}
			finally
			{
				_refreshLock.Release();
			}
		}

		/// <summary>
		/// Forces a token refresh (used when receiving 401 responses).
		/// </summary>
		public async Task<string> ForceRefreshAsync(CancellationToken cancellationToken = default)
		{
			await _refreshLock.WaitAsync(cancellationToken).ConfigureAwait(false);
			try
			{
				Logging.WriteDebugLog("TokenProvider.ForceRefreshAsync() Forcing token refresh");
				
				var newToken = await RefreshTokenAsync(cancellationToken).ConfigureAwait(false);
				if (newToken != null)
				{
					_cachedToken = newToken;
					_tokenExpiry = newToken.TokenExpires.AddSeconds(-30);
					
					Logging.WriteDebugLog("TokenProvider.ForceRefreshAsync() Token refreshed, expires at {0}", newToken.TokenExpires);
					return newToken.BearerToken;
				}

				throw new InvalidOperationException("Failed to force refresh bearer token");
			}
			finally
			{
				_refreshLock.Release();
			}
		}

		private async Task<QueToken> RefreshTokenAsync(CancellationToken cancellationToken)
		{
			if (_pairingToken == null || string.IsNullOrEmpty(_pairingToken.Token))
			{
				Logging.WriteDebugLogError("TokenProvider.RefreshTokenAsync()", "Pairing token is null or empty");
				return null;
			}

			// Use a separate client for auth that doesn't have the BearerTokenHandler
			var client = _httpClientFactory.CreateClient("ActronQueAuth");
			
			var formContent = new System.Collections.Generic.Dictionary<string, string>
			{
				["grant_type"] = "refresh_token",
				["refresh_token"] = _pairingToken.Token,
				["client_id"] = "app"
			};

			try
			{
				var request = new HttpRequestMessage(HttpMethod.Post, "api/v0/oauth/token")
				{
					Content = new FormUrlEncodedContent(formContent)
				};

				var response = await client.SendAsync(request, cancellationToken).ConfigureAwait(false);
				
				if (!response.IsSuccessStatusCode)
				{
					Logging.WriteDebugLog("TokenProvider.RefreshTokenAsync() Failed with status {0}", response.StatusCode);
					return null;
				}

				var content = await response.Content.ReadAsStringAsync().ConfigureAwait(false);
				var jsonResponse = JObject.Parse(content);

				var queToken = new QueToken
				{
					BearerToken = (string)jsonResponse["access_token"]
				};

				var expiresInStr = (string)jsonResponse["expires_in"];
				if (int.TryParse(expiresInStr, out int expiresIn))
					queToken.TokenExpires = DateTime.Now.AddSeconds(expiresIn);
				else
					queToken.TokenExpires = DateTime.Now.AddSeconds(3600); // fallback

				// Persist token to file
				try
				{
					await File.WriteAllTextAsync(_bearerTokenFile, JsonConvert.SerializeObject(queToken)).ConfigureAwait(false);
				}
				catch (Exception ex)
				{
					Logging.WriteDebugLogError("TokenProvider.RefreshTokenAsync()", ex, "Unable to update bearer token json file.");
				}

				return queToken;
			}
			catch (Exception ex)
			{
				Logging.WriteDebugLogError("TokenProvider.RefreshTokenAsync()", ex, "Exception during token refresh.");
				return null;
			}
		}

		/// <summary>
		/// Loads cached token from file if available.
		/// </summary>
		public void LoadCachedToken()
		{
			try
			{
				if (File.Exists(_bearerTokenFile))
				{
					var json = File.ReadAllText(_bearerTokenFile);
					_cachedToken = JsonConvert.DeserializeObject<QueToken>(json);
					if (_cachedToken != null)
					{
						_tokenExpiry = _cachedToken.TokenExpires.AddSeconds(-30);
						Logging.WriteDebugLog("TokenProvider.LoadCachedToken() Loaded cached token, expires at {0}", _cachedToken.TokenExpires);
					}
				}
			}
			catch (Exception ex)
			{
				Logging.WriteDebugLogError("TokenProvider.LoadCachedToken()", ex, "Unable to load cached token.");
			}
		}
	}
}
