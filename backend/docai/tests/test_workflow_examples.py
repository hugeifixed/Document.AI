"""Keep the copy/paste examples valid through the same API used by the builder."""

import json
from pathlib import Path

import pytest

from docai.schemas.config import CONFIG_SCHEMAS, validate_workflow_config

EXAMPLES = Path(__file__).resolve().parents[3] / "examples" / "workflows"
FILES = sorted(EXAMPLES.glob("*/*.json"))


def assert_preserved(submitted, normalized):
    """Pydantic permits extra keys; catch examples that silently lose a typo."""
    if isinstance(submitted, dict):
        for key, value in submitted.items():
            assert key in normalized, f"Unrecognized example key: {key}"
            assert_preserved(value, normalized[key])
    elif isinstance(submitted, list):
        assert len(submitted) == len(normalized)
        for value, result in zip(submitted, normalized, strict=True):
            assert_preserved(value, result)
    else:
        assert submitted == normalized


def test_example_inventory_covers_all_workflow_types():
    assert {path.parent.name for path in FILES} == set(CONFIG_SCHEMAS)
    readme = (EXAMPLES / "README.md").read_text(encoding="utf-8")
    for path in FILES:
        assert path.relative_to(EXAMPLES).as_posix() in readme


@pytest.mark.django_db
@pytest.mark.parametrize("path", FILES, ids=lambda path: path.relative_to(EXAMPLES).as_posix())
def test_example_validates_and_creates_a_workflow_version(path, api, project):
    body = json.loads(path.read_text(encoding="utf-8"))
    workflow_type = path.parent.name
    # Leave settings owned by the UI controls out of the pasteable examples.
    assert not {"model", "chunking", "layout", "input_quality", "di_analysis"} & body.keys()
    normalized = validate_workflow_config(workflow_type, body)
    assert_preserved(body, normalized)
    schemas = [body["schema"]] if "schema" in body else body.get("schemas", [])
    for schema in schemas:
        names = [field["name"] for field in schema["fields"]]
        assert len(names) == len(set(names)), (
            "Duplicate field names cannot be reviewed independently"
        )

    request = {"workflow_type": workflow_type, "config": body}
    validation = api.post("/api/v1/workflows/validate/", request, format="json")
    assert validation.status_code == 200, validation.data
    assert validation.data["valid"] is True
    creation = api.post(
        "/api/v1/workflows/",
        {"project": str(project.pk), "name": path.stem, **request},
        format="json",
    )
    assert creation.status_code == 201, creation.data
    assert creation.data["version"] == 1
    assert creation.data["config"] == normalized
    assert creation.data["content_hash"] == validation.data["content_hash"]


def test_mixed_package_uses_the_same_schemas_as_standalone_examples():
    mixed = json.loads(
        (EXAMPLES / "unbundle_classify_extract/w2-1099-promissory-note.json").read_text(
            encoding="utf-8"
        )
    )
    standalone = [
        json.loads((EXAMPLES / path).read_text(encoding="utf-8"))["schema"]
        for path in (
            "extract_structured/w2.json",
            "extract_structured/1099-common.json",
            "extract_unstructured/promissory-note.json",
        )
    ]
    assert mixed["schemas"] == standalone
