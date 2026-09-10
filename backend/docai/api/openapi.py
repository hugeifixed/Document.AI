"""OpenAPI presentation and small documentation-only serializers.

The API uses a global response renderer, so drf-spectacular cannot infer the
success envelope on its own. ``DocAIAutoSchema`` keeps the generated contract
aligned with the bytes clients actually receive and provides consistent tags,
summaries, response descriptions, and role hints without coupling views to UI
copy.
"""

from __future__ import annotations

from typing import Any

from drf_spectacular.openapi import AutoSchema
from drf_spectacular.utils import OpenApiResponse
from rest_framework import serializers
from rest_framework.permissions import SAFE_METHODS, AllowAny


class AdapterSelectionSerializer(serializers.Serializer):
    layout = serializers.CharField(help_text="Active OCR/layout adapter.")
    llm = serializers.CharField(help_text="Active language-model adapter.")
    task_runner = serializers.CharField(help_text="Active background task runner.")


class UserProfileSerializer(serializers.Serializer):
    username = serializers.CharField()
    is_staff = serializers.BooleanField()
    roles = serializers.ListField(
        child=serializers.CharField(),
        help_text="Django groups that authorize Document AI actions.",
    )
    platform_version = serializers.CharField()
    adapters = AdapterSelectionSerializer()


class SessionPayloadSerializer(serializers.Serializer):
    user = UserProfileSerializer(
        allow_null=True,
        help_text="The signed-in user, or null when no session is active.",
    )


class ErrorEnvelopeSerializer(serializers.Serializer):
    success = serializers.BooleanField(default=False)
    message = serializers.CharField(help_text="Safe, human-readable error summary.")
    errors = serializers.JSONField(
        help_text="Field-level or structured details; empty when none are available."
    )
    error_code = serializers.CharField(
        help_text="Stable machine-readable code such as VALIDATION_ERROR or NOT_FOUND."
    )
    trace_id = serializers.CharField(
        help_text="Correlation ID to include when reporting or searching for this failure."
    )


class ReasonRequestSerializer(serializers.Serializer):
    reason = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Optional audit note explaining the action.",
    )


class DatasetUploadRequestSerializer(serializers.Serializer):
    files = serializers.ListField(
        child=serializers.FileField(),
        min_length=1,
        help_text="One or more documents. The configured batch and file-size limits apply.",
    )


class UploadRejectionSerializer(serializers.Serializer):
    filename = serializers.CharField()
    error_code = serializers.CharField()
    message = serializers.CharField()
    errors = serializers.JSONField()


class DatasetUploadResultSerializer(serializers.Serializer):
    accepted = serializers.ListField(
        child=serializers.DictField(),
        help_text="Serialized documents accepted into the dataset.",
    )
    rejected = UploadRejectionSerializer(many=True)


class LayoutBuildResultSerializer(serializers.Serializer):
    service = serializers.CharField()
    service_version = serializers.CharField()
    units = serializers.IntegerField(help_text="Number of pages or worksheets normalized.")
    warnings = serializers.ListField(child=serializers.CharField())


class WorkflowValidationRequestSerializer(serializers.Serializer):
    workflow_type = serializers.CharField(
        help_text="Workflow type returned by GET /workflows/types/."
    )
    config = serializers.JSONField(help_text="Candidate workflow configuration.")


class WorkflowValidationResultSerializer(serializers.Serializer):
    valid = serializers.BooleanField()
    config = serializers.JSONField(help_text="Validated and normalized configuration.")
    content_hash = serializers.CharField(help_text="Hash of the normalized configuration.")


class SegmentSplitRequestSerializer(serializers.Serializer):
    at_unit = serializers.IntegerField(
        min_value=1,
        help_text="First page or worksheet index in the new second segment.",
    )
    category = serializers.CharField(required=False, allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True)


SegmentMergeRequestSerializer = type(
    "SegmentMergeRequestSerializer",
    (serializers.Serializer,),
    {
        "with": serializers.UUIDField(
            help_text="ID of the adjacent segment to merge into this segment."
        ),
        "reason": serializers.CharField(required=False, allow_blank=True),
    },
)


class ReclassifyRequestSerializer(serializers.Serializer):
    category = serializers.CharField(help_text="Replacement category key.")
    reason = serializers.CharField(required=False, allow_blank=True)


class RunProgressSerializer(serializers.Serializer):
    total = serializers.IntegerField()
    succeeded = serializers.IntegerField()
    failed = serializers.IntegerField()
    skipped = serializers.IntegerField()
    queued = serializers.IntegerField()
    running = serializers.IntegerField()
    remaining = serializers.IntegerField()
    stage = serializers.CharField(allow_blank=True)
    estimated_seconds_remaining = serializers.IntegerField(allow_null=True)


