import pytest

from docai.models import (
    DOC_STATUS,
    LABEL_KIND,
    LABEL_STATUS,
    REVIEW_STATUS,
    RUN_STATUS,
    Document,
    Evaluation,
    ExtractedField,
    GroundTruthLabel,
)
from docai.serializers.core import RunDetailSerializer
from docai.services.dashboard import dashboard
from docai.services.runs import create_run


def _document(dataset, admin, suffix="one"):
    return Document.objects.create(
        dataset=dataset,
        original_filename=f"statement-{suffix}.txt",
        mime_type="text/plain",
        file_format="txt",
        sha256=(suffix * 64)[:64],
        size_bytes=10,
        page_count=1,
        storage_path=f"documents/{suffix}.txt",
        status=DOC_STATUS.validated,
        created_by=admin,
    )


@pytest.mark.django_db
def test_dataset_and_run_guidance_exposes_lifecycle_facts(project, dataset, sample_workflow, admin):
    document = _document(dataset, admin)
    run = create_run(project, sample_workflow, dataset, admin)
    run.status = RUN_STATUS.succeeded
    run.processed_items = 1
    run.save(update_fields=["status", "processed_items", "modified"])
    ExtractedField.objects.create(
        run=run,
        document=document,
        name="account_holder",
        review_status=REVIEW_STATUS.needs_review,
        created_by=admin,
    )
    GroundTruthLabel.objects.create(
        document=document,
        labeler=admin,
        kind=LABEL_KIND.field,
        field_name="account_holder",
        expected_value="Daniel Silva",
        version=1,
        status=LABEL_STATUS.final,
        created_by=admin,
    )
    evaluation = Evaluation.objects.create(
        project=project,
        run=run,
        dataset=dataset,
        has_ground_truth=True,
        created_by=admin,
    )

    scoped = dashboard(project.id, dataset.id)["guidance"]

    assert scoped["documents"] == {
        "total": 1,
        "runnable": 1,
        "blocked": 0,
        "new_for_run": 0,
    }
    assert scoped["workflows"]["runnable"] == 1
    assert scoped["latest_run"]["id"] == str(run.id)
    assert scoped["latest_run"]["guidance"]["review"]["fields"] == 1
    assert scoped["latest_run"]["guidance"]["ground_truth"] == {
        "labels": 1,
        "documents": 1,
    }
    assert scoped["latest_run"]["guidance"]["evaluations"] == {
        "count": 1,
        "latest_id": str(evaluation.id),
        "has_ground_truth": True,
    }
    assert RunDetailSerializer(run).data["guidance"]["export_ready"] is True

    _document(dataset, admin, "two")
    assert dashboard(project.id, dataset.id)["guidance"]["documents"]["new_for_run"] == 1
