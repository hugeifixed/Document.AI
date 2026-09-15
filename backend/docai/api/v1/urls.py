from django.urls import path
from rest_framework.routers import DefaultRouter

from docai.api.auth import LoginView, LogoutView, SessionView
from docai.api.invocation import RunJSONResultsView, WorkflowInvokeView

from . import views

router = DefaultRouter()
router.register("projects", views.ProjectViewSet, basename="project")
router.register("datasets", views.DatasetViewSet, basename="dataset")
router.register("documents", views.DocumentViewSet, basename="document")
router.register("categories", views.CategoryViewSet, basename="category")
router.register("schemas", views.SchemaVersionViewSet, basename="schema")
router.register("prompts", views.PromptVersionViewSet, basename="prompt")
router.register(
    "model-configurations", views.ModelConfigurationViewSet, basename="model-configuration"
)
router.register("templates", views.TemplateViewSet, basename="template")
router.register("workflows", views.WorkflowViewSet, basename="workflow")
router.register("runs", views.RunViewSet, basename="run")
router.register("run-items", views.RunItemViewSet, basename="run-item")
router.register("segments", views.SegmentViewSet, basename="segment")
router.register("classifications", views.ClassificationViewSet, basename="classification")
router.register("fields", views.FieldViewSet, basename="field")
router.register("labels", views.LabelViewSet, basename="label")
router.register("review-actions", views.ReviewActionViewSet, basename="review-action")
router.register("evaluations", views.EvaluationViewSet, basename="evaluation")
router.register("audit-events", views.AuditEventViewSet, basename="audit-event")

urlpatterns = router.urls + [
    path(
        "workflows/<uuid:workflow_id>/invoke/", WorkflowInvokeView.as_view(), name="workflow-invoke"
    ),
    path("runs/<uuid:run_id>/results/", RunJSONResultsView.as_view(), name="run-json-results"),
    path("auth/session/", SessionView.as_view(), name="auth-session"),
    path("auth/login/", LoginView.as_view(), name="auth-login"),
    path("auth/logout/", LogoutView.as_view(), name="auth-logout"),
    path("dashboard/", views.DashboardView.as_view(), name="dashboard"),
    path("me/", views.MeView.as_view(), name="me"),
]
