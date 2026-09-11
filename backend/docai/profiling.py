"""Optional named Silk profiles without coupling application code to Silk."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import ParamSpec, TypeVar, cast

from django.conf import settings

P = ParamSpec("P")
R = TypeVar("R")


def silk_profile(*, name: str) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Return Silk's decorator when enabled, otherwise preserve the target unchanged."""
    if not settings.SILKY_ENABLED:

        def passthrough(target: Callable[P, R]) -> Callable[P, R]:
            return target

        return passthrough

    from silk.profiling.profiler import silk_profile as django_silk_profile

    def decorate(target: Callable[P, R]) -> Callable[P, R]:
        @wraps(target)
        def profiled(*args: P.args, **kwargs: P.kwargs) -> R:
            # django-silk stores active profile state on the decorator instance.
            # Use one instance per invocation so concurrent requests cannot share it.
            decorator = django_silk_profile(name=name)
            wrapped = cast(Callable[P, R], decorator(target))
            return wrapped(*args, **kwargs)

        return profiled

    return decorate
