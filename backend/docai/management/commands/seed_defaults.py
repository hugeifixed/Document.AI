"""Create RBAC groups, default prompt versions, and (optionally) a local admin
and a sample project with reference workflow configurations."""

from django.conf import settings
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand

from docai.models import Project
from docai.services import governance

W2_FIELDS = [
    {
        "name": "employee_name",
        "description": "Employee's full name (box e)",
        "type": "string",
        "required": True,
        "match_mode": "fuzzy",
    },
    {
        "name": "employee_ssn",
        "description": "Employee's social security number (box a)",
        "type": "identifier",
        "required": True,
        "validation": [
            {
                "kind": "regex",
                "pattern": r"^\d{3}-\d{2}-\d{4}$",
                "message": "SSN must be ###-##-####",
            }
        ],
    },
    {
        "name": "employer_name",
        "description": "Employer's name (box c)",
        "type": "string",
        "required": True,
        "match_mode": "fuzzy",
    },
    {
        "name": "employer_ein",
        "description": "Employer identification number (box b)",
        "type": "identifier",
    },
    {
        "name": "wages_box1",
        "description": "Box 1 wages, tips, other compensation",
        "type": "currency",
        "required": True,
    },
    {
        "name": "federal_tax_withheld",
        "description": "Box 2 federal income tax withheld",
        "type": "currency",
        "validation": [
            {
                "kind": "cross_field",
                "expr": "wages_box1 >= federal_tax_withheld",
                "message": "Withholding exceeds wages",
            }
        ],
    },
    {
        "name": "social_security_wages",
        "description": "Box 3 social security wages",
        "type": "currency",
    },
]
PAYSTUB_FIELDS = [
    {
        "name": "employee_name",
        "description": "Employee name",
        "type": "string",
        "required": True,
        "match_mode": "fuzzy",
    },
    {
        "name": "employer_name",
        "description": "Employer / company name",
        "type": "string",
        "match_mode": "fuzzy",
    },
    {"name": "pay_date", "description": "Pay date", "type": "date"},
    {
        "name": "gross_pay",
        "description": "Gross pay for the period",
        "type": "currency",
        "required": True,
    },
    {
        "name": "net_pay",
        "description": "Net pay for the period",
        "type": "currency",
        "required": True,
        "validation": [
            {
                "kind": "cross_field",
                "expr": "gross_pay >= net_pay",
                "message": "Net pay exceeds gross pay",
            }
        ],
    },
]
SUBPOENA_FIELDS = [
    {
        "name": "case_number",
        "description": "Civil action / case number",
        "type": "identifier",
        "required": True,
    },
    {"name": "plaintiff", "description": "Plaintiff name", "type": "string", "match_mode": "fuzzy"},
    {"name": "defendant", "description": "Defendant name", "type": "string", "match_mode": "fuzzy"},
    {"name": "production_date", "description": "Date documents must be produced", "type": "date"},
]
NOTE_FIELDS = [
    {
        "name": "borrower_name",
        "description": "Borrower's name",
        "type": "string",
        "required": True,
        "match_mode": "fuzzy",
    },
    {
        "name": "lender_name",
        "description": "Lender's name",
        "type": "string",
        "match_mode": "fuzzy",
    },
    {
        "name": "principal_amount",
        "description": "Principal amount",
        "type": "currency",
        "required": True,
    },
    {"name": "interest_rate", "description": "Annual interest rate percent", "type": "percent"},
    {"name": "maturity_date", "description": "Maturity date", "type": "date"},
]
STATEMENT_FIELDS = [
    {
        "name": "account_holder",
        "description": "Account holder name",
        "type": "string",
        "match_mode": "fuzzy",
    },
    {
        "name": "beginning_balance",
        "description": "Beginning balance",
        "type": "currency",
        "required": True,
    },
    {
        "name": "ending_balance",
        "description": "Ending balance",
        "type": "currency",
        "required": True,
    },
]
CATEGORIES = [
    {
        "key": "w2",
        "name": "Form W-2",
        "description": "IRS Wage and Tax Statement issued by an employer.",
        "distinguishing_evidence": "'Form W-2', 'Wage and Tax Statement', boxes a-e, box 1 wages",
        "aliases": ["W2", "wage statement"],
        "extraction_schema": "w2",
    },
    {
        "key": "paystub",
        "name": "Pay stub",
        "description": "Employee earnings statement for a pay period.",
        "distinguishing_evidence": "'Earnings Statement', 'Pay Period', 'Net Pay', 'Gross Pay'",
        "aliases": ["earnings statement"],
        "extraction_schema": "paystub",
    },
    {
        "key": "subpoena",
        "name": "Subpoena",
        "description": "Court order to produce documents or testify.",
        "distinguishing_evidence": "'SUBPOENA', 'YOU ARE COMMANDED', court caption, civil action number",
        "continuation_characteristics": "Rule 45 text pages without a caption",
        "extraction_schema": "subpoena",
    },
    {
        "key": "promissory_note",
        "name": "Promissory note",
        "description": "Borrower's written promise to repay a lender.",
        "distinguishing_evidence": "'PROMISSORY NOTE', 'promises to pay', principal, maturity",
        "extraction_schema": "promissory_note",
    },
    {
        "key": "bank_statement",
        "name": "Bank statement",
        "description": "Periodic account activity statement.",
        "distinguishing_evidence": "'Statement Period', 'Beginning Balance', 'Ending Balance'",
        "extraction_schema": "bank_statement",
    },
]
SCHEMAS = [
    {"name": "w2", "fields": W2_FIELDS},
    {"name": "paystub", "fields": PAYSTUB_FIELDS},
    {"name": "subpoena", "fields": SUBPOENA_FIELDS},
    {"name": "promissory_note", "fields": NOTE_FIELDS},
    {"name": "bank_statement", "fields": STATEMENT_FIELDS},
]
ROUTING = [
    {"when": {"validation_failed": True}, "outcome": "human_review"},
    {"when": {"missing_grounding": True}, "outcome": "human_review"},
    {"when": {"min_score": 0.85}, "outcome": "auto_accept"},
]


