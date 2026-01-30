using System;
using System.Net.Http;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Http;                 // IHttpClientFactory
using Microsoft.Extensions.Http.Resilience;      // AddStandardResilienceHandler

namespace HMX.HASSActronQue
{
    public static class ServiceCollectionExtensions
    {
        public static IServiceCollection AddActronQueHttpClients(this IServiceCollection services, string baseUrl, string bearerTokenFile, Func<string> getPairingTokenCallback)
        {
            // Token provider requires IHttpClientFactory + pairing token provider
            services.AddSingleton<TokenProvider>(sp => new TokenProvider(sp.GetRequiredService<IHttpClientFactory>(), bearerTokenFile, getPairingTokenCallback));
            services.AddTransient<BearerTokenHandler>();

            // Attach Microsoft.Extensions.Http.Resilience standard handler to named HttpClients.
            // This uses documented defaults (rate limiter, total timeout, retry, circuit breaker, attempt timeout).
            services.AddHttpClient("ActronQueApi", client =>
            {
                client.BaseAddress = new Uri(baseUrl);
            })
            .AddHttpMessageHandler<BearerTokenHandler>()
            .AddStandardResilienceHandler();

            services.AddHttpClient("ActronQueAuth", client =>
            {
                client.BaseAddress = new Uri(baseUrl);
            })
            .AddStandardResilienceHandler();

            return services;
        }
    }
}