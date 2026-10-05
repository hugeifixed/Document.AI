"""The local harness wraps production extraction; it does not publish run results."""

import io
import json
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from docai.exceptions import IntegrationError
from docai.schemas.layout import LayoutDocument, LayoutPage, Paragraph, Span, Word
from docai.services import extraction_preview, extraction_visualization, governance
from docai.workflows.base import DocumentResult, FieldResultData

if TYPE_CHECKING:
    from PIL.Image import Image


def rgb_pixel(image: "Image", position: tuple[int, int]) -> tuple[int, ...]:
    pixel = image.getpixel(position)
    assert isinstance(pixel, tuple)
    return pixel


@pytest.fixture
def extraction_workflow(project, admin):
    return governance.create_workflow_version(
        project,
        "preview",
        "extract_structured",
        {
            "mode": "custom",
            "schema": {
                "name": "w2",
                "fields": [
                    {"name": "employee_name"},
                    {"name": "wages", "type": "currency"},
                ],
            },
            "model": {"adapter": "azure_openai", "deployment": "fixture"},
        },
        admin,
    )


def invoke(workflow, source, output, *extra):
    stdout, stderr = io.StringIO(), io.StringIO()
    call_command(
        "test_extraction",
        "--workflow-id",
        str(workflow.id),
        "--input",
        str(source),
        "--output",
        str(output),
        *extra,
        stdout=stdout,
        stderr=stderr,
    )
    return stdout.getvalue(), stderr.getvalue()


def hit(index=0):
    return {
        "unit_index": index,
        "polygon": [0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2],
        "method": "exact",
        "word_ids": [f"p{index + 1}:w0"],
    }


def field(name, value, **extra):
    return FieldResultData(
        **{
            "name": name,
            "raw_value": value,
            "field_type": "string",
            "normalized_value": value,
            "score": 0.8,
            "source_text": "",
            "method": "llm",
            "strategy": "whole_document",
            "fallback_used": "",
            "model_deployment": "fixture",
            "prompt": None,
            "schema": None,
            "api_version": "",
            "validation_status": "not_run",
            "validation_messages": [],
            "suggested_correction": None,
            "grounding": None,
            "review_outcome": "human_review",
            **extra,
        }
    )


def test_labels_keep_false_zero_pages_and_unknown_locations_without_guessing():
    layout = LayoutDocument(
        document_id="fixture",
        source_format="pdf",
        service="fixture",
        units=[
            LayoutPage(index=0, number=1),
            LayoutPage(index=2, number=3),
        ],
    )
    result = DocumentResult(
        fields=[
            field("same", "100", grounding=hit(2)),
            field("unknown", "100"),
            field("invalid_geometry", "100", grounding={**hit(), "polygon": [float("nan")] * 8}),
            field("absent", None),
            field(
                "items",
                '[{"flag":false,"zero":0,"missing":null}]',
                field_type="list",
                property_evidence=[
                    {
                        "path": "/0/flag",
                        "value": False,
                        "sources": [],
                        "status": "grounded",
                        "grounding": hit(2),
                    },
                    {
                        "path": "/0/zero",
                        "value": 0,
                        "sources": [{"unit_index": 0}],
                        "status": "value_not_found",
                        "grounding": None,
                    },
                    {
                        "path": "/0/invented",
                        "value": None,
                        "sources": [],
                        "status": "invalid_path",
                        "grounding": None,
                    },
                ],
            ),
        ]
    )
    labels = extraction_visualization.collect_labels(result, layout)
    assert [(label["color"], label["unit_index"]) for label in labels] == [
        ("blue", 2),
        ("orange", None),
        ("orange", None),
        ("green", 2),
        ("orange", 0),
    ]
    assert labels[3]["value"] is False and labels[4]["value"] == 0


@pytest.mark.django_db
def test_workflow_resolution_preserves_overrides_and_does_not_write(extraction_workflow):
    prompt = governance.new_prompt_version(
        "preview-custom", "extraction", "Private system", "{content}"
    )
    extraction_workflow.config["prompt_overrides"] = {"extraction": prompt.name}
    with CaptureQueriesContext(connection) as queries:
        ctx = extraction_preview.workflow_context(extraction_workflow, live=False)
    assert ctx.layout_adapter_key == "pypdf" and ctx.llm.key == "mock"
    assert ctx.prompts["extraction"].name == prompt.name
    assert ctx.config.model.deployment == "fixture"  # Saved settings remain unchanged.
    assert not any(
        q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries
    )


