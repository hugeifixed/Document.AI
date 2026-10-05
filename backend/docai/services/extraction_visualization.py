"""Draw saved evidence on source pages; missing boxes remain orange labels, never guessed."""

from __future__ import annotations

import csv
import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path

from docai.grounding.provenance import field_locations
from docai.schemas.layout import LayoutDocument
from docai.workflows.base import DocumentResult

COLORS = {"blue": (5, 87, 184), "green": (5, 110, 56), "orange": (180, 82, 3)}
GRAY = (80, 87, 100)
LABELS_PER_PANEL = 90


class RendererUnavailable(RuntimeError):
    pass


def check_renderer() -> None:
    if any(importlib.util.find_spec(name) is None for name in ("PIL", "pypdfium2")):
        raise RendererUnavailable(
            "JPG rendering needs the image-normalization extra: uv sync --extra image-normalization."
        )


def collect_labels(result: DocumentResult, layout: LayoutDocument) -> list[dict]:
    pages = {page.index for page in layout.pages}
    labels = []
    for index, field in enumerate(result.fields, 1):
        for number, location in enumerate(field_locations(field), 1):
            path = location.provenance.property_path
            boxed = location.boxed
            unit = location.display_unit_index
            labels.append(
                {
                    "id": f"L{index:03}.{number:03}" if path is not None else f"F{index:03}",
                    "name": field.name,
                    "path": path or "",
                    "value": location.value,
                    "unit_index": unit if unit in pages else None,
                    "boxed": boxed,
                    "color": ("green" if path is not None else "blue") if boxed else "orange",
                    "status": location.status if path is not None or boxed else "unverified",
                    "grounding": location.grounding if boxed else None,
                    "citation_repaired": location.provenance.citation_repaired,
                    "review": field.review_outcome,
                }
            )
    return labels


def write_labels(output: Path, labels: list[dict]) -> None:
    (output / "labels.json").write_text(
        json.dumps(labels, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    with (output / "labels.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "id",
                "name",
                "path",
                "value",
                "unit_index",
                "boxed",
                "color",
                "status",
                "citation_repaired",
                "review",
            ],
        )
        writer.writeheader()
        writer.writerows({key: label[key] for key in writer.fieldnames} for label in labels)


def render_labels(
    source: Path,
    output: Path,
    labels: list[dict],
    *,
    layout: LayoutDocument,
    title: str,
    source_format: str = "pdf",
) -> list[str]:
    check_renderer()
    from PIL import Image, ImageDraw, ImageFont

    from docai.input_quality.pdf import render_page

    font = ImageFont.load_default(size=19)
    small = ImageFont.load_default(size=17)
    heading = ImageFont.load_default(size=30)
    files = []

    def text(draw, xy, value, *, fill=GRAY, selected_font=font, max_width=590):
        value = " ".join(str(value).split())
        while value and draw.textlength(value, font=selected_font) > max_width:
            value = value[:-4] + "..." if len(value) > 4 else ""
        draw.text(xy, value, font=selected_font, fill=fill)

    def panel(image, selected, filename, page_title):
        with Image.new("RGB", (2600, 2400), "white") as canvas:
            draw = ImageDraw.Draw(canvas)
            text(draw, (30, 25), title, selected_font=heading, max_width=2500)
            text(draw, (30, 70), page_title, max_width=2500)
            text(
                draw,
                (30, 105),
                f"{len(labels)} detected values | {sum(x['boxed'] for x in labels)} boxes | {sum(not x['boxed'] for x in labels)} unboxed",
                max_width=2500,
            )
            for x, color, caption in [
                (30, "blue", "BLUE: scalar box"),
                (510, "green", "GREEN: list property box"),
                (1110, "orange", "ORANGE: unverified location"),
            ]:
                text(draw, (x, 145), caption, fill=COLORS[color])
            if image is not None:
                image.thumbnail((1240, 2100))
                canvas.paste(image, (30, 200))
                for label in selected:
                    if not label["boxed"]:
                        continue
                    poly = label["grounding"]["polygon"]
                    left, top, right, bottom = (
                        min(poly[::2]),
                        min(poly[1::2]),
                        max(poly[::2]),
                        max(poly[1::2]),
                    )
                    box = (
                        30 + left * image.width,
                        200 + top * image.height,
                        30 + right * image.width,
                        200 + bottom * image.height,
                    )
                    draw.rectangle(box, outline=COLORS[label["color"]], width=3)
                    badge = label["id"] + ("*" if label["citation_repaired"] else "")
                    badge_xy = (box[0], max(200, box[1] - 19))
                    draw.rectangle(draw.textbbox(badge_xy, badge, font=small), fill="white")
                    draw.text(badge_xy, badge, font=small, fill=COLORS[label["color"]])
            for index, label in enumerate(selected):
                column, row = divmod(index, 45)
                x, y = 1310 + column * 630, 205 + row * 46
                badge = label["id"] + ("*" if label["citation_repaired"] else "")
                text(
                    draw,
                    (x, y),
                    f"{badge} {label['name']}{label['path']}",
                    fill=COLORS[label["color"]],
                )
                value = (
                    label["value"]
                    if isinstance(label["value"], str)
                    else json.dumps(label["value"], ensure_ascii=False)
                )
                text(draw, (x + 10, y + 23), value, selected_font=small)
            text(
                draw,
                (30, 2330),
                "* Citation corrected. Collections and corrected fields require review of record association.",
                max_width=2500,
            )
            text(
                draw,
                (30, 2360),
                "Boxes show recorded source geometry. Detection and location coverage do not establish complete field accuracy.",
                selected_font=small,
                max_width=2500,
            )
            canvas.save(output / filename, "JPEG", quality=95, subsampling=0)
            files.append(filename)

    with Image.open(source) if source_format != "pdf" else nullcontext() as frames:
        for page in layout.pages:
            selected = [label for label in labels if label["unit_index"] == page.index]
            if frames is None:
                image, _dpi = render_page(
                    source,
                    page.index,
                    max_pixels=6_000_000,
                    max_dimension=3000,
                    allow_downscale=True,
                )
            else:
                frames.seek(page.index)
                # Use the analyzed pixels: no independent orientation/enhancement transform.
                image = frames.convert("RGB")
            try:
                for start in range(0, max(1, len(selected)), LABELS_PER_PANEL):
                    suffix = "" if start == 0 else f"-labels-{start // LABELS_PER_PANEL + 1:02}"
                    page_title = f"Page {page.number}" + (
                        " | excluded from analysis" if page.excluded_from_analysis else ""
                    )
                    panel(
                        image,
                        selected[start : start + LABELS_PER_PANEL],
                        f"page-{page.number:03}{suffix}.jpg",
                        page_title,
                    )
            finally:
                image.close()
    unlocated = [label for label in labels if label["unit_index"] is None]
    for start in range(0, len(unlocated), LABELS_PER_PANEL):
        panel(
            None,
            unlocated[start : start + LABELS_PER_PANEL],
            f"unlocated-labels-{start // LABELS_PER_PANEL + 1:03}.jpg",
            "Detected values without a uniquely identified source page",
        )
    return files