class ReviewHistoryEntrySerializer(serializers.Serializer):
    id = serializers.UUIDField()
    action = serializers.CharField()
    actor = serializers.CharField(allow_null=True)
    at = serializers.DateTimeField()
    before = serializers.JSONField()
    after = serializers.JSONField()
    reason = serializers.CharField(allow_blank=True)


class BulkReviewSkipSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    reason = serializers.CharField()


class BulkReviewResultSerializer(serializers.Serializer):
    applied = serializers.ListField(child=serializers.UUIDField())
    skipped = BulkReviewSkipSerializer(many=True)
    undo_window_seconds = serializers.IntegerField()


class EvaluationCreateRequestSerializer(serializers.Serializer):
    run = serializers.UUIDField(help_text="Completed run to compare with ground truth.")
    normalization = serializers.JSONField(
        required=False,
        help_text="Optional field normalization overrides.",
    )
    numeric_tolerance = serializers.FloatField(
        required=False,
        default=0.01,
        help_text="Relative numeric tolerance; 0.01 means 1%.",
    )


_RESOURCE_NAMES = {
    "ProjectViewSet": ("project", "projects"),
    "DatasetViewSet": ("dataset", "datasets"),
    "DocumentViewSet": ("document", "documents"),
    "CategoryViewSet": ("category definition", "category definitions"),
    "SchemaVersionViewSet": ("schema version", "schema versions"),
    "PromptVersionViewSet": ("prompt version", "prompt versions"),
    "ModelConfigurationViewSet": ("model configuration", "model configurations"),
    "TemplateViewSet": ("extraction template", "extraction templates"),
    "WorkflowViewSet": ("workflow version", "workflow versions"),
    "RunViewSet": ("run", "runs"),
    "RunItemViewSet": ("run item", "run items"),
    "SegmentViewSet": ("segment", "segments"),
    "ClassificationViewSet": ("classification", "classifications"),
    "FieldViewSet": ("extracted field", "extracted fields"),
    "LabelViewSet": ("ground-truth label", "ground-truth labels"),
    "ReviewActionViewSet": ("review action", "review actions"),
    "EvaluationViewSet": ("evaluation", "evaluations"),
    "AuditEventViewSet": ("audit event", "audit events"),
}

_TAGS = {
    "SessionView": "Authentication",
    "LoginView": "Authentication",
    "LogoutView": "Authentication",
    "MeView": "Authentication",
    "ProjectViewSet": "Workspace",
    "DatasetViewSet": "Workspace",
    "DocumentViewSet": "Workspace",
    "CategoryViewSet": "Configuration",
    "SchemaVersionViewSet": "Configuration",
    "PromptVersionViewSet": "Configuration",
    "ModelConfigurationViewSet": "Configuration",
    "TemplateViewSet": "Configuration",
    "WorkflowViewSet": "Configuration",
    "RunViewSet": "Processing",
    "RunItemViewSet": "Processing",
    "SegmentViewSet": "Processing",
    "ClassificationViewSet": "Review & labeling",
    "FieldViewSet": "Review & labeling",
    "LabelViewSet": "Review & labeling",
    "ReviewActionViewSet": "Review & labeling",
    "EvaluationViewSet": "Evaluation & export",
    "DashboardView": "Operations & audit",
    "AuditEventViewSet": "Operations & audit",
}

_TAG_OVERRIDES = {
    ("RunViewSet", "export"): "Evaluation & export",
}

_SUMMARIES = {
    ("SessionView", "get"): "Check the current session",
    ("LoginView", "post"): "Sign in and start a session",
    ("LogoutView", "post"): "End the current session",
    ("MeView", "get"): "Retrieve the current user and runtime context",
    ("DashboardView", "get"): "Retrieve operational dashboard counts",
    ("DatasetViewSet", "upload"): "Upload documents to a dataset",
    ("DocumentViewSet", "original"): "Download the original document",
    ("DocumentViewSet", "layout"): "Build the normalized document layout",
    ("DocumentViewSet", "unit"): "Retrieve one normalized document unit",
    ("TemplateViewSet", "approve"): "Approve an extraction template",
    ("WorkflowViewSet", "validate"): "Validate a workflow configuration",
    ("WorkflowViewSet", "types"): "List workflow types and config schemas",
    ("WorkflowViewSet", "approve"): "Approve a workflow version",
    ("WorkflowViewSet", "retire"): "Retire a workflow version",
    ("RunViewSet", "execute"): "Execute a queued run",
    ("RunViewSet", "retry"): "Retry failed run items",
    ("RunViewSet", "cancel"): "Request run cancellation",
    ("RunViewSet", "progress"): "Retrieve live run progress",
    ("RunViewSet", "metrics"): "Retrieve run quality metrics",
    ("RunViewSet", "export"): "Export a run package",
    ("SegmentViewSet", "split"): "Split a segment at a document unit",
    ("SegmentViewSet", "merge"): "Merge two adjacent segments",
    ("ClassificationViewSet", "accept"): "Accept a classification",
    ("ClassificationViewSet", "reclassify"): "Correct a classification",
    ("FieldViewSet", "review"): "Review an extracted field",
    ("FieldViewSet", "history"): "Retrieve field review history",
    ("FieldViewSet", "bulk_review"): "Review multiple extracted fields",
}

