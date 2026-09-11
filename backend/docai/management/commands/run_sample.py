"""End-to-end local sample: run a workflow over the synthetic dataset with the
configured adapters (pypdf + mock by default), evaluate against ground truth,
and print a summary + export paths."""

import json
from pathlib import Path

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from docai.models import Dataset, Project, WorkflowConfiguration
from docai.services import evaluation as eval_svc
from docai.services import export as export_svc
from docai.services import runs as run_svc


class Command(BaseCommand):
    help = "Run a workflow on the synthetic dataset and evaluate it."

    def add_arguments(self, parser):
        parser.add_argument("--project", default="sample-banking-docs")
        parser.add_argument("--dataset", default="synthetic-dev")
        parser.add_argument("--workflow", default="unbundle-classify-extract")
        parser.add_argument("--sample", type=int, default=None)
        parser.add_argument("--export-dir", default=None)

    def handle(self, *args, **opts):
        project = Project.available_objects.get(slug=opts["project"])
        dataset = Dataset.available_objects.get(project=project, name=opts["dataset"])
        wf = (
            WorkflowConfiguration.objects.filter(project=project, name=opts["workflow"])
            .order_by("-version")
            .first()
        )
        if wf is None:
            raise CommandError(f"Workflow {opts['workflow']!r} was not found.")
        user = User.objects.filter(is_superuser=True).first()
        run = run_svc.create_run(
            project, wf, dataset, user, name=f"sample:{wf.name}", sample_size=opts["sample"]
        )
        self.stdout.write(
            f"run {run.id} created: {run.total_items} items, adapters layout={run.layout_adapter} llm={run.llm_adapter}"
        )
        run = run_svc.execute_run(run.id)
        self.stdout.write(
            f"status={run.status} processed={run.processed_items} failed={run.failed_items}"
        )
        for item in run.items.filter(status="failed").select_related("document"):
            self.stdout.write(
                f"  FAILED {item.document.original_filename}: {item.error_code} — {item.error_message}"
            )
        ev = eval_svc.create_evaluation(run, user)
        m = ev.metrics
        if m.get("has_ground_truth"):
            ex = m.get("extraction", {}).get("aggregate", {})
            self.stdout.write(
                f"extraction: acc={ex.get('accuracy')} P={ex.get('precision')} R={ex.get('recall')} "
                f"F1={ex.get('f1')} spec={ex.get('specificity')} npv={ex.get('npv')} support={ex.get('support')}"
            )
            for name, pf in sorted(m.get("extraction", {}).get("per_field", {}).items()):
                self.stdout.write(
                    f"  {name:<24} match={pf['match']:<3} mismatch={pf['mismatch']:<3} missing={pf['missing']:<3} "
                    f"spurious={pf['spurious']:<3} tb={pf['true_blank']:<3} F1={pf['f1']}"
                )
            cl = m.get("classification", {})
            if cl:
                self.stdout.write(
                    f"classification: acc={cl.get('accuracy')} macroF1={cl['macro']['f1']} labels={cl['labels']}"
                )
            sg = m.get("segmentation", {}).get("aggregate", {})
            if sg:
                self.stdout.write(
                    f"segmentation: boundaryF1={sg.get('boundary_f1')} pageAcc={sg.get('page_level_category_accuracy')} "
                    f"exact={sg.get('exact_segment_match_rate')} docs={sg.get('document_count')}"
                )
        else:
            self.stdout.write("no ground truth: quality indicators only")
        out_dir = Path(opts["export_dir"] or settings.DOCAI_DATA_DIR / "exports")
        out_dir.mkdir(parents=True, exist_ok=True)
        pkg = export_svc.run_package(run)
        (out_dir / f"run-{str(run.id)[:8]}.json").write_bytes(export_svc.to_json_bytes(pkg))
        (out_dir / f"run-{str(run.id)[:8]}-fields.csv").write_bytes(
            export_svc.rows_to_csv(pkg["fields"])
        )
        (out_dir / f"run-{str(run.id)[:8]}.xlsx").write_bytes(
            export_svc.rows_to_xlsx(
                {"fields": pkg["fields"], "classifications": pkg["classifications"]}
            )
        )
        self.stdout.write(self.style.SUCCESS(f"exports written to {out_dir}"))
        self.stdout.write(
            json.dumps({"run_id": str(run.id), "evaluation_id": str(ev.id), "status": run.status})
        )
