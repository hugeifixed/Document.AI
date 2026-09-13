from unittest.mock import patch

import pytest

from docai.profiling import should_profile_silk_request, silk_profile


@pytest.mark.parametrize(
    ("method", "path", "expected"),
    [
        ("POST", "/api/v1/datasets/id/upload/", True),
        ("PATCH", "/api/v1/projects/id/", True),
        ("GET", "/api/v1/runs/", False),
        ("GET", "/api/v1/runs/id/progress/", False),
        ("POST", "/api/v1/auth/login/", False),
        ("GET", "/admin/profiler/", False),
    ],
)
def test_silk_intercepts_api_mutations_without_polling(method, path, expected):
    request = type("Request", (), {"method": method, "path_info": path})()

    assert should_profile_silk_request(request) is expected


def test_silk_profile_has_no_wrapper_overhead_when_disabled(settings):
    settings.SILKY_ENABLED = False

    def operation():
        return "done"

    decorated = silk_profile(name="test operation")(operation)

    assert decorated is operation
    assert decorated() == "done"


def test_silk_profile_delegates_to_django_silk_when_enabled(settings):
    settings.SILKY_ENABLED = True
    if "silk" not in settings.INSTALLED_APPS:
        settings.INSTALLED_APPS = [*settings.INSTALLED_APPS, "silk"]

    def operation():
        return "done"

    def package_decorator(target):
        def wrapped():
            return target()

        return wrapped

    with patch("silk.profiling.profiler.silk_profile", return_value=package_decorator) as profiler:
        decorated = silk_profile(name="test operation")(operation)
        result = decorated()
        second_result = decorated()

    assert profiler.call_count == 2
    profiler.assert_called_with(name="test operation")
    assert result == "done"
    assert second_result == "done"
