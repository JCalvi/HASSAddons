using System;
using System.Net.Http;
using System.Threading;
using System.Threading.Tasks;

namespace HMX.HASSActronQue
{
    internal class QueHttpClient : IDisposable
    {
        private readonly HttpClient _http;
        // When true this wrapper owns and should dispose the inner HttpClient.
        private readonly bool _ownsClient;

        public QueHttpClient(HttpClient http, bool ownsClient = false)
        {
            _http = http ?? throw new ArgumentNullException(nameof(http));
            _ownsClient = ownsClient;
        }

        public async Task<string> GetJsonAsync(string path, CancellationToken ct)
        {
            var resp = await _http.GetAsync(path, ct).ConfigureAwait(false);
            resp.EnsureSuccessStatusCode();
            return await resp.Content.ReadAsStringAsync().ConfigureAwait(false);
        }

        // Methods for Authenticate, RenewToken, PostCommand, with retry/backoff logic
        // (left unchanged)

        public void Dispose()
        {
            // Only dispose the inner HttpClient if this wrapper explicitly owns it.
            if (_ownsClient)
            {
                try { _http?.Dispose(); } catch { }
            }
        }
    }
}