using System;
using System.Collections.Generic;
using System.IO;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace HMX.HASSActronQue
{
	public class TokenProvider
	{
		private readonly IHttpClientFactory _httpClientFactory;
		private readonly string _tokenFilePath;
		private readonly int _tokenRefreshBufferSeconds;		
		private readonly Func<string> _getPairingToken;
		private QueToken _currentToken;
		private readonly SemaphoreSlim _refreshLock = new SemaphoreSlim(1, 1);

		// Reusable JSON settings for this class
		private static readonly JsonSerializerSettings _jsonSettings = new JsonSerializerSettings
		{
			NullValueHandling = NullValueHandling.Ignore,
			DefaultValueHandling = DefaultValueHandling.Ignore,
			Formatting = Formatting.None
		};

		public TokenProvider(IHttpClientFactory httpClientFactory, string tokenFilePath, Func<string> getPairingToken, int tokenRefreshBufferSeconds = 300)
		{
			_httpClientFactory = httpClientFactory ?? throw new ArgumentNullException(nameof(httpClientFactory));
			_tokenFilePath = tokenFilePath ?? throw new ArgumentNullException(nameof(tokenFilePath));
			_getPairingToken = getPairingToken ?? throw new ArgumentNullException(nameof(getPairingToken));
			_tokenRefreshBufferSeconds = tokenRefreshBufferSeconds;
			LoadTokenFromFile();
		}

		private void LoadTokenFromFile()
		{
			try
			{
				if (File.Exists(_tokenFilePath))
				{
					var content = File.ReadAllText(_tokenFilePath);
					_currentToken = JsonConvert.DeserializeObject<QueToken>(content);

					// Ensure TokenExpires is treated as UTC (avoid Kind/Timezone mismatch)
					if (_currentToken != null)
					{
						_currentToken.TokenExpires = DateTime.SpecifyKind(_currentToken.TokenExpires, DateTimeKind.Utc);
						Logging.WriteDebugLog("TokenProvider: loaded token from file, expires {0}", _currentToken.TokenExpires);
					}
				}
			}
			catch
			{
				// ignore - will request new token when needed
			}
		}

		// Returns QueToken (cached or newly fetched). Throws on HTTP failure.
		public async Task<QueToken> GetTokenAsync(CancellationToken ct = default)
		{
			if (_currentToken != null && _currentToken.TokenExpires > DateTime.UtcNow.AddMinutes(5))
				return _currentToken;

			await _refreshLock.WaitAsync(ct).ConfigureAwait(false);
			try
			{
				if (_currentToken != null && _currentToken.TokenExpires > DateTime.UtcNow.AddSeconds(30))
					return _currentToken;

				var pairingRefresh = _getPairingToken?.Invoke() ?? "";
				var client = _httpClientFactory.CreateClient("ActronQueAuth");

				var dtFormContent = new Dictionary<string, string>
				{
					["grant_type"] = "refresh_token",
					["refresh_token"] = pairingRefresh,
					["client_id"] = "app"
				};

				var req = new HttpRequestMessage(HttpMethod.Post, "api/v0/oauth/token")
				{
					Content = new FormUrlEncodedContent(dtFormContent)
				};

				var resp = await client.SendAsync(req, ct).ConfigureAwait(false);
				var body = await resp.Content.ReadAsStringAsync().ConfigureAwait(false);

				if (!resp.IsSuccessStatusCode)
				{
					Logging.WriteDebugLogError("TokenProvider.GetTokenAsync()", $"Token endpoint returned {resp.StatusCode}: {body}");
					throw new HttpRequestException($"Failed to obtain token: {resp.StatusCode} {body}");
				}

				var json = JObject.Parse(body);
				var queToken = new QueToken
				{
					BearerToken = (string)json["access_token"]
				};

				if (int.TryParse((string)json["expires_in"], out int expiresIn))
					queToken.TokenExpires = DateTime.UtcNow.AddSeconds(expiresIn);
				else
					queToken.TokenExpires = DateTime.UtcNow.AddHours(1);

				_currentToken = queToken;

				try
				{
					await File.WriteAllTextAsync(_tokenFilePath, JsonConvert.SerializeObject(_currentToken, _jsonSettings)).ConfigureAwait(false);
				}
				catch
				{
					// non-fatal
				}

				Logging.WriteDebugLog("TokenProvider: refreshed token, expires {0}", _currentToken.TokenExpires);
				return _currentToken;
			}
			finally
			{
				_refreshLock.Release();
			}
		}

		// Forcibly clear token (e.g. on bad refresh)
		public void ClearToken()
		{
			_currentToken = null;
		}
	}
}