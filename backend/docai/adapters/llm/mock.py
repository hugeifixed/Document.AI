"""Deterministic, keyless StructuredLLM used for local runs and tests. It
NEVER reads the prompt for instructions; it answers from `mock_context`
(document text + requested schema fields/categories) with regex heuristics,
then validates the result through the same Pydantic schema a real model must
satisfy. Ported from the prototype's mock provider."""

from __future__ import annotations

import json
import re
import time

from pydantic import BaseModel, ValidationError

from docai.exceptions import InvalidModelOutput
from docai.schemas.llm import (
    ClassificationOut,
    ExtractionOut,
    FieldOut,
    GenericKVOut,
    SegmentationOut,
    SegmentOut,
    SourceRef,
    StructuredResult,
)

from .base import LLMCall

SSN_RE = re.compile(r"\b(\d{3})-(\d{2})-(\d{4})\b")
EIN_RE = re.compile(r"\b(\d{2})-(\d{7})\b")
MONEY_RE = re.compile(r"\$?\s?(\d{1,3}(?:,\d{3})+(?:\.\d{2})?|\d+\.\d{2})")
DATE_RE = re.compile(r"\b(\d{1,2}/\d{1,2}/\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Z][a-z]+ \d{1,2}, \d{4})\b")

KEYWORDS = {
    "w2": ["form w-2", "wage and tax statement", "social security wages"],
    "form_1099_nec": ["1099-nec", "nonemployee compensation"],
    "paystub": ["pay stub", "earnings statement", "net pay", "pay period"],
    "subpoena": ["subpoena", "you are commanded", "district court"],
    "wage_garnishment": ["garnishment", "writ of execution", "garnishee"],
    "bank_statement": ["statement period", "beginning balance", "ending balance"],
    "promissory_note": ["promissory note", "promise to pay"],
    "invoice": ["invoice", "amount due", "bill to"],
    "schedule_k1_1065": ["schedule k-1", "partner's share"],
    "loan_agreement": ["loan agreement", "borrower", "lender"],
}


