import pytest
from django.conf import settings
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import override_settings
from rest_framework.test import APIClient


@pytest.fixture
def browser(db):
    cache.clear()
    return APIClient(enforce_csrf_checks=True)


def csrf(browser):
    response = browser.get("/api/v1/auth/session/")
    assert response.status_code == 200
    assert "no-store" in response["Cache-Control"]
    return browser.cookies[settings.CSRF_COOKIE_NAME].value


def sign_in(browser, username="viewer", password="pw"):
    return browser.post(
        "/api/v1/auth/login/",
        {"username": username, "password": password},
        format="json",
        HTTP_X_CSRFTOKEN=csrf(browser),
    )


def test_anonymous_bootstrap_and_login_csrf(browser, viewer):
    assert browser.get("/api/v1/auth/session/").json()["data"]["user"] is None
    response = browser.post(
        "/api/v1/auth/login/", {"username": "viewer", "password": "pw"}, format="json"
    )
    assert response.status_code == 403
    assert response["Content-Type"].startswith("application/json")
    assert response.json()["error_code"] == "CSRF_FAILED"
    assert settings.SESSION_COOKIE_NAME not in browser.cookies
    assert browser.get("/api/v1/dashboard/").json()["error_code"] == "NOT_AUTHENTICATED"


def test_non_staff_login_uses_django_session_and_preserves_permissions(browser, viewer):
    old_csrf = csrf(browser)
    response = sign_in(browser)
    assert response.status_code == 200
    assert response.json()["data"]["user"]["username"] == "viewer"
    assert response.json()["data"]["user"]["is_staff"] is False
    assert response.json()["data"]["user"]["tools"]["request_profiler"] is None
    assert browser.cookies[settings.CSRF_COOKIE_NAME].value != old_csrf
    assert browser.cookies[settings.SESSION_COOKIE_NAME]["httponly"]
    assert browser.get("/api/v1/dashboard/").status_code == 200
    denied = browser.post(
        "/api/v1/projects/", {"name": "Forbidden"}, format="json", HTTP_X_CSRFTOKEN=csrf(browser)
    )
    assert denied.status_code == 403
    assert denied.json()["error_code"] == "PERMISSION_DENIED"
    assert browser.get("/api/v1/auth/session/").json()["data"]["user"]["username"] == "viewer"


def test_profiler_link_is_exposed_only_to_superusers_when_enabled(admin, viewer, monkeypatch):
    from docai.api import auth

    monkeypatch.setattr(auth, "reverse", lambda name: "/admin/profiler/")
    with override_settings(SILKY_ENABLED=True):
        assert auth.user_profile(admin)["tools"]["request_profiler"] == "/admin/profiler/"
        assert auth.user_profile(viewer)["tools"]["request_profiler"] is None
    with override_settings(SILKY_ENABLED=False):
        assert auth.user_profile(admin)["tools"]["request_profiler"] is None


@pytest.mark.parametrize(
    "username,password", [("viewer", "wrong"), ("missing", "pw"), ("inactive", "pw")]
)
def test_failed_login_does_not_disclose_account_status(browser, viewer, username, password):
    User.objects.create_user("inactive", password="pw", is_active=False)
    response = sign_in(browser, username, password)
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_CREDENTIALS"
    assert response.json()["message"] == "Username or password is incorrect."
    assert browser.get("/api/v1/auth/session/").json()["data"]["user"] is None


def test_logout_requires_post_csrf_and_invalidates_session(browser, viewer):
    assert sign_in(browser).status_code == 200
    session_key = browser.cookies[settings.SESSION_COOKIE_NAME].value
    assert browser.get("/api/v1/auth/logout/").status_code == 405
    missing_csrf = browser.post("/api/v1/auth/logout/", {}, format="json")
    assert missing_csrf.status_code == 403
    assert missing_csrf.json()["error_code"] == "CSRF_FAILED"
    assert browser.get("/api/v1/auth/session/").json()["data"]["user"] is not None
    response = browser.post(
        "/api/v1/auth/logout/", {}, format="json", HTTP_X_CSRFTOKEN=csrf(browser)
    )
    assert response.status_code == 200
    assert response.json()["data"]["user"] is None
    replay = APIClient()
    replay.cookies[settings.SESSION_COOKIE_NAME] = session_key
    assert replay.get("/api/v1/auth/session/").json()["data"]["user"] is None
    assert browser.get("/api/v1/dashboard/").json()["error_code"] == "NOT_AUTHENTICATED"


def test_login_throttle(browser, viewer):
    for _ in range(10):
        assert sign_in(browser, password="wrong").status_code == 400
    assert sign_in(browser, password="wrong").status_code == 429
