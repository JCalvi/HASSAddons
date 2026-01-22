using System;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace HMX.HASSActronQue
{
    internal class QueHttpClient : IDisposable
    {
        private readonly HttpClient _http;

        public QueHttpClient(HttpClient http)
        {
            _http = http ?? throw new ArgumentNullException(nameof(http));
        }

        public async Task<string> GetJsonAsync(string path, CancellationToken ct)
        {
            var resp = await _http.GetAsync(path, ct).ConfigureAwait(false);
            resp.EnsureSuccessStatusCode();
            return await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
        }

        // Methods for Authenticate, RenewToken, PostCommand, with retry/backoff logic

        public void Dispose() => _http?.Dispose();
    }
}