"""Interruption, incompatible input and stale ownership are recovery boundaries."""

from dataclasses import replace
from unittest.mock import Mock

import pytest
from django.core.files.storage import default_storage

from docai.adapters.llm.base import LLMCall
from docai.models import ITEM_STATUS, ProcessingCheckpoint, Run, RunItem
from docai.schemas.llm import ExtractionOut, StructuredResult
from docai.services import ingestion, runs
from docai.services.checkpoints import Checkpoints, ClaimLost


@pytest.fixture
def claimed_item(dataset, sample_workflow, admin, tmp_path, settings):
    settings.MEDIA_ROOT = tmp_path
    ingestion.ingest_upload(dataset, "source.txt", b"Wages 100", user=admin)
    run = runs.create_run(dataset.project, sample_workflow, dataset, admin)
    item = run.items.get()
    item.status, item.attempts, item.worker_task_id = ITEM_STATUS.running, 1, "delivery-a"
    item.save()
    return item


def call():
    return LLMCall(
        system="Extract",
        user="Wages 100",
        schema=ExtractionOut,
        stage="extraction",
        segment_index=0,
        chunk_index=0,
        prompt_version=1,
    )


def response():
    return StructuredResult(
        parsed=ExtractionOut(fields=[]), raw_response='{"fields":[]}', model_deployment="test"
    )


@pytest.mark.django_db
def test_recovered_output_skips_provider_and_usage(claimed_item):
    provider = Mock(return_value=response())
    Checkpoints(claimed_item).invoke(call(), provider)
    # A new claim/worker can reuse completed output within the same run item.
    claimed_item.attempts += 1
    claimed_item.worker_task_id = "delivery-b"
    claimed_item.save()
    result = Checkpoints(claimed_item).invoke(call(), provider)
    assert isinstance(result.parsed, ExtractionOut)
    assert provider.call_count == 1
    assert ProcessingCheckpoint.objects.count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "change", ["user", "system", "prompt_version", "segment_index", "parameters"]
)
def test_changed_call_cannot_reuse_checkpoint(claimed_item, change):
    provider = Mock(return_value=response())
    original = call()
    Checkpoints(claimed_item).invoke(original, provider)
    value = {
        "user": "Wages 200",
        "system": "New instructions",
        "prompt_version": 2,
        "segment_index": 1,
        "parameters": {"max_tokens": 9000},
    }[change]
    Checkpoints(claimed_item).invoke(replace(original, **{change: value}), provider)
    assert provider.call_count == 2


@pytest.mark.django_db
@pytest.mark.parametrize("state", ["cancelled", "superseded", "terminal"])
def test_late_response_cannot_publish(claimed_item, state):
    def provider(_):
        if state == "cancelled":
            Run.objects.filter(pk=claimed_item.run_id).update(cancel_requested=True)
        elif state == "superseded":
            RunItem.objects.filter(pk=claimed_item.pk).update(attempts=2)
        else:
            RunItem.objects.filter(pk=claimed_item.pk).update(status=ITEM_STATUS.succeeded)
        return response()

    with pytest.raises(ClaimLost):
        Checkpoints(claimed_item).invoke(call(), provider)
    assert not ProcessingCheckpoint.objects.exists()


@pytest.mark.django_db
def test_invalid_result_not_checkpointed(claimed_item):
    result = response()
    result.parsed = {"fields": "invalid"}
    with pytest.raises(ValueError):
        Checkpoints(claimed_item).invoke(call(), lambda _: result)
    assert not ProcessingCheckpoint.objects.exists()


@pytest.mark.django_db
def test_corrupt_artifact_not_replayed(claimed_item):
    provider = Mock(return_value=response())
    Checkpoints(claimed_item).invoke(call(), provider)
    artifact = ProcessingCheckpoint.objects.get().artifact
    assert artifact is not None
    with default_storage.open(artifact.storage_path, "wb") as target:
        target.write(b"corrupt")
    with pytest.raises(ValueError, match="integrity"):
        Checkpoints(claimed_item).invoke(call(), provider)
    assert provider.call_count == 1


@pytest.mark.django_db
def test_operation_publication_uses_claim_and_scalar_fingerprint(claimed_item):
    store = Checkpoints(claimed_item)
    store.save_operation("a" * 64, {"result_id": "id", "resubmissions": 0})
    saved = store.read_operation("a" * 64)
    assert saved is not None and saved["result_id"] == "id"
    assert store.read_operation("b" * 64) is None
    RunItem.objects.filter(pk=claimed_item.pk).update(attempts=2)
    with pytest.raises(ClaimLost):
        store.save_operation("a" * 64, {"result_id": "wrong"})
    assert ProcessingCheckpoint.objects.get().metadata["result_id"] == "id"


@pytest.mark.django_db
def test_domain_rejection_revokes_replay(claimed_item):
    provider = Mock(return_value=response())
    store = Checkpoints(claimed_item)
    store.invoke(call(), provider)
    store.discard(call())
    assert not ProcessingCheckpoint.objects.exists()
    store.invoke(call(), provider)
    assert provider.call_count == 2


@pytest.mark.django_db
@pytest.mark.parametrize("cancelled", [False, True])
def test_final_results_cannot_replace_cancelled_or_newer_attempt(
    claimed_item, monkeypatch, cancelled
):
    from docai.services import run_execution
    from docai.workflows.base import DocumentResult

    def process(*args):
        if cancelled:
            Run.objects.filter(pk=claimed_item.run_id).update(cancel_requested=True)
        else:
            RunItem.objects.filter(pk=claimed_item.pk).update(attempts=99, stage="newer_attempt")
        return DocumentResult()

    monkeypatch.setattr(run_execution, "get_strategy", lambda _: Mock(process_document=process))
    persist = Mock()
    monkeypatch.setattr(runs, "persist_result", persist)
    run_execution.process_item(claimed_item.pk)
    claimed_item.refresh_from_db()
    persist.assert_not_called()
    if cancelled:
        assert claimed_item.status == ITEM_STATUS.skipped
    else:
        assert claimed_item.status == ITEM_STATUS.running
        assert claimed_item.stage == "newer_attempt"
        assert claimed_item.attempts == 99


@pytest.mark.django_db
def test_checkpoint_replay_does_not_fabricate_usage_events(claimed_item):
    from docai.adapters.llm.base import LLMUsage
    from docai.models import LLMUsageEvent
    from docai.services.llm_usage import observer_for

    observe = observer_for(claimed_item)

    def provider(request):
        observe(
            request, LLMUsage(provider="azure_openai", model_deployment="test", total_tokens=15)
        )
        return response()

    store = Checkpoints(claimed_item)
    store.invoke(call(), provider)
    store.invoke(call(), provider)
    assert LLMUsageEvent.objects.count() == 1
    # A deliberately different request is a real second call, hence a new event.
    store.invoke(replace(call(), user="New input"), provider)
    assert LLMUsageEvent.objects.count() == 2
