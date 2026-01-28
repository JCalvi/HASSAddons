using System;
using System.Linq;
using System.Net.Http;
using System.Reflection;
using Microsoft.Extensions.DependencyInjection;

namespace HMX.HASSActronQue
{
    public partial class Que
    {
        private static readonly object _initLock = new object();
        private static bool _httpInitialized = false;

        // Call this once at startup before making HTTP requests.
        public static void InitializeHttpClients()
        {
            // Fast path
            if (_httpInitialized) return;

            lock (_initLock)
            {
                if (_httpInitialized) return;

                try
                {
                    var services = new ServiceCollection();
                    services.AddHttpClient();

                    // register Actron clients and TokenProvider; supply pairing token callback
                    services.AddActronQueHttpClients(_strBaseURLQue, _strBearerTokenFile, () => _pairingToken?.Token ?? "");

                    var provider = services.BuildServiceProvider();

                    // Resolve IHttpClientFactory at runtime via reflection to avoid compile-time type issues in some build environments
                    var factoryType = AppDomain.CurrentDomain.GetAssemblies()
                        .SelectMany(a =>
                        {
                            try { return a.GetTypes(); }
                            catch { return Array.Empty<Type>(); }
                        })
                        .FirstOrDefault(t => t.IsInterface && t.Name == "IHttpClientFactory");

                    if (factoryType == null)
                        throw new InvalidOperationException("IHttpClientFactory type not found in loaded assemblies. Ensure Microsoft.Extensions.Http is available at runtime.");

                    var factoryObj = provider.GetService(factoryType);
                    if (factoryObj == null)
                        throw new InvalidOperationException("IHttpClientFactory service not registered in the ServiceProvider.");

                    // Use reflection to call CreateClient(string)
                    var createClientMethod = factoryType.GetMethod("CreateClient", new Type[] { typeof(string) });
                    if (createClientMethod == null)
                        throw new InvalidOperationException("IHttpClientFactory.CreateClient(string) method not found.");

                    _httpClient = (HttpClient)createClientMethod.Invoke(factoryObj, new object[] { "ActronQueApi" });
                    _httpClientAuth = (HttpClient)createClientMethod.Invoke(factoryObj, new object[] { "ActronQueAuth" });
                    _httpClientCommands = _httpClient; // use same API client for commands

                    // TokenProvider instance
                    _tokenProvider = provider.GetRequiredService<TokenProvider>();

                    Logging.WriteDebugLog("InitializeHttpClients() completed. HttpClient instances initialized (GetHashCode: Api={0}, Auth={1})",
                        _httpClient?.GetHashCode() ?? 0, _httpClientAuth?.GetHashCode() ?? 0);

                    _httpInitialized = true;
                }
                catch (Exception ex)
                {
                    Logging.WriteDebugLogError("Que.InitializeHttpClients()", ex, "Failed to initialize HTTP clients.");
                    throw;
                }
            }
        }
    }
}