using System.Net;
using System.Net.Http;
using System.Net.Http.Headers;
using System.Threading;
using System.Threading.Tasks;

namespace HMX.HASSActronQue
{
    public class BearerTokenHandler : DelegatingHandler
    {
        private readonly TokenProvider _tokenProvider;

        public BearerTokenHandler(TokenProvider tokenProvider)
        {
            _tokenProvider = tokenProvider;
        }

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var tokenObj = await _tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(false);
            var token = tokenObj?.BearerToken;
            if (!string.IsNullOrEmpty(token))
                request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);

            var response = await base.SendAsync(request, cancellationToken).ConfigureAwait(false);

            if (response.StatusCode == HttpStatusCode.Unauthorized)
            {
                // Attempt single refresh and retry
                response.Dispose();
                _tokenProvider.ClearToken();
                var newTokenObj = await _tokenProvider.GetTokenAsync(cancellationToken).ConfigureAwait(false);
                var newToken = newTokenObj?.BearerToken;
                if (!string.IsNullOrEmpty(newToken))
                {
                    request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", newToken);
                    response = await base.SendAsync(request, cancellationToken).ConfigureAwait(false);
                }
            }

            return response;
        }
    }
}