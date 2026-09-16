# Azure proxies and certificate trust

Azure Document Intelligence, Azure OpenAI, and service-principal token acquisition support
the standard proxy environment variables. The SDKs handle proxy negotiation; DocAI does not
add a forwarding service. Supply these values to **both web and worker processes** and restart
them after changes. A running process retains its credential/client configuration.

## Local proxy

In the ignored `backend/.env`, when your proxy is listening on port 9000:

```dotenv
HTTP_PROXY=http://127.0.0.1:9000
HTTPS_PROXY=http://127.0.0.1:9000
NO_PROXY=localhost,127.0.0.1,::1,169.254.169.254
AZURE_VERIFY_SSL=true
```

`127.0.0.1` refers to the machine/container running Python. In OpenShift it does not refer to
your laptop. Use the deployment's reachable proxy address there. For example, replacing the
placeholder domain with the real institution hostname:

```dotenv
HTTP_PROXY=http://vz-proxy.example.net:90
HTTPS_PROXY=http://vz-proxy.example.net:90
NO_PROXY=localhost,127.0.0.1,::1,169.254.169.254
```

The proxy URL requires `://`. `HTTPS_PROXY=http://...` is normal: the client connects to an HTTP
proxy and uses CONNECT for the HTTPS target. Keep `AZURE_DI_ENDPOINT` and `AZURE_OPENAI_ENDPOINT`
as the actual Azure resource roots, not the proxy URL. Leave proxy variables **unset** for direct
connections. Lowercase proxy variables may also be honored by the SDKs; avoid conflicting cases.

`NO_PROXY` is a comma-separated bypass list. The metadata IP bypass supports managed identity
where that host is used; add deployment-specific identity endpoints or internal hosts as needed.
Do not add Azure service hosts to the bypass list when those services must go through the proxy.
Standard proxy variables can also affect other outbound HTTP libraries in the same process.

## Institutional CA certificates

If the proxy intercepts TLS, request the institution's approved PEM CA bundle. Keep verification
enabled and configure **both** HTTP client stacks with a bundle that contains the required trust roots:

```dotenv
REQUESTS_CA_BUNDLE=/etc/docai/certs/institution-ca.pem
SSL_CERT_FILE=/etc/docai/certs/institution-ca.pem
AZURE_VERIFY_SSL=true
```

For Windows, `C:/DocAI/certs/institution-ca.pem` avoids slash-escaping ambiguity. Both paths must
exist in the runtime; a path on a developer laptop does not carry into a container. These settings
select a CA bundle rather than automatically appending certificates to an existing bundle.

| Client | Certificate setting |
| --- | --- |
| Azure identity / Document Intelligence (Requests transport) | `REQUESTS_CA_BUNDLE` |
| Azure OpenAI / LangChain (OpenAI HTTP client) | `SSL_CERT_FILE` (or the client's `SSL_CERT_DIR`) |

Azure identity remains `DefaultAzureCredential`. Service-principal configuration still uses
`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, and `AZURE_CLIENT_SECRET`; the proxy must also allow access
to the configured Microsoft identity authority. Azure CLI authentication is a separate process
with its own networking/trust configuration; the app's local TLS flag does not reconfigure `az`.

## Temporary local TLS debugging

`OPENAI_VERIFY_SSL=false` is **not** a setting read by this application. For a temporary local test:

```dotenv
AZURE_VERIFY_SSL=false
```

This disables certificate verification for DI, SDK-managed Azure identity requests, and OpenAI HTTP clients.
It logs a startup warning. RND, QA, UAT, and production settings reject this option; install the
CA bundle instead. Restore `true` after debugging. Do not disable Python TLS globally or suppress
certificate warnings. No API keys, proxy passwords, or client secrets belong in committed templates.

## Diagnosing connectivity

Startup logs report whether proxy environment settings and custom CA bundles are configured,
whether verification is enabled, and the Azure I/O timeout. They omit proxy URLs, usernames,
passwords, endpoints, CA filesystem paths, and token values. This confirms configuration, not connectivity.

`/health/` DNS checks run from the application host and do not traverse HTTP proxies. A forward
proxy may resolve Azure hostnames itself, so a local Azure DNS failure is not proof that the proxied
API request will fail. Conversely, DNS success does not prove CONNECT/TLS/authentication works.
To monitor the institutional proxy hostname itself, add it to the existing diagnostics configuration:

```dotenv
DOCAI_HEALTH_DNS_ENDPOINTS={"outbound_proxy":"vz-proxy.example.net"}
```

This checks proxy-host DNS only, not whether its port accepts connections or permits Azure traffic.
Verify an authorized small DI/LLM request through the institution's actual proxy before deployment.
Automated transport tests use a loopback-only rejecting proxy and never send documents to Azure.
