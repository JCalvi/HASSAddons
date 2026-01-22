using System;
using System.Collections.Generic;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

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
			}, _sharedHttpClient, -1, lRequestId).ConfigureAwait(false);

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
			string strPageURL = "api/v0/oauth/token";
			bool bRetVal = true;

			Logging.WriteDebugLog("Que.GenerateBearerToken()");

			var dtFormContent = new Dictionary<string, string>
			{
				["grant_type"] = "refresh_token",
				["refresh_token"] = _pairingToken?.Token ?? "",
				["client_id"] = "app"
			};

			var result = await ExecuteRequestAsync(() =>
			{
				var req = new HttpRequestMessage(HttpMethod.Post, strPageURL)
				{
					Content = new FormUrlEncodedContent(dtFormContent)
				};
				return req;
			}, _sharedHttpClient, -1, lRequestId).ConfigureAwait(false);

			if (!result.Success)
			{
				if (result.StatusCode == System.Net.HttpStatusCode.Unauthorized)
				{
					Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, "Unauthorized - refreshing pairing token.");
					_pairingToken = null;
				}
				else if (result.StatusCode == System.Net.HttpStatusCode.BadRequest)
				{
					System.Threading.Interlocked.Increment(ref _iFailedBearerRequests);

					if (_iFailedBearerRequests == _iFailedBearerRequestMaximum)
					{
						Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, "BadRequest - reached max failed attempts, clearing pairing token.");
						_pairingToken = null;
					}
					else
						Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, $"BadRequest attempt {_iFailedBearerRequests} of {_iFailedBearerRequestMaximum}");
				}
				else if (result.StatusCode != 0)
				{
					Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, $"HTTP error: {result.StatusCode}/{result.Error?.Message}");
				}
				else
				{
					// Exception already logged by ExecuteRequestAsync
				}
				bRetVal = false;
				goto Cleanup;
			}

			try
			{
				var jsonResponse = JObject.Parse(result.Content);

				var queToken = new QueToken
				{
					BearerToken = (string)jsonResponse["access_token"]
				};

				var expiresInStr = (string)jsonResponse["expires_in"];
				if (int.TryParse(expiresInStr, out int expiresIn))
					queToken.TokenExpires = DateTime.Now.AddSeconds(expiresIn);
				else
					queToken.TokenExpires = DateTime.Now.AddSeconds(3600); // fallback

				_queToken = queToken;

				_sharedHttpClient.DefaultRequestHeaders.Authorization = new System.Net.Http.Headers.AuthenticationHeaderValue("Bearer", _queToken.BearerToken);

				// Update Token File
				try
				{
					await File.WriteAllTextAsync(_strBearerTokenFile, JsonConvert.SerializeObject(_queToken)).ConfigureAwait(false);
				}
				catch (Exception eException)
				{
					Logging.WriteDebugLogError("Que.GenerateBearerToken()", eException, "Unable to update bearer token json file.");
				}
			}
			catch (Exception eException)
			{
				if (eException.InnerException != null)
					Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, eException.InnerException, "Exception in HTTP response processing.");
				else
					Logging.WriteDebugLogError("Que.GenerateBearerToken()", lRequestId, eException, "Exception in HTTP response processing.");

				bRetVal = false;
			}

			if (bRetVal)
				_iFailedBearerRequests = 0;
			else
				_queToken = null;

		Cleanup:
			return bRetVal;
		}
	}
}