@pytest.mark.django_db
@pytest.mark.parametrize("saved", [False, True])
@pytest.mark.parametrize("flag", [None, "--citation-repair", "--no-citation-repair"])
def test_command_citation_repair_override_is_local_and_manifest_records_effective_setting(
    extraction_workflow, admin, saved, flag, tmp_path, monkeypatch
):
    from docai.management.commands import test_extraction

    workflow = governance.create_workflow_version(
        extraction_workflow.project,
        "repair-preview",
        extraction_workflow.workflow_type,
        {**extraction_workflow.config, "citation_repair": saved},
        admin,
    )
    source, output = tmp_path / "sample.pdf", tmp_path / "outputs"
    source.touch()
    expected = saved if flag is None else flag == "--citation-repair"

    def preview(path, destination, context):
        assert context.config.citation_repair is expected
        return {"status": "succeeded", "labels": 0, "boxed": 0, "unboxed": 0, "images": []}

    monkeypatch.setattr(test_extraction, "check_renderer", lambda: None)
    monkeypatch.setattr(test_extraction, "preview_file", preview)
    with CaptureQueriesContext(connection) as queries:
        invoke(workflow, source, output, *([flag] if flag else []))
    assert not any(
        q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries
    )
    assert json.loads((output / "manifest.json").read_text())["citation_repair"] is expected
    workflow.refresh_from_db()
    assert workflow.config["citation_repair"] is saved