def sample_workflow_configs():
    return {
        "unbundle-classify-extract": (
            "unbundle_classify_extract",
            {
                "categories": CATEGORIES,
                "schemas": SCHEMAS,
                "segmentation": {},
                "other_behavior": "needs_review",
                "chunking": {"strategy": "whole_document", "fallback": "context_length"},
                "routing": ROUTING,
                "model": {
                    "adapter": "azure_openai",
                    "deployment": settings.DOCAI["AZURE_OPENAI_DEPLOYMENT"],
                    "temperature": 0.0,
                },
            },
        ),
        "classify-structured-rules": (
            "classify_structured",
            {
                "rules": [
                    {
                        "category": "w2",
                        "required": [{"pattern": "Form W-2", "kind": "form_id", "weight": 2}],
                        "optional": [
                            {"pattern": "Wage and Tax Statement", "kind": "phrase"},
                            {"pattern": r"\b\d{3}-\d{2}-\d{4}\b", "kind": "identifier_format"},
                        ],
                        "exclusions": [{"pattern": "1099", "kind": "phrase"}],
                        "threshold": 2,
                    },
                    {
                        "category": "subpoena",
                        "required": [{"pattern": "SUBPOENA", "kind": "phrase", "weight": 2}],
                        "optional": [
                            {"pattern": "YOU ARE COMMANDED", "kind": "phrase"},
                            {"pattern": r"Civil Action No\.", "kind": "regex"},
                        ],
                        "threshold": 2,
                    },
                    {
                        "category": "paystub",
                        "required": [
                            {
                                "pattern": "Earnings Statement",
                                "kind": "phrase",
                                "group": "title",
                                "weight": 2,
                            },
                            {
                                "pattern": "Pay Stub",
                                "kind": "phrase",
                                "group": "title",
                                "weight": 2,
                            },
                        ],
                        "optional": [{"pattern": "Net Pay", "kind": "phrase"}],
                        "threshold": 2,
                    },
                    {
                        "category": "promissory_note",
                        "required": [
                            {"pattern": "PROMISSORY NOTE", "kind": "exact_title", "weight": 2}
                        ],
                        "threshold": 2,
                    },
                    {
                        "category": "bank_statement",
                        "required": [
                            {"pattern": "Statement Period", "kind": "phrase", "weight": 2}
                        ],
                        "optional": [{"pattern": "Ending Balance", "kind": "phrase"}],
                        "threshold": 2,
                    },
                ],
                "use_llm_fallback": True,
                "categories": CATEGORIES,
                "routing": ROUTING,
            },
        ),
        "extract-w2-unstructured": (
            "extract_unstructured",
            {
                "schema": {"name": "w2", "fields": W2_FIELDS},
                "document_type": "w2",
                "chunking": {"strategy": "page"},
                "reconciliation": {"policy": "highest_score"},
                "routing": ROUTING,
            },
        ),
        "extract-generic-default": ("extract_structured", {"mode": "default", "routing": ROUTING}),
    }


class Command(BaseCommand):
    help = "Seed RBAC groups, default prompts, and a sample project (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--admin-password",
            default=None,
            help="Create/update local superuser 'admin' with this password.",
        )
        parser.add_argument("--no-sample", action="store_true")

    def handle(self, *args, **opts):
        for g in ("docai_viewers", "docai_operators", "docai_reviewers", "docai_approvers"):
            Group.objects.get_or_create(name=g)
        admin = None
        if opts["admin_password"]:
            admin, _ = User.objects.get_or_create(
                username="admin", defaults={"is_superuser": True, "is_staff": True}
            )
            admin.is_superuser = admin.is_staff = True
            admin.set_password(opts["admin_password"])
            admin.save()
            self.stdout.write("superuser 'admin' ready")
        prompts = governance.ensure_default_prompts(admin)
        self.stdout.write(
            f"prompts: {', '.join(f'{p.name}@{p.version}' for p in prompts.values())}"
        )
        if not opts["no_sample"]:
            project, _ = Project.available_objects.get_or_create(
                slug="sample-banking-docs",
                defaults={
                    "name": "Sample banking documents",
                    "description": "Synthetic W-2, pay stubs, subpoenas, notes, statements.",
                    "created_by": admin,
                },
            )
            for name, (wt, cfg) in sample_workflow_configs().items():
                if not project.workflows.filter(name=name).exists():
                    wf = governance.create_workflow_version(project, name, wt, cfg, admin)
                    self.stdout.write(
                        f"workflow {wf.name} v{wf.version} [{wt}] hash={wf.content_hash[:19]}…"
                    )
            self.stdout.write(f"project '{project.name}' ready ({project.id})")
        self.stdout.write(self.style.SUCCESS("seed complete"))
