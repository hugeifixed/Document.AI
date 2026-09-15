"""Authorized, privately cached aggregate metrics endpoints."""

from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView

from docai.api import permissions
from docai.api.openapi import ErrorEnvelopeSerializer
from docai.models import Dataset, Project
from docai.serializers.metrics import (
    MetricsQuerySerializer,
    MetricsResponseSerializer,
    UsageMetricsResponseSerializer,
    UsageQuerySerializer,
)
from docai.services import metrics


def authorized_projects(request, view, filters):
    projects = Project.available_objects.all()
    if filters.get("project"):
        project = get_object_or_404(projects, pk=filters["project"])
        if not permissions.can_access_project(request.user, project):
            raise PermissionDenied()
        projects = projects.filter(pk=project.pk)
    if filters.get("dataset"):
        dataset = get_object_or_404(
            Dataset.available_objects.select_related("project"),
            pk=filters["dataset"],
            project__is_removed=False,
        )
        view.check_object_permissions(request, dataset)
        if filters.get("project") and dataset.project_id != filters["project"]:
            raise ValidationError({"dataset": "Dataset does not belong to the selected project."})
        projects = projects.filter(pk=dataset.project_id)
    return [
        project.pk for project in projects if permissions.can_access_project(request.user, project)
    ]


class MetricsView(APIView):
    permission_classes = [permissions.DocAIPermission]
    query_serializer: type[serializers.Serializer] = MetricsQuerySerializer
    response_serializer: type[serializers.Serializer] = MetricsResponseSerializer
    usage = False

    def handle_exception(self, exc):
        response = super().handle_exception(exc)
        # These serializers validate URL query syntax, not a parsed business body.
        if isinstance(exc, ValidationError):
            response.status_code = 400
        return response

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "private, no-store"
        return response

    def _response(self, request):
        query = self.query_serializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        project_ids = authorized_projects(request, self, filters)
        data = metrics.snapshot(
            filters=filters,
            project_ids=project_ids,
            user=request.user,
            roles=permissions.roles(request.user),
            usage=self.usage,
        )
        return Response(self.response_serializer(data).data)

    @extend_schema(
        parameters=[MetricsQuerySerializer],
        responses={
            200: MetricsResponseSerializer,
            400: ErrorEnvelopeSerializer,
            401: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
        tags=["Metrics"],
        description="UTC operational trends. Processing filters affect only processing; current review backlog ignores dates. Durations describe recorded final attempts. Cached for 60 seconds per caller, role and scope.",
    )
    def get(self, request, **kwargs):
        return self._response(request)


class UsageMetricsView(MetricsView):
    query_serializer = UsageQuerySerializer
    response_serializer = UsageMetricsResponseSerializer
    usage = True
    action = "usage"
    read_action_roles = {"usage": permissions.OPERATOR}

    @extend_schema(
        parameters=[UsageQuerySerializer],
        responses={
            200: UsageMetricsResponseSerializer,
            400: ErrorEnvelopeSerializer,
            401: ErrorEnvelopeSerializer,
            403: ErrorEnvelopeSerializer,
            404: ErrorEnvelopeSerializer,
        },
        tags=["Metrics"],
        description="Operator-only recorded LLM responses including retries. Missing totals remain unknown; partial measurement sums known totals. No financial estimate or provider error-rate claim.",
    )
    def get(self, request, **kwargs):
        return self._response(request)
