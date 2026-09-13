"""Public normalization boundary tests run without any optional native packages."""

import builtins
from pathlib import Path
from types import SimpleNamespace

import pytest

from docai import input_quality
from docai.exceptions import NormalizationUnavailable
from docai.schemas.config import DIAnalysisConfig, InputQualityConfig, validate_workflow_config


def test_defaults_are_snapshotted_and_di_addon_is_independent():
    config = validate_workflow_config(
        "classify_unstructured",
        {"categories": [{"key": "w2", "name": "W2"}], "di_analysis": {"ocr_high_resolution": True}},
    )
    assert config["input_quality"] == {
        "mode": "off",
        "skip_blank_pages": False,
        "profile": "adaptive-v1",
    }
    assert config["di_analysis"] == {"ocr_high_resolution": True}
    assert DIAnalysisConfig().ocr_high_resolution is False


def test_off_mode_never_loads_native_libraries(monkeypatch):
    original_import = builtins.__import__

    def without_native(name, *args, **kwargs):
        if name.split(".")[0] in {"PIL", "cv2", "pypdfium2", "numpy"} or name.endswith("native"):
            raise ImportError("Optional dependencies intentionally unavailable")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_native)
    config = InputQualityConfig()
    input_quality.validate_input_quality(config, "pypdf")
    with input_quality.prepare_input(
        Path("original.pdf"), source_format="pdf", config=config
    ) as prepared:
        assert prepared.path == Path("original.pdf")
        assert prepared.summary["status"] == "off"
        assert prepared.selected_pages is None


def test_capability_validation_reports_disabled_missing_dependencies_and_adapter(
    settings, monkeypatch
):
    settings.DOCAI_IMAGE_NORMALIZATION_ENABLED = False
    config = InputQualityConfig(mode="adaptive")
    assert input_quality.capabilities()["image_normalization"]["available"] is False
    with pytest.raises(NormalizationUnavailable, match="disabled"):
        input_quality.validate_input_quality(config, "azure_di")
    settings.DOCAI_IMAGE_NORMALIZATION_ENABLED = True
    monkeypatch.setattr(input_quality.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(NormalizationUnavailable, match="not installed"):
        input_quality.validate_input_quality(config, "azure_di")
    monkeypatch.setattr(input_quality.importlib.util, "find_spec", lambda name: object())
    with pytest.raises(NormalizationUnavailable, match="Azure"):
        input_quality.validate_input_quality(config, "pypdf")
    assert input_quality.capabilities()["image_normalization"]["available"] is False
    settings.DOCAI = {**settings.DOCAI, "LAYOUT_ADAPTER": "azure_di"}
    assert input_quality.capabilities()["image_normalization"]["available"] is True
    input_quality.validate_input_quality(config, "azure_di")


@pytest.mark.parametrize("source_format", ["docx", "xlsx", "xls", "txt"])
def test_nonimage_inputs_bypass_native_module(source_format, monkeypatch):
    monkeypatch.setattr(input_quality, "_availability", lambda: (True, "available"))
    with input_quality.prepare_input(
        Path("original"), source_format=source_format, config=InputQualityConfig(mode="adaptive")
    ) as prepared:
        assert prepared.summary["status"] == "bypassed"
        assert prepared.page_details == []


def test_worker_rechecks_gate_before_preparation(settings):
    settings.DOCAI_IMAGE_NORMALIZATION_ENABLED = False
    with (
        pytest.raises(NormalizationUnavailable),
        input_quality.prepare_input(
            Path("original.pdf"), source_format="pdf", config=InputQualityConfig(mode="adaptive")
        ),
    ):
        pytest.fail("Disabled adaptive processing must not start")


@pytest.mark.parametrize(
    ("source_format", "pages", "high_resolution", "features"),
    [
        ("pdf", "1-3,5", True, ["keyValuePairs", "ocrHighResolution"]),
        ("jpeg", None, True, ["keyValuePairs", "ocrHighResolution"]),
        ("pdf", None, False, ["keyValuePairs"]),
        ("docx", None, True, None),
    ],
)
def test_di_options_are_forwarded_independently_of_local_enhancement(
    tmp_path, monkeypatch, source_format, pages, high_resolution, features
):
    from docai.adapters.layout import azure_di

    adapter = object.__new__(azure_di.AzureDocumentIntelligenceLayout)
    adapter.timeout = 1
    adapter.api_version = "2024-11-30"
    path = tmp_path / "input"
    path.write_bytes(b"accepted upload")
    calls = []
    result = SimpleNamespace(content="", pages=[], paragraphs=[], tables=[], sections=[])

    class Client:
        def begin_analyze_document(self, model, body, **kwargs):
            calls.append((model, body.bytes_source, kwargs))
            return SimpleNamespace(result=lambda **kwargs: result)

    monkeypatch.setattr(adapter, "_client", Client)
    monkeypatch.setattr(azure_di, "with_retries", lambda call: call())
    adapter.analyze(
        path,
        document_id="document-1",
        source_format=source_format,
        pages=pages,
        ocr_high_resolution=high_resolution,
    )
    expected = {"features": features}
    if pages:
        expected["pages"] = pages
    assert calls == [("prebuilt-layout", b"accepted upload", expected)]