_ACTION_DESCRIPTIONS = {
    ("DatasetViewSet", "upload"): (
        "Uploads one or more files as multipart form data. Each file is validated independently; "
        "the response lists both accepted documents and rejected files. A mixed batch is not rolled back."
    ),
    ("WorkflowViewSet", "validate"): (
        "Validates and normalizes a candidate configuration without creating a workflow version. "
        "Use the schemas from the workflow-types endpoint to build the config."
    ),
    ("TemplateViewSet", "approve"): (
        "Marks this immutable template version as approved and records the optional reason in the audit trail."
    ),
    ("WorkflowViewSet", "approve"): (
        "Marks this immutable workflow version as approved and records the optional reason in the audit trail."
    ),
    ("WorkflowViewSet", "retire"): (
        "Retires this workflow version without changing its historical runs or configuration snapshot."
    ),
    ("RunViewSet", "execute"): (
        "Starts processing a previously created run. The response may be immediate with the sync runner "
        "or asynchronous with the thread or Celery runner."
    ),
    ("RunViewSet", "retry"): "Reprocesses only failed items; completed items are not duplicated.",
    ("RunViewSet", "cancel"): (
        "Records a cancellation request. Work already in progress may finish before the run becomes cancelled."
    ),
    ("RunViewSet", "progress"): (
        "Returns aggregate item counts, the current stage, and an ETA when enough timing data exists."
    ),
    ("RunViewSet", "metrics"): (
        "Returns the quality indicators or ground-truth metrics stored on the run. The keys vary by workflow type."
    ),
    ("RunViewSet", "export"): (
        "Downloads the complete run package as JSON, extracted fields as CSV, or a multi-sheet XLSX workbook."
    ),
    ("FieldViewSet", "bulk_review"): (
        "Applies accept or reject to up to 500 fields. confirm_count must match the number of field IDs."
    ),
    ("SegmentViewSet", "split"): (
        "Splits inside a segment. The existing segment becomes the first part and a new adjacent segment is created."
    ),
    ("SegmentViewSet", "merge"): (
        "Merges this segment with the immediately following segment from the same document and run."
    ),
    ("ClassificationViewSet", "accept"): (
        "Accepts the predicted category while preserving the original prediction and recording a review action."
    ),
    ("ClassificationViewSet", "reclassify"): (
        "Stores the corrected category separately from the original prediction and records a review action."
    ),
    ("FieldViewSet", "review"): (
        "Accepts, corrects, rejects, marks absent, annotates, or promotes a field. Raw model output is preserved. "
        "Promotion returns a ground-truth label and requires both reviewer and approver roles."
    ),
    ("FieldViewSet", "history"): (
        "Returns the field's review actions in chronological order, including before/after snapshots and reasons."
    ),
    ("EvaluationViewSet", "create"): (
        "Computes extraction, classification, and segmentation metrics for a run using final ground-truth labels."
    ),
}

_ROLE_LABELS = {
    "docai_operators": "operator",
    "docai_reviewers": "reviewer",
    "docai_approvers": "approver",
}

_ROLE_OVERRIDES = {
    ("DocumentViewSet", "original"): "operator, reviewer, or approver",
    ("DocumentViewSet", "unit"): "operator, reviewer, or approver",
    ("RunViewSet", "export"): "operator, reviewer, or approver",
    ("FieldViewSet", "history"): "operator, reviewer, or approver",
    ("FieldViewSet", "review"): "reviewer; reviewer and approver when action is promote",
}


