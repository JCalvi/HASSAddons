using System;
using Microsoft.Extensions.DependencyInjection;
using Polly;
using Polly.Extensions.Http;
using System.Net.Http;
using System.Threading.Tasks;

namespace HMX.HASSActronQue
{
    public static class ServiceCollectionExtensions
    {
        public static IServiceCollection AddActronQueHttpClients(this IServiceCollection services, string baseUrl, string bearerTokenFile, Func<string> getPairingTokenCallback)
        {
            // Token provider requires IHttpClientFactory + pairing token provider
            services.AddSingleton<TokenProvider>(sp => new TokenProvider(sp.GetRequiredService<IHttpClientFactory>(), bearerTokenFile, getPairingTokenCallback));
            services.AddTransient<BearerTokenHandler>();

            // Retry policy: handle transient network errors and 5xx
            var retryPolicy = HttpPolicyExtensions
                .HandleTransientHttpError()
                .Or<TaskCanceledException>()
                .WaitAndRetryAsync(new[] { TimeSpan.FromSeconds(1), TimeSpan.FromSeconds(5), TimeSpan.FromSeconds(15) },
                    onRetry: (outcome, timespan, retryAttempt, context) =>
                    {
                        Logging.WriteDebugLog("Polly retry attempt {0}: {1}", retryAttempt, outcome.Exception?.Message ?? outcome.Result?.StatusCode.ToString());
                    });

            // Circuit breaker: trip after 5 failures, hold for 30s
            var circuitBreaker = HttpPolicyExtensions
                .HandleTransientHttpError()
                .CircuitBreakerAsync(5, TimeSpan.FromSeconds(30), onBreak: (result, ts) =>
                {
                    Logging.WriteDebugLog("Polly circuit breaker opened: {0}", result.Exception?.Message ?? result.Result?.StatusCode.ToString());
                }, onReset: () =>
                {
                    Logging.WriteDebugLog("Polly circuit breaker reset.");
                });

            // Named client used for API calls (uses BearerTokenHandler)
            services.AddHttpClient("ActronQueApi", client =>
            {
                client.BaseAddress = new Uri(baseUrl);
            })
            .AddHttpMessageHandler<BearerTokenHandler>()
            .AddPolicyHandler(retryPolicy)
            .AddPolicyHandler(circuitBreaker);

            // Named client used for auth/token endpoint (no BearerTokenHandler)
            services.AddHttpClient("ActronQueAuth", client =>
            {
                client.BaseAddress = new Uri(baseUrl);
            })
            .AddPolicyHandler(retryPolicy)
            .AddPolicyHandler(circuitBreaker);

            return services;
        }
    }
}