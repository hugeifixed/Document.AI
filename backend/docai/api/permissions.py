"""RBAC via Django groups (created by `manage.py seed_defaults`):
  docai_viewers    read-only, sensitive values masked
  docai_operators  upload, configure, run
  docai_reviewers  label, review, see document content
  docai_approvers  approve configurations/templates, promote ground truth
Superusers hold every role. Object-level: project scoping hook in `can_access_project`."""
from rest_framework.permissions import SAFE_METHODS, BasePermission

VIEWER, OPERATOR, REVIEWER, APPROVER = "docai_viewers", "docai_operators", "docai_reviewers", "docai_approvers"


def roles(user) -> set[str]:
    if not user or not user.is_authenticated:
        return set()
    if user.is_superuser:
        return {VIEWER, OPERATOR, REVIEWER, APPROVER}
    cached = getattr(user, "_docai_roles", None)
    if cached is None:
        cached = set(user.groups.filter(name__startswith="docai_").values_list("name", flat=True))
        user._docai_roles = cached
    return cached


def can_view_content(user) -> bool:
    return bool(roles(user) & {OPERATOR, REVIEWER, APPROVER})


def can_access_project(user, project) -> bool:
    """Extension point for per-project membership; currently role-based."""
    return bool(roles(user))


class DocAIPermission(BasePermission):
    """Read for any role; writes need the role named on the view (`write_role`)."""
    def has_permission(self, request, view):
        r = roles(request.user)
        if not r:
            return False
        if request.method in SAFE_METHODS:
            return True
        needed = getattr(view, "write_role", OPERATOR)
        if hasattr(view, "action_roles"):
            needed = view.action_roles.get(getattr(view, "action", None), needed)
        return needed in r

    def has_object_permission(self, request, view, obj):
        project = getattr(obj, "project", None) or getattr(getattr(obj, "dataset", None), "project", None) \
            or getattr(getattr(obj, "run", None), "project", None)
        return can_access_project(request.user, project) if project else True
