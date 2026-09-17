"""The external operation survives retries; persisted data never selects a URL."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from azure.core.exceptions import ServiceResponseError

from docai.adapters.layout.azure_di import AzureDocumentIntelligenceLayout
from docai.exceptions import IntegrationError

ENDPOINT = "https://di.example.test"
API = "2024-11-30"


class Store:
    def __init__(self):
        self.saved = {}

    def check(self):
        pass

    def read_operation(self, key):
        return self.saved.get(key)

    def save_operation(self, key, state):
        self.saved[key] = state.copy()


class Client:
    def __init__(self, statuses):
        self.statuses = iter(statuses)
        self.posts = 0
        self.urls = []
        self.ids = []
        self.closed_responses = 0
        self.location = None

    def begin_analyze_document(self, model, source, **options):
        assert model == "prebuilt-layout"
        assert source.read() == b"document bytes"
        assert options["retry_total"] == 0
        assert options["polling"] is False
        self.posts += 1
        operation_id = str(uuid4())
        self.ids.append(operation_id)
        location = (
            self.location
            or f"{ENDPOINT}/documentintelligence/documentModels/prebuilt-layout/analyzeResults/{operation_id}?api-version={API}"
        )
        options["raw_response_hook"](
            SimpleNamespace(
                http_response=SimpleNamespace(
                    status_code=202, headers={"Operation-Location": location}
                )
            )
        )

    def send_request(self, request):
        self.urls.append(request.url)
        value = next(self.statuses)
        if isinstance(value, Exception):
            raise value
        status, body = (value, {}) if isinstance(value, int) else (200, value)
        return SimpleNamespace(
            status_code=status,
            json=lambda: body,
            headers={"Retry-After": "0"},
            close=self._close_response,
        )

    def _close_response(self):
        self.closed_responses += 1

    def close(self):
        pass


def success():
    return {
        "status": "succeeded",
        "analyzeResult": {
            "content": "hello",
            "pages": [],
            "modelId": "prebuilt-layout",
            "apiVersion": API,
            "stringIndexType": "unicodeCodePoint",
        },
    }


@pytest.fixture
def setup_di(tmp_path, settings, monkeypatch):
    settings.DOCAI = {
        **settings.DOCAI,
        "AZURE_DI_ENDPOINT": ENDPOINT,
        "AZURE_DI_API_VERSION": API,
        "AZURE_MAX_RETRIES": 0,
    }
    path = tmp_path / "source.pdf"
    path.write_bytes(b"document bytes")
    store = Store()

    def create(client):
        adapter = AzureDocumentIntelligenceLayout()
        adapter.bind_recovery(store)
        monkeypatch.setattr(adapter, "_client", lambda: client)
        return adapter

    return path, store, create


def analyze(adapter, path):
    return adapter._analyze_result(path, features=["keyValuePairs"], pages=None)


def test_restart_resumes_operation_after_polling_network_failure(setup_di):
    path, store, create = setup_di
    client = Client([ServiceResponseError("connection interrupted"), success()])
    with pytest.raises(IntegrationError):
        analyze(create(client), path)
    saved_id = next(iter(store.saved.values()))["result_id"]
    assert analyze(create(client), path).content == "hello"
    assert client.posts == 1
    assert all(saved_id in url for url in client.urls)
    assert client.closed_responses == 1


def test_expiration_consumes_one_durable_resubmission_budget(setup_di):
    path, store, create = setup_di
    client = Client([404, 410])
    with pytest.raises(IntegrationError) as exc:
        analyze(create(client), path)
    assert exc.value.error_code == "OCR_OPERATION_EXPIRED"
    assert client.posts == 2
    state = next(iter(store.saved.values()))
    assert state["resubmissions"] == 1
    assert state["previous_result_id"] == client.ids[0]
    # A further worker restart must not reset the external retry budget.
    client.statuses = iter([404])
    with pytest.raises(IntegrationError):
        analyze(create(client), path)
    assert client.posts == 2


@pytest.mark.parametrize(
    "location",
    [
        "https://attacker.test/documentintelligence/documentModels/prebuilt-layout/analyzeResults/id?api-version=2024-11-30",
        f"{ENDPOINT}/wrong/path?api-version={API}",
        f"{ENDPOINT}/documentintelligence/documentModels/prebuilt-layout/analyzeResults/../../secret?api-version={API}",
    ],
)
def test_foreign_or_invalid_operation_location_never_fetched(setup_di, location):
    path, store, create = setup_di
    client = Client([])
    client.location = location
    with pytest.raises(IntegrationError) as exc:
        analyze(create(client), path)
    assert exc.value.error_code == "OCR_OPERATION_INVALID"
    assert not store.saved
    assert not client.urls


def test_changed_effective_policy_cannot_resume_old_operation(setup_di):
    path, store, create = setup_di
    client = Client([success(), success()])
    analyze(create(client), path)
    create(client)._analyze_result(
        path, features=["keyValuePairs", "ocrHighResolution"], pages=None
    )
    assert client.posts == 2
    assert len(store.saved) == 2


def test_saved_id_validated_without_fetching_supplied_url(setup_di):
    path, store, create = setup_di
    client = Client([success()])
    analyze(create(client), path)
    next(iter(store.saved.values()))["result_id"] = "https://attacker.test/"
    with pytest.raises(IntegrationError) as exc:
        analyze(create(client), path)
    assert exc.value.error_code == "OCR_OPERATION_INVALID"
    assert len(client.urls) == 1


def test_polling_in_progress_honors_deadline_and_preserves_reference(setup_di, monkeypatch):
    path, store, create = setup_di
    client = Client([{"status": "running"}])
    monkeypatch.setattr("docai.adapters.layout.azure_di.time.monotonic", iter([0, 1000]).__next__)
    adapter = create(client)
    adapter.timeout = 1
    with pytest.raises(IntegrationError) as exc:
        analyze(adapter, path)
    assert exc.value.error_code == "OCR_POLL_TIMEOUT"
    assert exc.value.retryable
    assert len(store.saved) == 1


@pytest.mark.parametrize(
    "status,code", [("failed", "OCR_ANALYSIS_FAILED"), ("invalid", "OCR_OPERATION_INVALID")]
)
def test_terminal_provider_outcome_not_resubmitted(setup_di, status, code):
    path, _, create = setup_di
    client = Client([{"status": status}])
    with pytest.raises(IntegrationError) as exc:
        analyze(create(client), path)
    assert exc.value.error_code == code
    assert not exc.value.retryable
    assert client.posts == 1