@pytest.mark.django_db
@pytest.mark.parametrize("extension", [".pdf", ".PDF"])
def test_offline_command_runs_real_pipeline_and_exports_jpg_without_database_writes(
    extraction_workflow,
    w2_pdf,
    tmp_path,
    extension,
):
    pytest.importorskip("PIL")
    pytest.importorskip("pypdfium2")
    from PIL import Image

    source, output = tmp_path / ("sample" + extension), tmp_path / "outputs"
    source.write_bytes(w2_pdf.data)
    with CaptureQueriesContext(connection) as queries:
        stdout, _stderr = invoke(extraction_workflow, source, output)
    assert not any(
        q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["workflow"]["id"] == str(extraction_workflow.id)
    assert manifest["citation_repair"] is False
    document = manifest["documents"][0]
    assert document["status"] == "succeeded" and document["labels"] == 2
    destination = output / document["output"]
    result = json.loads((destination / "result.json").read_text())
    assert result["summary"]["llm_adapter"] == "mock"
    assert result["config"]["citation_repair"] is False
    assert len(result["result"]["fields"]) == 2 and "wages" not in stdout
    assert (destination / "labels.csv").exists() and (destination / "layout.json").exists()
    with Image.open(destination / document["images"][0]) as image:
        assert image.format == "JPEG" and image.size == (2600, 2400)


@pytest.mark.django_db
def test_folder_limit_order_recursion_and_output_exclusion(
    extraction_workflow, tmp_path, monkeypatch
):
    from docai.management.commands import test_extraction

    source = tmp_path / "inputs"
    source.mkdir()
    output = source / "outputs"
    (source / "a").mkdir()
    (source / "a" / "same.pdf").touch()
    (source / "b").mkdir()
    (source / "b" / "same.PDF").touch()
    (source / "z.pdf").touch()
    (source / "readme.txt").touch()
    output.mkdir()
    (output / "old.pdf").touch()
    calls = []

    def preview(path, destination, context):
        calls.append((path, destination))
        return {"status": "succeeded", "labels": 0, "boxed": 0, "unboxed": 0, "images": []}

    monkeypatch.setattr(test_extraction, "check_renderer", lambda: None)
    monkeypatch.setattr(test_extraction, "preview_file", preview)
    invoke(extraction_workflow, source, output, "--recursive", "--limit", "2")
    manifest = json.loads((output / "manifest.json").read_text())
    assert [str(path.relative_to(source)) for path, _dest in calls] == ["a/same.pdf", "b/same.PDF"]
    assert calls[0][1] != calls[1][1] and manifest["omitted"] == 1


@pytest.mark.django_db
@pytest.mark.parametrize("recursive", [False, True])
def test_output_ancestor_does_not_exclude_input_pdfs(
    extraction_workflow, tmp_path, monkeypatch, recursive
):
    from docai.management.commands import test_extraction

    source = tmp_path / "inputs"
    source.mkdir()
    pdf = source / "sample.pdf"
    pdf.touch()
    calls = []

    def preview(path, destination, context):
        calls.append((path, destination))
        return {"status": "succeeded", "labels": 0, "boxed": 0, "unboxed": 0, "images": []}

    monkeypatch.setattr(test_extraction, "check_renderer", lambda: None)
    monkeypatch.setattr(test_extraction, "preview_file", preview)
    invoke(extraction_workflow, source, tmp_path, *(["--recursive"] if recursive else []))
    assert calls == [(pdf, tmp_path / "sample.pdf.extraction")]
    assert json.loads((tmp_path / "manifest.json").read_text())["selected"] == 1


@pytest.mark.django_db
def test_provider_failure_is_sanitized_and_other_documents_still_run(
    extraction_workflow, tmp_path, monkeypatch
):
    from docai.management.commands import test_extraction

    source, output = tmp_path / "inputs", tmp_path / "outputs"
    source.mkdir()
    (source / "bad.pdf").touch()
    (source / "good.pdf").touch()

    def preview(path, destination, context):
        if path.name == "bad.pdf":
            raise IntegrationError("secret provider content")
        return {"status": "succeeded", "labels": 0, "boxed": 0, "unboxed": 0, "images": []}

    monkeypatch.setattr(test_extraction, "check_renderer", lambda: None)
    monkeypatch.setattr(test_extraction, "preview_file", preview)
    stdout, stderr = io.StringIO(), io.StringIO()
    with pytest.raises(CommandError, match="1 file"):
        call_command(
            "test_extraction",
            "--workflow-id",
            str(extraction_workflow.id),
            "--input",
            str(source),
            "--output",
            str(output),
            stdout=stdout,
            stderr=stderr,
        )
    manifest = (output / "manifest.json").read_text()
    assert "secret provider content" not in manifest + stdout.getvalue() + stderr.getvalue()
    assert [d["status"] for d in json.loads(manifest)["documents"]] == ["failed", "succeeded"]


@pytest.mark.django_db
def test_missing_renderer_fails_before_provider_call(extraction_workflow, tmp_path, monkeypatch):
    from docai.management.commands import test_extraction

    source = tmp_path / "sample.pdf"
    source.touch()
    provider = Mock()
    monkeypatch.setattr(test_extraction, "preview_file", provider)
    monkeypatch.setattr(extraction_visualization.importlib.util, "find_spec", lambda name: None)
    with pytest.raises(CommandError, match="image-normalization"):
        invoke(extraction_workflow, source, tmp_path / "outputs")
    provider.assert_not_called()


@pytest.mark.django_db
def test_classification_workflow_is_rejected(sample_workflow, tmp_path, monkeypatch):
    from docai.management.commands import test_extraction

    source = tmp_path / "sample.pdf"
    source.touch()
    monkeypatch.setattr(test_extraction, "check_renderer", lambda: None)
    with pytest.raises(CommandError, match="extraction-only"):
        invoke(sample_workflow, source, tmp_path / "outputs")


@pytest.mark.django_db
def test_incomplete_layout_is_rejected_before_extraction(
    extraction_workflow, tmp_path, monkeypatch
):
    from docai.synthetic.pdfwriter import write_pdf

    source = tmp_path / "two-pages.pdf"
    source.write_bytes(write_pdf([["First"], ["Second"]]))
    ctx = extraction_preview.workflow_context(extraction_workflow, live=False)
    invocation = Mock()
    monkeypatch.setattr(ctx.llm, "invoke", invocation)
    provider = Mock(key="fixture")
    provider.analyze.return_value = LayoutDocument(
        document_id="fixture",
        source_format="pdf",
        service="fixture",
        units=[LayoutPage(index=0, number=1, content="Partial")],
    )
    monkeypatch.setattr(
        extraction_preview, "get_layout_provider_for_format", lambda *args: provider
    )
    with pytest.raises(IntegrationError) as error:
        extraction_preview.preview_file(source, tmp_path / "output", ctx)
    assert error.value.error_code == "INCOMPLETE_LAYOUT"
    invocation.assert_not_called()


@pytest.mark.django_db
def test_template_context_uses_the_pinned_template_prompt_schema_and_chunking(project, admin):
    from docai.models import ExtractionTemplate, ModelConfiguration

    schema = governance.new_schema_version("template-w2", [{"name": "wages"}])
    prompt = governance.new_prompt_version(
        "template-prompt", "extraction", "Template instructions", "{content}"
    )
    model = ModelConfiguration.objects.create(
        name="template-model", deployment="template-deployment", adapter="mock"
    )
    ExtractionTemplate.objects.create(
        project=project,
        name="template",
        document_type="w2",
        schema_version=schema,
        prompt_version=prompt,
        model_config=model,
        chunking={"strategy": "page"},
    )
    wf = governance.create_workflow_version(
        project,
        "preview-template",
        "extract_template",
        {
            "template_name": "template",
            "template_version": 1,
        },
        admin,
    )
    ctx = extraction_preview.workflow_context(wf, live=False)
    assert ctx.prompts["extraction"].name == prompt.name
    assert ctx.config.chunking.strategy == "page"
    assert vars(ctx)["template"]["schema"]["name"] == schema.name
    assert ctx.llm.key == "mock"


def test_large_label_sets_and_unknown_pages_are_all_rendered(tmp_path):
    pytest.importorskip("PIL")
    pytest.importorskip("pypdfium2")
    from docai.synthetic.pdfwriter import write_pdf

    source = tmp_path / "sample.pdf"
    source.write_bytes(write_pdf([["Evidence"]]))
    layout = LayoutDocument(
        document_id="fixture",
        source_format="pdf",
        service="fixture",
        units=[LayoutPage(index=0, number=1)],
    )
    result = DocumentResult(
        fields=[field(f"field_{i}", "100", grounding=hit()) for i in range(91)]
        + [field("unlocated", "value")]
    )
    labels = extraction_visualization.collect_labels(result, layout)
    files = extraction_visualization.render_labels(
        source, tmp_path, labels, layout=layout, title="sample"
    )
    assert files == ["page-001.jpg", "page-001-labels-02.jpg", "unlocated-labels-001.jpg"]
    assert all((tmp_path / name).read_bytes().startswith(b"\xff\xd8") for name in files)


def test_large_pdf_pages_can_downscale_for_previews_while_enhancement_keeps_its_limit(tmp_path):
    pytest.importorskip("PIL")
    pytest.importorskip("pypdfium2")
    from pypdf import PdfWriter

    from docai.exceptions import NormalizationLimitExceeded
    from docai.input_quality.pdf import render_page

    source = tmp_path / "large-page.pdf"
    with PdfWriter() as writer:
        writer.add_blank_page(width=3500, height=4000)
        writer.write(source)
    with pytest.raises(NormalizationLimitExceeded):
        render_page(source, 0, max_pixels=6_000_000, max_dimension=3000)
    image, _dpi = render_page(
        source, 0, max_pixels=6_000_000, max_dimension=3000, allow_downscale=True
    )
    try:
        assert image.width * image.height <= 6_000_000 and max(image.size) <= 3000
    finally:
        image.close()


@pytest.mark.django_db
def test_render_failure_preserves_extraction_output(
    extraction_workflow, tmp_path, w2_pdf, monkeypatch
):
    source, output = tmp_path / "sample.pdf", tmp_path / "output"
    source.write_bytes(w2_pdf.data)
    ctx = extraction_preview.workflow_context(extraction_workflow, live=False)

    def rendering(*args, **kwargs):
        raise RuntimeError("Graphics unavailable")

    monkeypatch.setattr(extraction_preview, "render_labels", rendering)
    with pytest.raises(RuntimeError, match="Graphics"):
        extraction_preview.preview_file(source, output, ctx)
    saved = json.loads((output / "result.json").read_text())
    assert saved["summary"]["status"] == "extracted"
    assert len(saved["result"]["fields"]) == 2
    assert (output / "layout.json").exists() and (output / "labels.csv").exists()


@pytest.mark.django_db
@pytest.mark.parametrize("recursive", [False, True])
def test_mixed_folder_selects_formats_with_limit_and_excludes_previous_outputs(
    extraction_workflow, tmp_path, monkeypatch, recursive
):
    from docai.management.commands import test_extraction

    source = tmp_path / "inputs"
    source.mkdir()
    output = source / "outputs"
    output.mkdir()
    (source / "nested").mkdir()
    for name in ("a.JPG", "b.pdf", "c.png", "d.TIFF", "ignore.gif", "ignore.txt"):
        (source / name).touch()
    (source / "nested" / "form.JPEG").touch()
    (source / "nested" / "form.tif").touch()
    for name in ("previous.jpg", "previous.pdf", "previous.tiff"):
        (output / name).touch()
    calls = []

    def preview(path, destination, context):
        calls.append(path.relative_to(source).as_posix())
        return {"status": "succeeded", "labels": 0, "boxed": 0, "unboxed": 0}

    monkeypatch.setattr(test_extraction, "check_renderer", lambda: None)
    monkeypatch.setattr(test_extraction, "preview_file", preview)
    invoke(
        extraction_workflow,
        source,
        output,
        "--limit",
        "5",
        *(["--recursive"] if recursive else []),
    )
    manifest = json.loads((output / "manifest.json").read_text())
    assert calls == ["a.JPG", "b.pdf", "c.png", "d.TIFF"] + (
        ["nested/form.JPEG"] if recursive else []
    )
    assert manifest["selected"] == (5 if recursive else 4)
    assert manifest["omitted"] == (1 if recursive else 0)


def raster_fixture(source, image_format, colors):
    """Distinct frames and geometry make a swapped frame or rotation observable."""
    pytest.importorskip("PIL")
    from PIL import Image, ImageDraw

    images = [Image.new("RGB", (1000, 600), color) for color in colors]
    try:
        for image in images:
            ImageDraw.Draw(image).rectangle((100, 60, 200, 120), fill="black")
        images[0].save(source, image_format, save_all=len(images) > 1, append_images=images[1:])
    finally:
        for image in images:
            image.close()
    units = []
    for index in range(len(colors)):
        value = f"{index + 1}00.00"
        text = "Wages: " + value
        polygon = [0.1, 0.1, 0.2, 0.1, 0.2, 0.2, 0.1, 0.2]
        units.append(
            LayoutPage(
                index=index,
                number=index + 1,
                width=1000,
                height=600,
                unit="pixel",
                content=text,
                words=[
                    Word(
                        id=f"p{index + 1}:w0",
                        text=value,
                        span=Span(offset=7, length=len(value)),
                        polygon=polygon,
                    )
                ],
                paragraphs=[
                    Paragraph(
                        id=f"p{index + 1}:para0",
                        text=text,
                        span=Span(offset=0, length=len(text)),
                        polygon=polygon,
                    )
                ],
            )
        )
    layout = LayoutDocument(
        document_id="fixture", source_format=image_format.lower(), service="fixture", units=units
    )
    source.with_suffix(source.suffix + ".layout.json").write_text(layout.model_dump_json())
    return layout


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("extension", "image_format", "colors", "source_format"),
    [
        (".jpg", "JPEG", ["red"], "jpeg"),
        (".JPEG", "JPEG", ["red"], "jpeg"),
        (".png", "PNG", ["red"], "png"),
        (".TIF", "TIFF", ["red", "lime"], "tiff"),
        (".tiff", "TIFF", ["red", "lime"], "tiff"),
    ],
)
def test_native_raster_command_uses_real_pipeline_frames_and_aligned_boxes_without_writes(
    project, admin, tmp_path, monkeypatch, extension, image_format, colors, source_format
):
    pytest.importorskip("pypdfium2")
    from PIL import Image

    from docai.management.commands import test_extraction

    source, output = tmp_path / ("sample" + extension), tmp_path / "outputs"
    raster_fixture(source, image_format, colors)
    workflow = governance.create_workflow_version(
        project,
        "image-preview",
        "extract_structured",
        {"mode": "default", "layout": {"include_source_ids": False}},
        admin,
    )
    context = extraction_preview.workflow_context(workflow, live=False)
    context.layout_adapter_key = "fixture"
    monkeypatch.setattr(test_extraction, "workflow_context", lambda *args, **kwargs: context)
    with CaptureQueriesContext(connection) as queries:
        invoke(workflow, source, output, "--live")
    assert not any(
        q["sql"].lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")) for q in queries
    )
    document = json.loads((output / "manifest.json").read_text())["documents"][0]
    assert document["status"] == "succeeded"
    assert document["pages"] == document["labels"] == document["boxed"] == len(colors)
    assert document["source_format"] == document["prepared_format"] == source_format
    assert document["images"] == [f"page-{i + 1:03}.jpg" for i in range(len(colors))]
    destination = output / document["output"]
    labels = json.loads((destination / "labels.json").read_text())
    assert [label["unit_index"] for label in labels] == list(range(len(colors)))
    for index, expected_color in enumerate([(255, 0, 0), (0, 255, 0)][: len(colors)]):
        with Image.open(destination / document["images"][index]) as image:
            assert (
                max(
                    abs(a - b)
                    for a, b in zip(rgb_pixel(image, (530, 500)), expected_color, strict=True)
                )
                < 8
            )
            # Native 1000x600 pixels are pasted at (30,200); the recorded 0.1-0.2 box
            # must overlay the black source rectangle on its own original frame.
            blue = rgb_pixel(image, (130, 290))
            assert blue[2] > 150 and blue[0] < 40
            assert max(rgb_pixel(image, (180, 290))) < 15


