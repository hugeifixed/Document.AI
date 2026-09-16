"""Docs are part of the deployed access boundary, even when their content is static."""

import base64
from importlib.resources import files
from unittest.mock import patch

import pytest
from django.conf import settings
from django.test import override_settings
from django.urls import reverse, set_script_prefix
from rest_framework.test import APIClient, APIRequestFactory

from docai.api.documentation import AgentGuideView

PROTECTED_DOCS = ["/api/docs/", "/api/docs/scalar/", "/api/llms.txt", "/api/docs/integration.md"]


@pytest.mark.parametrize("url", PROTECTED_DOCS)
def test_deployed_documentation_requires_authentication(url):
    with override_settings(
        SPECTACULAR_SETTINGS={
            **settings.SPECTACULAR_SETTINGS,
            "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
        }
    ):
        response = APIClient().get(url)
    assert response.status_code in (401, 403)
    assert response["Cache-Control"] == "private, no-store"


@pytest.mark.django_db
@pytest.mark.parametrize("url", PROTECTED_DOCS)
def test_deployed_documentation_is_available_to_authenticated_reader(url, viewer):
    client = APIClient()
    client.force_authenticate(viewer)
    with (
        override_settings(
            DOCAI_SCALAR_ENABLED=True,
            SPECTACULAR_SETTINGS={
                **settings.SPECTACULAR_SETTINGS,
                "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
            },
        ),
        patch("docai.api.documentation.finders.find", return_value="installed.js"),
    ):
        response = client.get(url)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-store"
    assert "Cookie" in response["Vary"]
    assert "Authorization" in response["Vary"]
    assert 'rel="describedby"' in response["Link"]


def test_agent_guide_is_plain_text_curated_and_does_not_generate_schema():
    with patch("drf_spectacular.generators.SchemaGenerator.get_schema") as generate:
        response = APIClient().get("/api/llms.txt")
    generate.assert_not_called()
    assert response.status_code == 200
    assert response["Content-Type"] == "text/plain; charset=utf-8"
    text = response.content.decode()
    assert "Idempotency-Key" in text
    assert "Retry-After" in text
    assert "Lists need row-association review" in text
    assert "quality indicators" in text
    assert "/api/schema/?format=json" in text
    assert "/api/docs/integration.md" in text


def test_integration_guide_is_the_packaged_canonical_source():
    response = APIClient().get("/api/docs/integration.md", HTTP_ACCEPT="text/markdown")
    assert response.status_code == 200
    assert response["Content-Type"] == "text/markdown; charset=utf-8"
    assert response.content.decode() == files("docai").joinpath("docs/integration.md").read_text()


@pytest.mark.django_db
def test_agent_can_use_the_configured_documentation_authenticator(viewer):
    with override_settings(
        SPECTACULAR_SETTINGS={
            **settings.SPECTACULAR_SETTINGS,
            "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
            "SERVE_AUTHENTICATION": ["rest_framework.authentication.BasicAuthentication"],
        }
    ):
        client = APIClient()
        assert client.get("/api/llms.txt").status_code == 401
        token = base64.b64encode(f"{viewer.username}:pw".encode()).decode()
        response = client.get("/api/llms.txt", HTTP_AUTHORIZATION=f"Basic {token}")
        assert response.status_code == 200


def test_root_discovery_is_public_and_contains_no_operation_inventory():
    with override_settings(
        SPECTACULAR_SETTINGS={
            **settings.SPECTACULAR_SETTINGS,
            "SERVE_PERMISSIONS": ["rest_framework.permissions.IsAuthenticated"],
        }
    ):
        response = APIClient().get("/llms.txt")
    assert response.status_code == 200
    assert "authentication" in response.content.decode()
    assert "/api/llms.txt" in response.content.decode()
    assert "/api/v1/" not in response.content.decode()


def test_documentation_links_honor_application_mount_prefix():
    set_script_prefix("/docai/")
    try:
        response = AgentGuideView.as_view()(APIRequestFactory().get("/api/llms.txt"))
        response.render()
        assert reverse("schema") + "?format=json" in response.content.decode()
        assert "/docai/api/docs/integration.md" in response.content.decode()
    finally:
        set_script_prefix("/")


def test_scalar_is_optional_and_disabled_links_are_not_advertised():
    with override_settings(DOCAI_SCALAR_ENABLED=False):
        assert APIClient().get("/api/docs/scalar/").status_code == 404
        assert b"/api/docs/scalar/" not in APIClient().get("/api/llms.txt").content
        assert b"/api/docs/scalar/" not in APIClient().get("/api/docs/").content


def test_scalar_missing_assets_has_actionable_fallback_without_cdn():
    with (
        override_settings(DOCAI_SCALAR_ENABLED=True),
        patch("docai.api.documentation.finders.find", return_value=None),
    ):
        response = APIClient().get("/api/docs/scalar/")
    assert response.status_code == 503
    assert b"Scalar assets are not installed" in response.content
    assert b"/api/docs/" in response.content
    assert b"cdn.jsdelivr" not in response.content


def test_scalar_uses_local_assets_and_disables_external_services():
    with (
        override_settings(DOCAI_SCALAR_ENABLED=True),
        patch("docai.api.documentation.finders.find", return_value="installed.js"),
    ):
        response = APIClient().get("/api/docs/scalar/")
    assert response.status_code == 200
    config = response.data["scalar_config"]
    assert config["url"] == "/api/schema/?format=json"
    assert config["telemetry"] is False
    assert config["persistAuth"] is False
    assert config["withDefaultFonts"] is False
    assert config["agent"] == {"disabled": True}
    assert config["mcp"] == {"disabled": True}
    assert config["hideClientButton"] is True
    assert config["proxyUrl"] == ""
    assert response.cookies[settings.CSRF_COOKIE_NAME]
    assert b"/static/docai/vendor/scalar/1.68.0/standalone.js" in response.content
    assert b"/static/docai/img/mark-rings.svg" in response.content
    assert "connect-src 'self'" in response["Content-Security-Policy"]
    assert b'id="api-reference"' not in response.content


@pytest.mark.parametrize("url", PROTECTED_DOCS + ["/llms.txt"])
def test_documentation_never_accepts_mutations(url):
    assert APIClient().post(url).status_code == 405
