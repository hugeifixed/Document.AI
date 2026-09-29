"""Operator-only guided workflow playground transport."""

from __future__ import annotations

from django.utils import timezone
from django.utils.cache import patch_cache_control
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser

from docai.api.envelope import SuccessResponse
from docai.api.permissions import OPERATOR, DocAIPermission, can_access_project
from docai.exceptions import ValidationFailed
from docai.models import PlaygroundSession
from docai.services import playground


class PlaygroundCreateSerializer(serializers.Serializer):
    project = serializers.UUIDField()


class PlaygroundGenerateSerializer(serializers.Serializer):
    goal = serializers.CharField(required=False, default="", allow_blank=True, max_length=1000)
    workflow_type = serializers.ChoiceField(
        choices=(
            "extract_structured",
            "extract_unstructured",
            "unbundle_classify_extract",
        )
    )
    refinement = serializers.CharField(
        required=False, default="", allow_blank=True, max_length=1000
    )


class PlaygroundDocumentSerializer(serializers.Serializer):
    document_id = serializers.UUIDField()


class PlaygroundUploadSerializer(serializers.Serializer):
    file = serializers.FileField(help_text="One private sample; the session holds at most three.")


class PlaygroundSampleSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    document_id = serializers.UUIDField(allow_null=True)
    filename = serializers.CharField()
    units = serializers.IntegerField()
    source_kind = serializers.ChoiceField(choices=("dataset", "temporary"))


class PlaygroundUsageSerializer(serializers.Serializer):
    input_tokens = serializers.IntegerField()
    cached_input_tokens = serializers.IntegerField()
    output_tokens = serializers.IntegerField()


class PlaygroundResultSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    project = serializers.UUIDField()
    expires_at = serializers.DateTimeField()
    last_activity_at = serializers.DateTimeField()
    status = serializers.CharField()
    goal = serializers.CharField()
    workflow_type = serializers.CharField()
    error_code = serializers.CharField()
    error_message = serializers.CharField()
    samples = PlaygroundSampleSerializer(many=True)
    proposal = serializers.JSONField()
    config = serializers.JSONField(allow_null=True)
    usage = PlaygroundUsageSerializer()


class PlaygroundSummarySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    status = serializers.CharField()
    goal = serializers.CharField()
    workflow_type = serializers.CharField()
    expires_at = serializers.DateTimeField()
    last_activity_at = serializers.DateTimeField()


class PlaygroundDeletedSerializer(serializers.Serializer):
    deleted = serializers.BooleanField()


class PlaygroundSessionViewSet(viewsets.GenericViewSet):
    queryset = PlaygroundSession.objects.all()
    serializer_class = PlaygroundResultSerializer
    permission_classes = [DocAIPermission]
    write_role = OPERATOR
    read_action_roles = {"list": OPERATOR, "retrieve": OPERATOR}
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def _response(self, data, *, code=200):
        response = SuccessResponse(data, status=code, message="Playground session")
        patch_cache_control(response, private=True, no_store=True)
        return response

    def _session(self, request, pk):
        return playground.get_session(pk, request.user)

    @extend_schema(tags=["Workflow playground"], responses=PlaygroundSummarySerializer(many=True))
    def list(self, request, **kwargs):
        sessions = PlaygroundSession.objects.filter(
            created_by=request.user, expires_at__gt=timezone.now()
        )
        project_id = request.query_params.get("project")
        if project_id:
            project_id = serializers.UUIDField().run_validation(project_id)
            sessions = sessions.filter(project_id=project_id)
        sessions = sessions.order_by("-last_activity_at", "-created")
        return self._response(
            [
                {
                    "id": str(item.pk),
                    "status": item.status,
                    "goal": item.goal,
                    "workflow_type": item.workflow_type,
                    "expires_at": item.expires_at,
                    "last_activity_at": item.last_activity_at,
                }
                for item in sessions.select_related("project")
                if can_access_project(request.user, item.project)
            ]
        )

    @extend_schema(
        tags=["Workflow playground"],
        request=PlaygroundCreateSerializer,
        responses={201: PlaygroundResultSerializer},
    )
    def create(self, request, **kwargs):
        data = PlaygroundCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        session = playground.create_session(data.validated_data["project"], request.user)
        return self._response(playground.result(session), code=status.HTTP_201_CREATED)

    @extend_schema(tags=["Workflow playground"], responses=PlaygroundResultSerializer)
    def retrieve(self, request, pk=None, **kwargs):
        return self._response(playground.result(self._session(request, pk)))

    @extend_schema(tags=["Workflow playground"], responses=PlaygroundDeletedSerializer)
    def destroy(self, request, pk=None, **kwargs):
        playground.delete_session(self._session(request, pk))
        return self._response({"deleted": True})

    @action(detail=True, methods=["post"], url_path="samples")
    @extend_schema(
        tags=["Workflow playground"],
        request=PlaygroundUploadSerializer,
        responses={201: PlaygroundResultSerializer},
    )
    def samples(self, request, pk=None, **kwargs):
        session = self._session(request, pk)
        uploaded = request.FILES.get("file")
        if uploaded is None:
            raise ValidationFailed("Attach one file at a time using the file field.")
        playground.attach_upload(session, uploaded)
        return self._response(playground.result(session), code=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="documents")
    @extend_schema(
        tags=["Workflow playground"],
        request=PlaygroundDocumentSerializer,
        responses={201: PlaygroundResultSerializer},
    )
    def documents(self, request, pk=None, **kwargs):
        data = PlaygroundDocumentSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        session = self._session(request, pk)
        playground.attach_document(session, data.validated_data["document_id"])
        return self._response(playground.result(session), code=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path="samples/delete")
    @extend_schema(tags=["Workflow playground"], responses=PlaygroundResultSerializer)
    def delete_samples(self, request, pk=None, **kwargs):
        session = self._session(request, pk)
        playground.delete_samples(session)
        return self._response(playground.result(session))

    @action(detail=True, methods=["post"], url_path="generate")
    @extend_schema(
        tags=["Workflow playground"],
        request=PlaygroundGenerateSerializer,
        responses={202: PlaygroundResultSerializer},
    )
    def generate(self, request, pk=None, **kwargs):
        data = PlaygroundGenerateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        session = self._session(request, pk)
        playground.queue_generation(session, **data.validated_data)
        session.refresh_from_db()
        return self._response(playground.result(session), code=status.HTTP_202_ACCEPTED)

    @action(detail=True, methods=["put"], url_path="proposal")
    @extend_schema(
        tags=["Workflow playground"],
        request=serializers.JSONField(),
        responses=PlaygroundResultSerializer,
    )
    def proposal(self, request, pk=None, **kwargs):
        session = self._session(request, pk)
        playground.update_proposal(session, request.data)
        return self._response(playground.result(session))
