using System;
using System.Net.Http;
using System.Text.Json;
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
            using var resp = await _http.GetAsync(path, HttpCompletionOption.ResponseHeadersRead, ct).ConfigureAwait(false);
            resp.EnsureSuccessStatusCode();

            await using var stream = await resp.Content.ReadAsStreamAsync(ct).ConfigureAwait(false);
            using var doc = await JsonDocument.ParseAsync(stream, cancellationToken: ct).ConfigureAwait(false);
            return doc.RootElement.GetRawText();
        }

        // Methods for Authenticate, RenewToken, PostCommand, with retry/backoff logic

        public void Dispose() => _http?.Dispose();
    }
}