"""Cookie-based sign-in for the frontend, sharing Django admin sessions."""

from django.conf import settings
from django.contrib.auth import authenticate, login, logout
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from drf_spectacular.utils import extend_schema
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework.views import APIView

from docai.api.openapi import SessionPayloadSerializer
from docai.api.permissions import roles
from docai.exceptions import DocAIError
from docai.serializers.core import LoginSerializer


def user_profile(user):
    return {
        "username": user.username,
        "is_staff": user.is_staff,
        "roles": sorted(roles(user)),
        "platform_version": settings.DOCAI["PLATFORM_VERSION"],
        "adapters": {
            "layout": settings.DOCAI["LAYOUT_ADAPTER"],
            "llm": settings.DOCAI["LLM_ADAPTER"],
            "task_runner": settings.DOCAI["TASK_RUNNER"],
        },
    }


@method_decorator(never_cache, name="dispatch")
@method_decorator(ensure_csrf_cookie, name="dispatch")
class SessionView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (AllowAny,)

    @extend_schema(responses=SessionPayloadSerializer)
    def get(self, request):
        return Response(
            {"user": user_profile(request.user) if request.user.is_authenticated else None}
        )


class LoginThrottle(AnonRateThrottle):
    scope = "login"
    rate = "10/min"


@method_decorator(never_cache, name="dispatch")
@method_decorator(csrf_protect, name="dispatch")
class LoginView(APIView):
    # SessionAuthentication checks CSRF only for authenticated users. Login must
    # also protect anonymous users, hence csrf_protect on dispatch above.
    authentication_classes = ()
    permission_classes = (AllowAny,)
    throttle_classes = (LoginThrottle,)

    @extend_schema(request=LoginSerializer, responses=SessionPayloadSerializer)
    def post(self, request):
        data = LoginSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        user = authenticate(request, **data.validated_data)
        if user is None:
            raise DocAIError(
                "Username or password is incorrect.",
                error_code="INVALID_CREDENTIALS",
                status_code=400,
            )
        login(request, user)
        return Response({"user": user_profile(user)})


@method_decorator(never_cache, name="dispatch")
@method_decorator(csrf_protect, name="dispatch")
class LogoutView(APIView):
    authentication_classes = (SessionAuthentication,)
    permission_classes = (AllowAny,)

    @extend_schema(request=None, responses=SessionPayloadSerializer)
    def post(self, request):
        logout(request)
        return Response({"user": None})
