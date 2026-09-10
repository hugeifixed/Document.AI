"""Generate clearly-labeled synthetic documents into a dataset and create their
ground-truth labels (field, category, and segment-range labels)."""
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from docai.models import LABEL_KIND, LABEL_STATUS, Dataset, GroundTruthLabel, Project, SOURCE_KIND, SourceUnit
from docai.services import ingestion
from docai.services.layouts import get_or_build_layout
from docai.synthetic.generators import make_docs, make_text, make_workbook
from docai.validation.normalize import normalize_value


class Command(BaseCommand):
    help = "Create synthetic documents + ground truth in <project>/<dataset>."

    def add_arguments(self, parser):
        parser.add_argument("--project", default="sample-banking-docs")
        parser.add_argument("--dataset", default="synthetic-dev")
        parser.add_argument("--split", default="dev")
        parser.add_argument("--seed", type=int, default=7)
        parser.add_argument("--build-layouts", action="store_true", help="Run the layout adapter now (pypdf locally).")

    def handle(self, *args, **opts):
        project = Project.objects.get(slug=opts["project"])
        user = User.objects.filter(is_superuser=True).first()
        dataset, _ = Dataset.objects.get_or_create(project=project, name=opts["dataset"],
                                                   defaults={"split": opts["split"], "created_by": user})
        created, skipped = 0, 0
        docs = make_docs(opts["seed"])
        for sd in docs:
            try:
                doc = ingestion.ingest_upload(dataset, sd.filename, sd.data, user=user, source="synthetic")
            except Exception as exc:  # duplicate on re-run
                skipped += 1; self.stdout.write(f"skip {sd.filename}: {type(exc).__name__}"); continue
            created += 1
            if sd.category == "package":
                for seg in sd.segments:
                    GroundTruthLabel.objects.create(document=doc, kind=LABEL_KIND.segment, category=seg["category"],
                                                    segment_start=seg["start"], segment_end=seg["end"], labeler=user,
                                                    status=LABEL_STATUS.final, version=1, created_by=user)
            else:
                GroundTruthLabel.objects.create(document=doc, kind=LABEL_KIND.category, category=sd.category, labeler=user,
                                                status=LABEL_STATUS.final, version=1, created_by=user)
                for name, val in sd.fields.items():
                    GroundTruthLabel.objects.create(document=doc, kind=LABEL_KIND.field, field_name=name, expected_value=val,
                                                    normalized_value=normalize_value(val), is_absent=val is None, labeler=user,
                                                    status=LABEL_STATUS.final, version=1, created_by=user,
                                                    mapping_method="synthetic", match_score=1.0)
            if opts["build_layouts"]:
                get_or_build_layout(doc)
        # spreadsheet + text
        xlsx, xtruth = make_workbook()
        try:
            xdoc = ingestion.ingest_upload(dataset, "balance_sheet_synthetic.xlsx", xlsx, user=user, source="synthetic")
            created += 1
            for name, val in xtruth.items():
                GroundTruthLabel.objects.create(document=xdoc, kind=LABEL_KIND.field, field_name=name, expected_value=val,
                                                normalized_value=normalize_value(val), labeler=user, status=LABEL_STATUS.final,
                                                version=1, created_by=user, mapping_method="synthetic", match_score=1.0)
            if opts["build_layouts"]:
                get_or_build_layout(xdoc)
        except Exception as exc:
            skipped += 1; self.stdout.write(f"skip workbook: {type(exc).__name__}")
        txt, ttruth = make_text()
        try:
            tdoc = ingestion.ingest_upload(dataset, "invoice_synthetic.txt", txt, user=user, source="synthetic")
            created += 1
            GroundTruthLabel.objects.create(document=tdoc, kind=LABEL_KIND.category, category="invoice", labeler=user,
                                            status=LABEL_STATUS.final, version=1, created_by=user)
            for name, val in ttruth.items():
                GroundTruthLabel.objects.create(document=tdoc, kind=LABEL_KIND.field, field_name=name, expected_value=val,
                                                normalized_value=normalize_value(val), labeler=user, status=LABEL_STATUS.final,
                                                version=1, created_by=user, mapping_method="synthetic", match_score=1.0)
        except Exception as exc:
            skipped += 1; self.stdout.write(f"skip text: {type(exc).__name__}")
        self.stdout.write(self.style.SUCCESS(f"dataset '{dataset.name}' ({dataset.id}): {created} created, {skipped} skipped; "
                                             f"labels={GroundTruthLabel.objects.filter(document__dataset=dataset).count()}"))