@pytest.mark.django_db
def test_raster_input_requires_ocr_and_corrupt_or_incomplete_tiff_never_calls_model(
    extraction_workflow, tmp_path, monkeypatch
):
    from docai.exceptions import CorruptFile, UnsupportedFile

    source = tmp_path / "sample.tif"
    raster_fixture(source, "TIFF", ["red", "lime"])
    ctx = extraction_preview.workflow_context(extraction_workflow, live=False)
    invoke_model = Mock()
    monkeypatch.setattr(ctx.llm, "invoke", invoke_model)
    with pytest.raises(UnsupportedFile) as unsupported:
        extraction_preview.preview_file(source, tmp_path / "output", ctx)
    assert unsupported.value.error_code == "LAYOUT_ADAPTER_UNSUPPORTED"
    ctx.layout_adapter_key = "fixture"
    sidecar = source.with_suffix(source.suffix + ".layout.json")
    fixture = json.loads(sidecar.read_text())
    fixture["units"] = fixture["units"][:1]
    sidecar.write_text(json.dumps(fixture))
    with pytest.raises(IntegrationError) as incomplete:
        extraction_preview.preview_file(source, tmp_path / "output", ctx)
    assert incomplete.value.error_code == "INCOMPLETE_LAYOUT"
    fixture["units"][0].update(index=2, number=3)
    sidecar.write_text(json.dumps(fixture))
    with pytest.raises(IntegrationError) as invalid_index:
        extraction_preview.preview_file(source, tmp_path / "output", ctx)
    assert invalid_index.value.error_code == "INCOMPLETE_LAYOUT"
    source.write_bytes(b"II*\x00 damaged TIFF")
    with pytest.raises(CorruptFile):
        extraction_preview.preview_file(source, tmp_path / "output", ctx)
    invoke_model.assert_not_called()


