"""Clearly-labeled SYNTHETIC banking documents + their ground truth. All names,
numbers and identifiers are fabricated; every document is watermarked
'SYNTHETIC TEST DOCUMENT'. Deterministic under a seed."""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from .pdfwriter import write_pdf

FIRST = ["Maria", "James", "Priya", "Daniel", "Aisha", "Robert", "Chen", "Elena", "Marcus", "Sofia"]
LAST = ["Alvarez", "Okafor", "Nguyen", "Kowalski", "Patel", "Brennan", "Haddad", "Silva", "Lindqvist", "Moreau"]
EMPLOYERS = ["Allegheny Fabrication Inc", "Three Rivers Logistics LLC", "Keystone Health Partners", "Monongahela Software Co"]
STREETS = ["Oak St", "Ridge Ave", "Mill Rd", "Harbor Blvd", "Cedar Ln"]


@dataclass
class SynthDoc:
    filename: str
    data: bytes
    category: str
    fields: dict[str, str | None]                         # truth (None = absent)
    segments: list[dict] = field(default_factory=list)     # for packages: [{start,end,category}]
    kind: str = "pdf"


def _ssn(r):
    return f"{r.randint(100, 899):03d}-{r.randint(10, 99):02d}-{r.randint(1000, 9999):04d}"


def _ein(r):
    return f"{r.randint(10, 99):02d}-{r.randint(1000000, 9999999):07d}"


def _money(r, lo, hi):
    return f"{r.uniform(lo, hi):,.2f}"


def w2_pages(r, truth):
    name, ssn, emp, ein, wages, fed, ss_w = (truth[k] for k in ("employee_name", "employee_ssn", "employer_name", "employer_ein",
                                                                "wages_box1", "federal_tax_withheld", "social_security_wages"))
    return [[
        "SYNTHETIC TEST DOCUMENT - NOT A REAL TAX FORM",
        "Form W-2 Wage and Tax Statement 2025",
        "a Employee's social security number", ssn,
        "b Employer identification number (EIN)", ein,
        "c Employer's name, address, and ZIP code", emp, f"{r.randint(100, 999)} {r.choice(STREETS)}, Pittsburgh, PA 152{r.randint(10, 99)}",
        "e Employee's first name and initial   Last name", name,
        "1 Wages, tips, other compensation", wages,
        "2 Federal income tax withheld", fed,
        "3 Social security wages", ss_w,
        "4 Social security tax withheld", _money(r, 1000, 5000),
        "5 Medicare wages and tips", ss_w,
        "Copy B - To Be Filed With Employee's FEDERAL Tax Return.",
    ]]


def paystub_pages(r, truth):
    return [[
        "SYNTHETIC TEST DOCUMENT",
        f"{truth['employer_name']}   Earnings Statement / Pay Stub",
        f"Employee: {truth['employee_name']}",
        f"Pay Period: {truth['pay_period_start']} - {truth['pay_period_end']}",
        f"Pay Date: {truth['pay_date']}",
        "Earnings   Hours   Rate   Current",
        f"Regular   80.00   {r.uniform(18, 60):.2f}   {truth['gross_pay']}",
        f"Gross Pay: {truth['gross_pay']}",
        f"Federal Tax: {_money(r, 100, 900)}",
        f"Net Pay: {truth['net_pay']}",
    ]]


def subpoena_pages(r, truth):
    return [[
        "SYNTHETIC TEST DOCUMENT",
        "UNITED STATES DISTRICT COURT",
        "WESTERN DISTRICT OF PENNSYLVANIA",
        f"{truth['plaintiff']}, Plaintiff, v. {truth['defendant']}, Defendant.",
        f"Civil Action No. {truth['case_number']}",
        "SUBPOENA TO PRODUCE DOCUMENTS, INFORMATION, OR OBJECTS",
        f"To: {truth['recipient']}",
        "YOU ARE COMMANDED to produce at the time, date, and place set forth below",
        "the following documents: all account statements for the period listed.",
        f"Date and Time: {truth['production_date']} 9:00 AM",
    ], [
        "SYNTHETIC TEST DOCUMENT",
        "Federal Rule of Civil Procedure 45 (c), (d), (e), and (g) (Effective 12/1/13)",
        "(c) Place of Compliance. (1) For a Trial, Hearing, or Deposition.",
        "A subpoena may command a person to attend a trial, hearing, or deposition only as follows:",
        "(A) within 100 miles of where the person resides, is employed, or regularly transacts business in person.",
        "(d) Protecting a Person Subject to a Subpoena; Enforcement.",
    ]]


def note_pages(r, truth):
    return [[
        "SYNTHETIC TEST DOCUMENT",
        "PROMISSORY NOTE",
        f"Principal Amount: ${truth['principal_amount']}   Date: {truth['note_date']}",
        f"FOR VALUE RECEIVED, the undersigned Borrower, {truth['borrower_name']}, promises to pay to the order of",
        f"{truth['lender_name']} (the Lender) the principal sum of ${truth['principal_amount']}",
        f"with interest at the rate of {truth['interest_rate']}% per annum.",
        f"Maturity Date: {truth['maturity_date']}",
        "Borrower signature: ______________________",
    ]]


def statement_pages(r, truth):
    lines = [
        "SYNTHETIC TEST DOCUMENT",
        "Keystone Community Bank   Account Statement",
        f"Account Holder: {truth['account_holder']}",
        f"Statement Period: {truth['statement_start']} to {truth['statement_end']}",
        f"Beginning Balance: {truth['beginning_balance']}",
        "Date   Description   Amount",
    ]
    for _ in range(6):
        lines.append(f"0{r.randint(1, 9)}/{r.randint(10, 28)}/2025   Purchase {r.choice(['Grocery', 'Fuel', 'Utility', 'Pharmacy'])}   -{_money(r, 10, 300)}")
    lines.append(f"Ending Balance: {truth['ending_balance']}")
    return [lines]


