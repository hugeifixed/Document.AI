"""Offline transport tests: no Azure calls, credentials, or external DNS needed."""

from __future__ import annotations

import asyncio
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import Mock

import pytest
from azure.core.exceptions import ServiceRequestError
from azure.core.pipeline.transport import HttpRequest, RequestsTransport

from docai.adapters import azure_identity
from docai.adapters.layout.azure_di import AzureDocumentIntelligenceLayout
from docai.adapters.llm.azure_openai import AzureOpenAILangChainLLM


@pytest.fixture
def network_env(monkeypatch):
    # Test transports must never inherit a developer's real corporate proxy/CA.
    for name in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "REQUESTS_CA_BUNDLE",
        "CURL_CA_BUNDLE",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
    ):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)


@pytest.fixture
def rejecting_proxy(network_env):
    connections = []

    class Proxy(BaseHTTPRequestHandler):
        def do_CONNECT(self):  # noqa: N802 -- HTTP handler API
            connections.append(self.path)
            self.send_response(502)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Proxy)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", connections
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_both_azure_client_stacks_use_the_environment_proxy(settings, monkeypatch, rejecting_proxy):
    from openai import APIConnectionError

    proxy, connections = rejecting_proxy
    monkeypatch.setenv("HTTPS_PROXY", proxy)
    settings.DOCAI = {
        **settings.DOCAI,
        "AZURE_TIMEOUT_S": 1,
        "AZURE_OPENAI_ENDPOINT": "https://azure.invalid/",
    }
    settings.AZURE_OPENAI_API_KEY = "offline-test-key"

    with (
        RequestsTransport(**azure_identity.azure_transport_options()) as transport,
        pytest.raises(ServiceRequestError),
    ):
        transport.send(HttpRequest("GET", "https://azure.invalid/"))

    model = AzureOpenAILangChainLLM()._model("offline-model", {"timeout_s": 1})
    try:
        with pytest.raises(APIConnectionError):
            model.root_client.models.list()
    finally:
        model.root_client.close()
        asyncio.run(model.root_async_client.close())
    assert connections == ["azure.invalid:443", "azure.invalid:443"]


def test_di_respects_no_proxy_and_requests_ca_bundle(network_env, monkeypatch, tmp_path):
    bundle = tmp_path / "institution.pem"
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.invalid:90")
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1,169.254.169.254")
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(bundle))
    with RequestsTransport(**azure_identity.azure_transport_options()) as transport:
        external = transport.session.merge_environment_settings(
            "https://azure.invalid/", {}, None, None, True
        )
        local = transport.session.merge_environment_settings(
            "http://127.0.0.1/", {}, None, None, True
        )
    assert external["proxies"]["https"] == "http://proxy.invalid:90"
    assert external["verify"] == str(bundle)
    assert "https" not in local["proxies"]


def test_openai_reads_ssl_cert_file_without_a_custom_client(
    network_env, monkeypatch, tmp_path, settings
):
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing-ca.pem"))
    settings.AZURE_OPENAI_API_KEY = "offline-test-key"
    settings.DOCAI = {**settings.DOCAI, "AZURE_OPENAI_ENDPOINT": "https://azure.invalid/"}
    assert azure_identity.azure_openai_http_options() == {}
    with pytest.raises(FileNotFoundError):
        AzureOpenAILangChainLLM()._model("offline-model", {})


def test_local_tls_override_reaches_both_clients_and_di(
    settings, monkeypatch, network_env, tmp_path
):
    import azure.ai.documentintelligence

    settings.AZURE_VERIFY_SSL = False
    settings.AZURE_DI_API_KEY = "offline-test-key"
    settings.DOCAI = {
        **settings.DOCAI,
        "AZURE_DI_ENDPOINT": "https://di.invalid/",
        "AZURE_TIMEOUT_S": 7,
    }
    factory = Mock()
    monkeypatch.setattr(azure.ai.documentintelligence, "DocumentIntelligenceClient", factory)
    AzureDocumentIntelligenceLayout()._client()
    assert factory.call_args.kwargs["connection_verify"] is False
    assert factory.call_args.kwargs["connection_timeout"] == 7
    assert factory.call_args.kwargs["read_timeout"] == 7
    azure_identity._local_unverified_openai_clients.cache_clear()
    monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "missing-ca.pem"))
    options = azure_identity.azure_openai_http_options()
    try:
        assert options is azure_identity.azure_openai_http_options()
        assert set(options) == {"http_client", "http_async_client"}
        # Construction with verify=False also works without a CA file; no request is sent.
        assert options["http_client"].is_closed is False
        assert options["http_async_client"].is_closed is False
    finally:
        options["http_client"].close()
        asyncio.run(options["http_async_client"].aclose())
        azure_identity._local_unverified_openai_clients.cache_clear()
