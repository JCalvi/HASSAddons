using System;
using System.Net;
using System.Net.Http;
using System.Threading.Tasks;
using Microsoft.Extensions.DependencyInjection;
using Polly;
using Polly.Extensions.Http;

namespace HMX.HASSActronQue
{
	/// <summary>
	/// Extension methods for registering HTTP clients with IHttpClientFactory and Polly policies.
	/// </summary>
	public static class ServiceRegistration
	{
		/// <summary>
		/// Configures IHttpClientFactory with named clients and Polly resilience policies.
		/// </summary>
		public static IServiceCollection AddActronQueHttpClients(
			this IServiceCollection services,
			string baseUrl,
			PairingToken pairingToken,
			string bearerTokenFile)
		{
			if (services == null) throw new ArgumentNullException(nameof(services));
			if (string.IsNullOrEmpty(baseUrl)) throw new ArgumentNullException(nameof(baseUrl));

			// Register TokenProvider as singleton
			services.AddSingleton(sp =>
			{
				var factory = sp.GetRequiredService<IHttpClientFactory>();
				var provider = new TokenProvider(factory, bearerTokenFile, pairingToken);
				// Load any cached token from disk
				provider.LoadCachedToken();
				return provider;
			});

			// Register BearerTokenHandler as transient (one per client)
			services.AddTransient<BearerTokenHandler>();

			// Configure the main API client with auth and Polly policies
			services.AddHttpClient("ActronQueApi", client =>
			{
				client.BaseAddress = new Uri(baseUrl);
				client.Timeout = System.Threading.Timeout.InfiniteTimeSpan; // Use per-request timeouts
			})
			.AddHttpMessageHandler<BearerTokenHandler>()
			.AddPolicyHandler(GetCircuitBreakerPolicy()) // Circuit breaker first to stop requests when circuit is open
			.AddPolicyHandler(GetRetryPolicy()) // Retry policy second, respects circuit breaker state
			.ConfigurePrimaryHttpMessageHandler(() => new SocketsHttpHandler
			{
				AutomaticDecompression = DecompressionMethods.All,
				PooledConnectionLifetime = TimeSpan.FromMinutes(2),
				PooledConnectionIdleTimeout = TimeSpan.FromSeconds(30),
				MaxConnectionsPerServer = 10
			});

			// Configure auth-only client (no BearerTokenHandler to avoid circular dependency)
			services.AddHttpClient("ActronQueAuth", client =>
			{
				client.BaseAddress = new Uri(baseUrl);
				client.Timeout = System.Threading.Timeout.InfiniteTimeSpan;
			})
			.AddPolicyHandler(GetRetryPolicy())
			.ConfigurePrimaryHttpMessageHandler(() => new SocketsHttpHandler
			{
				AutomaticDecompression = DecompressionMethods.All,
				PooledConnectionLifetime = TimeSpan.FromMinutes(2),
				PooledConnectionIdleTimeout = TimeSpan.FromSeconds(30),
				MaxConnectionsPerServer = 10
			});

			return services;
		}

		/// <summary>
		/// Creates a retry policy with exponential backoff for transient errors.
		/// Retries: 1s, 5s, 15s (3 attempts total).
		/// </summary>
		private static IAsyncPolicy<HttpResponseMessage> GetRetryPolicy()
		{
			return HttpPolicyExtensions
				.HandleTransientHttpError() // 5xx, 408, and network failures
				.Or<TaskCanceledException>() // Timeouts
				.OrResult(response => (int)response.StatusCode == 429) // Rate limiting
				.WaitAndRetryAsync(
					retryCount: 3,
					sleepDurationProvider: retryAttempt => retryAttempt switch
					{
						1 => TimeSpan.FromSeconds(1),
						2 => TimeSpan.FromSeconds(5),
						_ => TimeSpan.FromSeconds(15)
					},
					onRetry: (outcome, timespan, retryCount, context) =>
					{
						var statusCode = outcome.Result?.StatusCode.ToString() ?? "Exception";
						var exception = outcome.Exception?.Message ?? "None";
						Logging.WriteDebugLog(
							"Polly Retry: Attempt {0} after {1}s. Status: {2}, Exception: {3}",
							retryCount,
							timespan.TotalSeconds,
							statusCode,
							exception);
					});
		}

		/// <summary>
		/// Creates a circuit breaker policy to prevent cascading failures.
		/// Breaks after 5 consecutive failures for 30 seconds.
		/// </summary>
		private static IAsyncPolicy<HttpResponseMessage> GetCircuitBreakerPolicy()
		{
			return HttpPolicyExtensions
				.HandleTransientHttpError()
				.OrResult(response => response.StatusCode == HttpStatusCode.ServiceUnavailable)
				.CircuitBreakerAsync(
					handledEventsAllowedBeforeBreaking: 5,
					durationOfBreak: TimeSpan.FromSeconds(30),
					onBreak: (outcome, duration) =>
					{
						Logging.WriteDebugLog(
							"Polly CircuitBreaker: Circuit opened for {0}s due to {1}",
							duration.TotalSeconds,
							outcome.Exception?.Message ?? outcome.Result?.StatusCode.ToString() ?? "Unknown");
					},
					onReset: () =>
					{
						Logging.WriteDebugLog("Polly CircuitBreaker: Circuit closed, resuming normal operation");
					},
					onHalfOpen: () =>
					{
						Logging.WriteDebugLog("Polly CircuitBreaker: Circuit half-open, testing connection");
					});
		}
	}
}