def make_docs(seed: int = 7) -> list[SynthDoc]:
    r = random.Random(seed)
    docs: list[SynthDoc] = []

    def person():
        return f"{r.choice(FIRST)} {r.choice(LAST)}"

    def w2(i):
        wages = r.uniform(30000, 140000)
        t = {"employee_name": person(), "employee_ssn": _ssn(r), "employer_name": r.choice(EMPLOYERS), "employer_ein": _ein(r),
             "wages_box1": f"{wages:,.2f}", "federal_tax_withheld": _money(r, 2000, 20000), "social_security_wages": f"{wages:,.2f}"}
        return SynthDoc(f"w2_{i:02d}.pdf", write_pdf(w2_pages(r, t)), "w2", t)

    def paystub(i):
        gross = r.uniform(1500, 6000)
        t = {"employee_name": person(), "employer_name": r.choice(EMPLOYERS), "pay_period_start": f"0{r.randint(1, 9)}/01/2025",
             "pay_period_end": f"0{r.randint(1, 9)}/15/2025", "pay_date": f"0{r.randint(1, 9)}/20/2025",
             "gross_pay": f"{gross:,.2f}", "net_pay": f"{gross * 0.74:,.2f}"}
        return SynthDoc(f"paystub_{i:02d}.pdf", write_pdf(paystub_pages(r, t)), "paystub", t)

    def subpoena(i):
        t = {"plaintiff": f"{r.choice(LAST)} Holdings LLC", "defendant": person(), "case_number": f"2:25-cv-{r.randint(1000, 9999)}",
             "recipient": "Keystone Community Bank, Records Custodian", "production_date": f"1{r.randint(0, 2)}/{r.randint(10, 28)}/2025"}
        return SynthDoc(f"subpoena_{i:02d}.pdf", write_pdf(subpoena_pages(r, t)), "subpoena", t)

    def note(i):
        t = {"borrower_name": person(), "lender_name": "Keystone Community Bank", "principal_amount": _money(r, 5000, 250000),
             "interest_rate": f"{r.uniform(4, 11):.2f}", "note_date": f"0{r.randint(1, 9)}/1{r.randint(0, 9)}/2025",
             "maturity_date": f"0{r.randint(1, 9)}/1{r.randint(0, 9)}/2030"}
        return SynthDoc(f"promissory_note_{i:02d}.pdf", write_pdf(note_pages(r, t)), "promissory_note", t)

    def statement(i):
        b = r.uniform(500, 20000)
        t = {"account_holder": person(), "statement_start": f"0{r.randint(1, 9)}/01/2025", "statement_end": f"0{r.randint(1, 9)}/30/2025",
             "beginning_balance": f"{b:,.2f}", "ending_balance": f"{b - r.uniform(100, 900):,.2f}"}
        return SynthDoc(f"bank_statement_{i:02d}.pdf", write_pdf(statement_pages(r, t)), "bank_statement", t)

    for i in range(1, 5):
        docs.append(w2(i))
    for i in range(1, 4):
        docs.append(paystub(i))
    for i in range(1, 4):
        docs.append(subpoena(i))
    for i in range(1, 3):
        docs.append(note(i))
    for i in range(1, 3):
        docs.append(statement(i))

    # packages: several documents scanned into one file (for unbundling)
    for i in range(1, 3):
        parts = [w2(90 + i), subpoena(90 + i), paystub(90 + i)]
        pages, segs, start = [], [], 0
        for p in parts:
            src = {"w2": w2_pages, "subpoena": subpoena_pages, "paystub": paystub_pages}[p.category]
            ppages = src(random.Random(seed + i + len(pages)), p.fields)
            pages += ppages
            segs.append({"start": start, "end": start + len(ppages) - 1, "category": p.category, "fields": p.fields})
            start += len(ppages)
        docs.append(SynthDoc(f"package_{i:02d}.pdf", write_pdf(pages), "package",
                             fields={}, segments=segs))
    return docs


def make_workbook() -> tuple[bytes, dict]:
    from io import BytesIO

    from openpyxl import Workbook
    wb = Workbook(); ws = wb.active; ws.title = "Balance Sheet"
    ws["A1"] = "SYNTHETIC TEST WORKBOOK"; ws.merge_cells("A1:C1")
    ws.append(["Line item", "FY2024", "FY2025"])
    ws.append(["Cash and equivalents", 125000.5, 143210.75])
    ws.append(["Accounts receivable", 88000, 91500])
    ws.append(["Total current assets", "=B3+B4", "=C3+C4"])
    ws2 = wb.create_sheet("Notes"); ws2["A1"] = "Prepared by: Synthetic Finance Team"; ws2["A2"] = "Company: Monongahela Software Co"
    buf = BytesIO(); wb.save(buf)
    truth = {"cash_fy2025": "143210.75", "receivables_fy2025": "91500", "company_name": "Monongahela Software Co"}
    return buf.getvalue(), truth


def make_text() -> tuple[bytes, dict]:
    text = ("SYNTHETIC TEST DOCUMENT\nInvoice\nInvoice Number: INV-4821\nBill To: Three Rivers Logistics LLC\n"
            "Invoice Date: 03/04/2025\nAmount Due: $4,250.00\nDue Date: 04/03/2025\n")
    return text.encode("utf-8"), {"invoice_number": "INV-4821", "amount_due": "4,250.00", "invoice_date": "03/04/2025"}