@pytest.mark.django_db
def test_tiff_page_and_frame_pixel_limits_precede_ocr(
    extraction_workflow, tmp_path, monkeypatch, settings
):
    from docai.exceptions import ValidationFailed

    source = tmp_path / "sample.tiff"
    raster_fixture(source, "TIFF", ["red", "lime"])
    ctx = extraction_preview.workflow_context(extraction_workflow, live=False)
    ctx.layout_adapter_key = "fixture"
    provider = Mock()
    monkeypatch.setattr(extraction_preview, "get_layout_provider_for_format", provider)
    settings.DOCAI = {**settings.DOCAI, "MAX_PAGES": 1}
    with pytest.raises(ValidationFailed) as error:
        extraction_preview.preview_file(source, tmp_path / "output", ctx)
    assert error.value.error_code == "TOO_MANY_PAGES"
    settings.DOCAI = {**settings.DOCAI, "MAX_PAGES": 2}
    settings.DOCAI_IMAGE_NORMALIZATION_MAX_PIXELS = 1_000
    with pytest.raises(ValidationFailed) as error:
        extraction_preview.preview_file(source, tmp_path / "output", ctx)
    assert error.value.error_code == "IMAGE_LIMIT_EXCEEDED"
    provider.assert_not_called()


@pytest.mark.django_db
def test_truncated_image_pixels_are_rejected_before_ocr(extraction_workflow, tmp_path, monkeypatch):
    from docai.exceptions import CorruptFile

    source = tmp_path / "sample.png"
    raster_fixture(source, "PNG", ["red"])
    data = source.read_bytes()
    source.write_bytes(data[: len(data) // 2])  # Preserve the format/dimension headers.
    ctx = extraction_preview.workflow_context(extraction_workflow, live=False)
    ctx.layout_adapter_key = "fixture"
    provider = Mock()
    monkeypatch.setattr(extraction_preview, "get_layout_provider_for_format", provider)
    with pytest.raises(CorruptFile):
        extraction_preview.preview_file(source, tmp_path / "output", ctx)
    provider.assert_not_called()


def test_off_raster_renderer_does_not_apply_an_independent_exif_rotation(tmp_path):
    pytest.importorskip("pypdfium2")
    from PIL import Image, ImageDraw

    source = tmp_path / "oriented.jpg"
    with Image.new("RGB", (1000, 600), "red") as image:
        ImageDraw.Draw(image).rectangle((100, 60, 200, 120), fill="black")
        exif = Image.Exif()
        exif[274] = 6
        image.save(source, "JPEG", quality=95, exif=exif)
    layout = LayoutDocument(
        document_id="fixture",
        source_format="jpeg",
        service="fixture",
        units=[LayoutPage(index=0, number=1)],
    )
    labels = extraction_visualization.collect_labels(
        DocumentResult(fields=[field("Wages", "100.00", grounding=hit())]), layout
    )
    extraction_visualization.render_labels(
        source, tmp_path, labels, layout=layout, title="fixture", source_format="jpeg"
    )
    with Image.open(tmp_path / "page-001.jpg") as image:
        assert max(rgb_pixel(image, (180, 290))) < 15
        blue = rgb_pixel(image, (130, 290))
        assert blue[2] > 150 and blue[0] < 40


@pytest.mark.django_db
def test_adaptive_tiff_preview_renders_prepared_pdf_with_original_skipped_page_numbers(
    extraction_workflow, tmp_path, monkeypatch, settings
):
    pytest.importorskip("cv2")
    pytest.importorskip("pypdfium2")
    from PIL import Image, ImageDraw
    from pypdf import PdfReader

    from docai.schemas.config import InputQualityConfig

    source, output = tmp_path / "sample.tiff", tmp_path / "output"
    layout = raster_fixture(source, "TIFF", ["white", "lime"])
    # The first frame is truly blank and must remain reviewable at original page 1.
    with (
        Image.new("RGB", (1000, 600), "white") as first,
        Image.new("RGB", (1000, 600), "lime") as second,
    ):
        ImageDraw.Draw(second).rectangle((100, 60, 200, 120), fill="black")
        first.save(source, "TIFF", save_all=True, append_images=[second])
    settings.DOCAI_IMAGE_NORMALIZATION_ENABLED = True
    ctx = extraction_preview.workflow_context(extraction_workflow, live=False)
    ctx.layout_adapter_key = "azure_di"
    ctx.config = ctx.config.model_copy(
        update={
            "input_quality": InputQualityConfig(mode="adaptive", skip_blank_pages=True),
            "layout": ctx.config.layout.model_copy(update={"include_source_ids": False}),
        }
    )
    analyzed = []

    def analyze(path, **kwargs):
        assert path != source and path.suffix == ".pdf"
        assert kwargs["source_format"] == "pdf" and kwargs["pages"] == "2"
        with PdfReader(path) as reader:
            assert len(reader.pages) == 2
        analyzed.append(path)
        return layout.model_copy(update={"source_format": "pdf", "units": [layout.pages[1]]})

    provider = Mock(key="fixture", supports_ocr=True, analyze=analyze)
    monkeypatch.setattr(
        extraction_preview, "get_layout_provider_for_format", lambda *args: provider
    )
    summary = extraction_preview.preview_file(source, output, ctx)
    assert summary["source_format"] == "tiff" and summary["prepared_format"] == "pdf"
    assert summary["pages"] == 2 and summary["boxed"] == 1
    assert summary["images"] == ["page-001.jpg", "page-002.jpg"]
    assert not analyzed[0].exists()  # Preparation owns and cleans its temporary PDF.
    saved_layout = json.loads((output / "layout.json").read_text())
    assert [unit["index"] for unit in saved_layout["units"]] == [0, 1]
    assert saved_layout["units"][0]["excluded_from_analysis"] is True
    labels = json.loads((output / "labels.json").read_text())
    assert labels[0]["unit_index"] == 1
    with Image.open(output / "page-001.jpg") as image:
        assert min(rgb_pixel(image, (650, 500))) > 245
    with Image.open(output / "page-002.jpg") as image:
        blue = rgb_pixel(image, (130, 290))
        assert blue[2] > 150 and blue[0] < 40
        assert max(rgb_pixel(image, (180, 290))) < 15
