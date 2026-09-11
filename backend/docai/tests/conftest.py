import pytest
from django.contrib.auth.models import Group, User
from rest_framework.test import APIClient

from docai.models import Dataset, Project
from docai.services import governance


@pytest.fixture
def groups(db):
    return {
        n: Group.objects.get_or_create(name=n)[0]
        for n in ("docai_viewers", "docai_operators", "docai_reviewers", "docai_approvers")
    }


def _user(name, groups, *roles, superuser=False):
    u = User.objects.create_user(name, password="pw", is_superuser=superuser, is_staff=superuser)
    for r in roles:
        u.groups.add(groups[r])
    return u


@pytest.fixture
def admin(groups):
    return _user("admin", groups, superuser=True)


@pytest.fixture
def operator(groups):
    return _user("op", groups, "docai_operators")


@pytest.fixture
def reviewer(groups):
    return _user("rev", groups, "docai_reviewers")


@pytest.fixture
def viewer(groups):
    return _user("viewer", groups, "docai_viewers")


@pytest.fixture
def api(admin):
    c = APIClient()
    c.force_authenticate(admin)
    return c


@pytest.fixture
def project(db, admin):
    governance.ensure_default_prompts(admin)
    return Project.available_objects.create(
        name="Test project", slug="test-project", created_by=admin
    )


@pytest.fixture
def dataset(project, admin):
    return Dataset.available_objects.create(
        project=project, name="dev", split="dev", created_by=admin
    )


@pytest.fixture
def w2_pdf():
    from docai.synthetic.generators import make_docs

    return next(d for d in make_docs(3) if d.category == "w2")


@pytest.fixture
def package_pdf():
    from docai.synthetic.generators import make_docs

    return next(d for d in make_docs(3) if d.category == "package")


@pytest.fixture
def sample_workflow(project, admin):
    from docai.management.commands.seed_defaults import sample_workflow_configs

    wt, cfg = sample_workflow_configs()["unbundle-classify-extract"]
    return governance.create_workflow_version(project, "ucx", wt, cfg, admin)