class MockStructuredLLM:
    key = "mock"

    def __init__(self, deployment: str = "mock-deterministic-v1"):
        self.deployment = deployment

    # ---------------------------------------------------------------- helpers
    @staticmethod
    def classify_text(text: str, candidates: list[str]) -> tuple[str, float, str]:
        low = text.lower()
        best, best_n, best_kw = "other", 0, ""
        for cat in candidates:
            kws = KEYWORDS.get(cat, [cat.replace("_", " ")])
            n = sum(1 for k in kws if k in low)
            if n > best_n:
                best, best_n, best_kw = cat, n, next(k for k in kws if k in low)
        conf = min(0.55 + 0.2 * best_n, 0.95) if best != "other" else 0.2
        return best, conf, best_kw

    @staticmethod
    def _after_label(labels, text):
        for lab in labels:
            m = re.search(re.escape(lab) + r"[:\s]+([A-Z][A-Za-z .'-]{2,40})", text)
            if not m:
                m = re.search(re.escape(lab) + r"[^\n]*\n\s*([A-Z][A-Za-z .'-]{2,40})", text)
            if m:
                return m.group(1).strip()
        return None

    @staticmethod
    def _labeled_money(labels, text):
        for lab in labels:
            m = re.search(
                re.escape(lab) + r"[^\n$\d]{0,40}\$?\s?(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)", text, re.I
            )
            if m:
                return m.group(1)
        return None

    _STOP = {"the", "a", "an", "of", "for", "and", "or", "to", "in", "on", "box", "per", "full"}

    @classmethod
    def _label_words(cls, desc: str) -> list[str]:
        d = re.sub(r"\(.*?\)", " ", desc.lower())
        d = re.sub(r"\bbox\s*[a-z0-9]+\b", " ", d)
        return [
            w.strip("'s")
            for w in re.findall(r"[a-z][a-z']+", d)
            if len(w) > 2 and w not in cls._STOP
        ]

    @staticmethod
    def _clean(line: str) -> str:
        return re.sub(r"\s*\[[^\]]*\]\s*$", "", line).strip()  # drop trailing source-id brackets

    def _find_label_line(self, lines: list[str], desc: str, name: str):
        """Best line for a field: fraction of description/name words present, with a
        bonus when the first two words appear as a contiguous phrase (breaks ties
        like 'Pay Period' vs 'Gross Pay')."""
        candidates = [
            w
            for w in (
                self._label_words(desc),
                [w for w in name.lower().split("_") if w not in self._STOP],
            )
            if w
        ]
        best, best_score, best_words = None, 0.0, candidates[0] if candidates else []
        for words in candidates:
            phrase = " ".join(words[:2]) if len(words) >= 2 else words[0]
            for i, ln in enumerate(lines):
                low = ln.lower()
                n = sum(1 for w in words if w in low)
                score = n / len(words) + (0.6 if phrase in low else 0.0)
                if score > best_score:
                    best, best_score, best_words = i, score, words
        if best is not None and best_score >= 0.5:
            return best, best_words
        return None, best_words

    @staticmethod
    def _parse_typed(window: str, ftype: str, key: str):
        if "ssn" in key or "social security number" in key:
            m = SSN_RE.search(window)
            return m.group(0) if m else None
        if "ein" in key or "employer identification" in key:
            m = EIN_RE.search(window)
            return m.group(0) if m else None
        if ftype in ("currency", "number", "integer"):
            m = MONEY_RE.search(window)
            return m.group(1) if m else None
        if ftype == "percent":
            m = re.search(r"(\d+(?:\.\d+)?)\s*%", window)
            return m.group(1) if m else None
        if ftype == "date":
            m = DATE_RE.search(window)
            return m.group(1) if m else None
        if ftype == "identifier":
            m = re.search(r"\b(\d[\w:-]{3,}|[A-Z]{2,}-\d[\w-]*)\b", window)
            return m.group(1) if m else None
        return None

    def extract_fields(
        self, text: str, fields: list[dict], unit_indexes: list[int] | None = None
    ) -> list[FieldOut]:
        lines = [self._clean(l) for l in text.split("\n")]
        out = []
        for f in fields:
            name, ftype = f["name"], f.get("type", "string")
            desc = f.get("description") or ""
            key = (name + " " + desc).lower()
            val = None
            idx, words = self._find_label_line(lines, desc, name)
            if idx is not None:
                same, nxt = lines[idx], lines[idx + 1] if idx + 1 < len(lines) else ""
                if ftype in ("string",):
                    # value follows the label on the same line (after ':' or the last label word), else next line
                    low = same.lower()
                    cut = same.find(":")
                    if cut < 0:
                        last = max((low.rfind(w) + len(w) for w in words if w in low), default=-1)
                        cut = last if last > 0 else -1
                    rest = same[cut + 1 :].strip(" :,-") if cut >= 0 else ""
                    rest = re.split(r"\s{2,}|,\s(?=[A-Z][a-z]+ *,)|\s(?:v\.|vs\.)\s|\s\(", rest)[
                        0
                    ].strip(" .,")
                    if len(rest) < 3 or not re.search(r"[A-Za-z]", rest) or not rest[0].isupper():
                        rest = re.split(r"\s{2,}", nxt)[0].strip(
                            " .,"
                        )  # value sits on the line below the label
                    if "plaintiff" in key:
                        m = re.search(r"([A-Z][^\n,]{2,60}?),\s*Plaintiff", text)
                        rest = m.group(1) if m else rest
                    elif "defendant" in key:
                        m = re.search(r"v\.\s*([A-Z][^\n,]{2,60}?),\s*Defendant", text)
                        rest = m.group(1) if m else rest
                    elif "borrower" in key:
                        m = re.search(r"Borrower,?\s+([A-Z][\w.'-]+(?: [A-Z][\w.'-]+){0,4})", text)
                        rest = m.group(1) if m else rest
                    elif "lender" in key:
                        m = re.search(r"([A-Z][^\n(]{2,60}?)\s*\(the Lender\)", text)
                        rest = m.group(1).strip() if m else rest
                    elif "recipient" in key:
                        m = re.search(r"To:\s*([^\n]{3,80})", text)
                        rest = m.group(1).strip() if m else rest
                    val = rest[:80] if rest else None
                else:
                    val = self._parse_typed(same + "\n" + nxt, ftype, key)
            if val is None:  # type-based global fallbacks
                if ftype != "string":
                    val = self._parse_typed(text, ftype, key)
                elif "employer" in key or "company" in key:
                    m = re.search(
                        r"^([A-Z][A-Za-z&' .-]+?(?:Inc|LLC|Co|Partners|Bank|Corp|Ltd)\.?)(?=\s{2,}|\s*$)",
                        "\n".join(lines),
                        re.M,
                    )
                    val = m.group(1).strip() if m else None
            evid = val or ""
            unit_idx = self._unit_of(text, val, unit_indexes)
            out.append(
                FieldOut(
                    name=name,
                    value=val,
                    confidence=0.93 if val else 0.0,
                    evidence=evid,
                    unit_index=unit_idx,
                    sources=[SourceRef(unit_index=unit_idx, quote=evid)] if val else [],
                )
            )
        return out

    @staticmethod
    def _unit_of(text: str, val, unit_indexes: list[int] | None = None) -> int:
        pos = text.lower().find(str(val).lower()) if val else -1
        prefix = text[:pos] if pos >= 0 else text
        headers = list(re.finditer(r"=== (?:PAGE|SHEET) [^\n]*?\(unit (\d+)[,)][^\n]*===", prefix))
        if headers:
            return int(headers[-1].group(1))
        return unit_indexes[0] if unit_indexes else 0

    # ---------------------------------------------------------------- invoke
    def invoke(self, call: LLMCall) -> StructuredResult:
        t0 = time.perf_counter()
        ctx = call.mock_context or {}
        text = ctx.get("text", "")
        schema = call.schema
        parsed: BaseModel
        try:
            if schema is SegmentationOut:
                units = ctx.get("unit_texts") or [text]
                cats = ctx.get("categories") or list(KEYWORDS)
                segs, prev = [], None
                indexes = ctx.get("unit_indexes", list(range(len(units))))
                for i, ut in zip(indexes, units, strict=True):
                    if i in ctx.get("excluded_unit_indexes", set()):
                        continue
                    cat, conf, kw = self.classify_text(ut, cats)
                    # continuation heuristic (mirrors the prompt's rule): a page that lacks
                    # its category's heading in its top lines continues the previous segment
                    top = "\n".join(ut.split("\n")[1:4]).lower()
                    title_hit = any(k in top for k in KEYWORDS.get(cat, [cat.replace("_", " ")]))
                    if prev is not None and (
                        cat == "other" or conf < 0.5 or (cat == prev and not title_hit)
                    ):
                        segs[-1].end_unit = i  # continuation
                        continue
                    segs.append(
                        SegmentOut(
                            start_unit=i,
                            end_unit=i,
                            category=cat,
                            confidence=conf,
                            evidence=kw,
                            sources=[SourceRef(unit_index=i, quote=kw)],
                        )
                    )
                    prev = cat
                parsed = SegmentationOut(segments=segs)
            elif schema is ClassificationOut:
                cats = ctx.get("categories") or list(KEYWORDS)
                cat, conf, kw = self.classify_text(text, cats)
                parsed = ClassificationOut(
                    category=cat,
                    confidence=conf,
                    evidence=kw,
                    sources=[
                        SourceRef(
                            unit_index=self._unit_of(text, kw, ctx.get("unit_indexes")), quote=kw
                        )
                    ]
                    if kw
                    else [],
                )
            elif schema is ExtractionOut:
                parsed = ExtractionOut(
                    fields=self.extract_fields(
                        text, ctx.get("fields") or [], ctx.get("unit_indexes")
                    )
                )
            elif schema is GenericKVOut:
                pairs = []
                for m in re.finditer(
                    r"^([A-Za-z][A-Za-z ,'/()-]{2,40}?):[ \t]*([^\n\f]+)", text, re.M
                ):
                    pairs.append(
                        FieldOut(
                            name=m.group(1).strip(),
                            value=m.group(2).strip()[:200],
                            confidence=0.6,
                            evidence=m.group(0)[:120],
                            unit_index=self._unit_of(
                                text[: m.start()], None, ctx.get("unit_indexes")
                            ),
                            sources=[
                                SourceRef(
                                    unit_index=self._unit_of(
                                        text[: m.start()], None, ctx.get("unit_indexes")
                                    ),
                                    quote=m.group(2)[:60],
                                )
                            ],
                        )
                    )
                parsed = GenericKVOut(pairs=pairs[:200])
            else:
                parsed = schema.model_validate(ctx.get("canned") or {})
        except ValidationError as exc:
            raise InvalidModelOutput(
                errors={"schema": schema.__name__, "detail": str(exc)[:300]}
            ) from None
        return StructuredResult(
            parsed=parsed,
            raw_response=json.dumps(parsed.model_dump(), ensure_ascii=False),
            model_deployment=self.deployment,
            parameters=dict(call.parameters),
            prompt_name=call.prompt_name,
            prompt_version=call.prompt_version,
            schema_name=call.schema_name,
            schema_version=call.schema_version,
            latency_ms=int((time.perf_counter() - t0) * 1000),
            input_chars=len(call.system) + len(call.user),
        )
