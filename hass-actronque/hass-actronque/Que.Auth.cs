using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;
using System.IO;
using System.Net.Http;

namespace HMX.HASSActronQue
{
	public partial class Que
	{
		// NOTE: ExecuteRequestAsync is provided centrally in QueHttpHelpers.cs.
		// This file contains the pairing / bearer token logic and relies on that helper.

		private static async Task<bool> GeneratePairingToken()
		{
			long lRequestId = RequestManager.GetRequestId();
			string strPageURL = "api/v0/client/user-devices";
			bool bRetVal = true;

			Logging.WriteDebugLog("Que.GeneratePairingToken()");

			if (string.IsNullOrEmpty(_strDeviceUniqueIdentifier))
			{
				_strDeviceUniqueIdentifier = GenerateDeviceId();
				Logging.WriteDebugLog("Que.GeneratePairingToken() Device Id: {0}", _strDeviceUniqueIdentifier);

				// Update Device Id File (best-effort)
				try
				{
					await File.WriteAllTextAsync(_strDeviceIdFile, JsonConvert.SerializeObject(_strQueUser + "," + _strDeviceUniqueIdentifier)).ConfigureAwait(false);
				}
				catch (Exception eException)
				{
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", eException, "Unable to update device id json file.");
				}
			}

			var dtFormContent = new Dictionary<string, string>
			{
				["username"] = _strQueUser,
				["password"] = _strQuePassword,
				["deviceName"] = _strDeviceName,
				["client"] = "ios",
				["deviceUniqueIdentifier"] = _strDeviceUniqueIdentifier
			};

			var result = await ExecuteRequestAsync(() =>
			{
				var req = new HttpRequestMessage(HttpMethod.Post, strPageURL)
				{
					Content = new FormUrlEncodedContent(dtFormContent)
				};
				return req;
			}, _httpClientAuth, -1, lRequestId).ConfigureAwait(false);

			if (!result.Success)
			{
				if (result.StatusCode != 0)
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", lRequestId, $"Unable to process API response: {result.StatusCode}");
				bRetVal = false;
				goto Cleanup;
			}

			try
			{
				var jsonResponse = JObject.Parse(result.Content);
				var pairingTokenValue = (string)jsonResponse["pairingToken"];
				if (!string.IsNullOrEmpty(pairingTokenValue))
				{
					_pairingToken = new PairingToken(pairingTokenValue);

					// Update Token File
					try
					{
						await File.WriteAllTextAsync(_strPairingTokenFile, JsonConvert.SerializeObject(_pairingToken)).ConfigureAwait(false);
					}
					catch (Exception eException)
					{
						Logging.WriteDebugLogError("Que.GeneratePairingToken()", eException, "Unable to update pairing token json file.");
					}
				}
				else
				{
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", lRequestId, "pairingToken not found in response.");
					bRetVal = false;
				}
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", lRequestId, eException.InnerException, "Exception in HTTP response processing.");
				else
					Logging.WriteDebugLogError("Que.GeneratePairingToken()", lRequestId, eException, "Exception in HTTP response processing.");

				bRetVal = false;
			}

		Cleanup:
			if (!bRetVal)
				_pairingToken = null;

			return bRetVal;
		}

		private static async Task<bool> GenerateBearerToken()
		{
			long lRequestId = RequestManager.GetRequestId();
			bool bRetVal = true;

			Logging.WriteDebugLog("Que.GenerateBearerToken()");

			try
			{
				// Ensure token provider is initialized
				if (_tokenProvider == null)
				{
					Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, "TokenProvider not initialized.");
					return false;
				}

				var tokenObj = await _tokenProvider.GetTokenAsync().ConfigureAwait(false);
				if (tokenObj == null || string.IsNullOrEmpty(tokenObj.BearerToken))
				{
					Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, "TokenProvider did not return a token.");
					return false;
				}

				_queToken = tokenObj;

				// Do not directly mutate HttpClient.DefaultRequestHeaders here - BearerTokenHandler attaches tokens per-request.
				Logging.WriteDebugLog("Que.GenerateBearerToken() obtained token, expires {0}", _queToken.TokenExpires);

				return true;
			}
			catch (HttpRequestException eHttp)
			{
				Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, eHttp, "HTTP error during token request.");
				bRetVal = false;
			}
			catch (Exception eException)
			{
				Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, eException, "Exception generating bearer token.");
				bRetVal = false;
			}

			return bRetVal;
		}
	}
}