class DocAIAutoSchema(AutoSchema):
    """Describe DocAI conventions that are implicit in DRF runtime code."""

    def _view_name(self) -> str:
        return self.view.__class__.__name__

    def _action_name(self) -> str:
        return getattr(self.view, "action", self.method.lower())

    def get_tags(self) -> list[str]:
        view_action = (self._view_name(), self._action_name())
        return [_TAG_OVERRIDES.get(view_action, _TAGS.get(view_action[0], "Document AI API"))]

    def get_summary(self) -> str | None:
        explicit = super().get_summary()
        if explicit:
            return explicit

        view_name, action = self._view_name(), self._action_name()
        if summary := _SUMMARIES.get((view_name, action)):
            return summary

        resource = _RESOURCE_NAMES.get(view_name)
        if not resource:
            return None
        singular, plural = resource
        return {
            "list": f"List {plural}",
            "retrieve": f"Retrieve a {singular}",
            "create": f"Create a {singular}",
            "update": f"Replace a {singular}",
            "partial_update": f"Update a {singular}",
            "destroy": f"Delete a {singular}",
        }.get(action)

    def get_description(self) -> str:
        view_name, action = self._view_name(), self._action_name()
        if description := _ACTION_DESCRIPTIONS.get((view_name, action)):
            return description

        documented = super().get_description()
        if documented:
            return documented

        resource = _RESOURCE_NAMES.get(view_name)
        if not resource:
            return ""
        singular, plural = resource
        return {
            "list": f"Returns a paginated collection of {plural}.",
            "retrieve": f"Returns one {singular} by UUID.",
            "create": f"Creates a {singular} after validation and authorization.",
            "update": f"Replaces the editable fields of a {singular}.",
            "partial_update": f"Updates the supplied editable fields of a {singular}.",
            "destroy": f"Deletes the selected {singular}.",
        }.get(action, "")

    def get_extensions(self) -> dict[str, Any]:
        extensions = super().get_extensions()
        view_name, action = self._view_name(), self._action_name()
        permission_types = {type(permission) for permission in self.view.get_permissions()}

        if AllowAny in permission_types:
            role = "public"
        elif (view_name, action) in _ROLE_OVERRIDES:
            role = _ROLE_OVERRIDES[(view_name, action)]
        elif self.method in SAFE_METHODS:
            role = "viewer, operator, reviewer, or approver"
        else:
            configured = getattr(self.view, "write_role", "docai_operators")
            configured = getattr(self.view, "action_roles", {}).get(action, configured)
            role = _ROLE_LABELS.get(configured, configured)

        return {**extensions, "x-required-role": role}

    def _get_parameters(self):
        parameters = super()._get_parameters()
        parameters.append(
            {
                "name": "X-Request-ID",
                "in": "header",
                "required": False,
                "description": (
                    "Optional client-generated correlation ID. Use 1–32 alphanumeric characters."
                ),
                "schema": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 32,
                    "pattern": "^[A-Za-z0-9]+$",
                },
            }
        )
        return parameters

    def _get_response_for_code(
        self,
        serializer,
        status_code,
        media_types=None,
        direction="response",
    ):
        response = super()._get_response_for_code(
            serializer,
            status_code,
            media_types=media_types,
            direction=direction,
        )
        response.setdefault("headers", {})["X-Request-ID"] = {
            "description": "Correlation ID for this request and its server-side logs.",
            "schema": {"type": "string", "maxLength": 32},
        }

        if not response.get("description"):
            response["description"] = {
                "200": "Request completed successfully.",
                "201": "Resource created successfully.",
                "202": "Request accepted; processing may continue asynchronously.",
            }.get(str(status_code), "Response returned by the API.")

        code = int(status_code) if str(status_code).isdigit() else None
        action = self._action_name()
        is_success_payload = code is not None and (
            200 <= code < 300 or (action == "upload" and code == 422)
        )
        if is_success_payload and action not in {"original", "export"}:
            for media_type, media_object in response.get("content", {}).items():
                if media_type != "application/json":
                    continue
                data_schema = media_object.get("schema", {})
                media_object["schema"] = {
                    "type": "object",
                    "title": "Success envelope",
                    "required": ["success", "message", "data", "trace_id"],
                    "properties": {
                        "success": {"type": "boolean", "enum": [True]},
                        "message": {"type": "string"},
                        "data": data_schema,
                        "trace_id": {"type": "string", "maxLength": 32},
                    },
                }
        return response

    def _get_response_bodies(self, direction="response"):
        responses = super()._get_response_bodies(direction=direction)
        for response in responses.values():
            response.setdefault("headers", {})["X-Request-ID"] = {
                "description": "Correlation ID for this request and its server-side logs.",
                "schema": {"type": "string", "maxLength": 32},
            }
        responses.setdefault(
            "default",
            self._get_response_for_code(
                OpenApiResponse(
                    response=ErrorEnvelopeSerializer,
                    description=(
                        "Error response. Inspect error_code for program flow and retain trace_id "
                        "when reporting the failure."
                    ),
                ),
                "default",
                direction=direction,
            ),
        )
        return responses
