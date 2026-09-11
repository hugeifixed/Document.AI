from unittest.mock import patch

from docai.profiling import silk_profile


def test_silk_profile_has_no_wrapper_overhead_when_disabled(settings):
    settings.SILKY_ENABLED = False

    def operation():
        return "done"

    decorated = silk_profile(name="test operation")(operation)

    assert decorated is operation
    assert decorated() == "done"


def test_silk_profile_delegates_to_django_silk_when_enabled(settings):
    settings.SILKY_ENABLED = True

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
