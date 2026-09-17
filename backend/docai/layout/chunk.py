"""Chunking strategies over preserved unit texts. Every chunk carries the unit
indexes it covers and a continuation prefix (overlap) so context is not lost.
The strategy actually used is recorded; a fallback is applied only when
explicitly configured and is reported, never silent."""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from docai.exceptions import ContextLimitExceeded
from docai.schemas.config import ChunkingConfig

from .preserve import UNIT_SEP


@dataclass
class Chunk:
    index: int
    text: str
    unit_indexes: list[int]
    strategy: str
    continuation: bool = False
    meta: dict = field(default_factory=dict)


@dataclass
class ChunkPlan:
    chunks: list[Chunk]
    strategy_used: str
    fallback_used: str | None = None
    total_chars: int = 0


def plan_chunks(
    unit_texts: list[str],
    cfg: ChunkingConfig,
    *,
    unit_kind: str = "page",
    excluded_unit_indexes: set[int] | None = None,
    prompt_overhead_chars: int = 0,
) -> ChunkPlan:
    indexes = [i for i in range(len(unit_texts)) if i not in (excluded_unit_indexes or set())]
    unit_texts = [unit_texts[i] for i in indexes]
    if not unit_texts:
        return ChunkPlan(chunks=[], strategy_used=cfg.strategy)
    total = len(UNIT_SEP.join(unit_texts))
    budget = cfg.max_request_chars - prompt_overhead_chars
    if budget <= 0:
        raise ContextLimitExceeded(errors={"reason": "Instructions exceed request budget"})
    strat = cfg.strategy
    fallback = None
    if strat == "whole_document" and total > cfg.whole_document_max_chars:
        if not cfg.fallback:
            raise ContextLimitExceeded(errors={"chars": total, "max": cfg.whole_document_max_chars})
        fallback = f"whole_document→{cfg.fallback} (document {total} chars > {cfg.whole_document_max_chars})"
        strat = cfg.fallback

    if (strat == "sheet" and unit_kind != "sheet") or (strat == "page" and unit_kind != "page"):
        raise ContextLimitExceeded(
            errors={"reason": "Chunk strategy does not match document format"}
        )
    size = min(cfg.chunk_chars, budget)
    if strat in ("context_length", "semantic") and cfg.overlap_chars >= size:
        raise ContextLimitExceeded(errors={"reason": "Overlap leaves no room for new content"})
    chunks: list[Chunk] = []
    if strat == "whole_document":
        chunks.append(Chunk(0, UNIT_SEP.join(unit_texts), list(range(len(unit_texts))), strat))
    elif strat in ("page", "sheet"):
        for i, t in enumerate(unit_texts):
            chunks.append(Chunk(i, t, [i], strat))
    elif strat == "context_length":
        chunks = _context_length(unit_texts, size, cfg.overlap_chars, strat)
    elif strat == "semantic":
        # Prefer paragraph/heading boundaries; dense sections still obey the budget.
        chunks = _semantic(unit_texts, size, cfg.overlap_chars, strat)
    else:
        raise ValueError(strat)
    for chunk in chunks:
        if len(chunk.text) > budget:
            raise ContextLimitExceeded(
                errors={
                    "chars": len(chunk.text) + prompt_overhead_chars,
                    "max": cfg.max_request_chars,
                }
            )
        chunk.meta["prompt_overhead_chars"] = prompt_overhead_chars
        chunk.unit_indexes = [indexes[i] for i in chunk.unit_indexes]
    logger.bind(
        event="chunking_completed",
        chunks=len(chunks),
        strategy=strat,
        chars=total,
        fallback=fallback,
    ).info("Chunking completed")
    return ChunkPlan(chunks=chunks, strategy_used=strat, fallback_used=fallback, total_chars=total)


def _tag_unit(text: str, original: str) -> str:
    header = original.partition("\n")[0]
    if header.startswith("===") and not text.startswith(header):
        return header + "\n" + text
    return text


def _tail(parts: list[tuple[int, str]], count: int, originals: list[str]) -> list[tuple[int, str]]:
    """Carry a bounded suffix with the original page identity, including header cost."""
    tail: list[tuple[int, str]] = []
    remaining = count
    for index, text in reversed(parts):
        header = originals[index].partition("\n")[0]
        prefix = header + "\n" if header.startswith("===") else ""
        available = remaining - (1 if tail else 0)
        if available <= len(prefix):
            break
        fragment = text[-(available - len(prefix)) :]
        tagged = _tag_unit(fragment, originals[index])
        tail.insert(0, (index, tagged))
        remaining -= len(tagged) + (1 if len(tail) > 1 else 0)
        if remaining <= 0:
            break
    return tail


def _split_at(text: str, budget: int) -> int:
    """Prefer a line boundary; never sever an inline source marker when it can fit."""
    if len(text) <= budget:
        return len(text)
    newline = text.rfind("\n", 0, budget)
    cut = newline + 1 if newline >= budget // 2 else budget
    opening = text.rfind("[", 0, cut)
    if opening >= 0 and "]" not in text[opening:cut] and opening > 0:
        cut = opening
    return cut


def _pack(
    blocks: list[tuple[int, str]], originals: list[str], size: int, overlap: int, strat: str
) -> list[Chunk]:
    chunks: list[Chunk] = []
    parts: list[tuple[int, str]] = []
    overlap_length = 0
    has_new_content = False

    def flush() -> None:
        nonlocal parts, overlap_length, has_new_content
        text = UNIT_SEP.join(part for _, part in parts)
        chunks.append(
            Chunk(
                len(chunks),
                text,
                sorted({index for index, _ in parts}),
                strat,
                continuation=bool(overlap_length),
                meta={"overlap_chars": overlap_length},
            )
        )
        parts = _tail(parts, overlap, originals)
        overlap_length = len(UNIT_SEP.join(part for _, part in parts))
        has_new_content = False

    for index, block in blocks:
        while block:
            tagged = _tag_unit(block, originals[index])
            used = sum(len(part) for _, part in parts) + max(0, len(parts) - 1)
            available = size - used - bool(parts)
            # Prefer intact sections/pages, but split a section larger than a fresh window.
            fresh_capacity = size - overlap - 1
            if has_new_content and len(tagged) > available and len(tagged) <= fresh_capacity:
                flush()
                continue
            header_length = len(tagged) - len(block)
            if available <= header_length:
                if has_new_content:
                    flush()
                    continue
                # Very long headers or an aggressive overlap cannot consume the whole window.
                if parts:
                    parts, overlap_length = [], 0
                    continue
                raise ContextLimitExceeded(errors={"reason": "Page header exceeds chunk budget"})
            cut = _split_at(block, available - header_length)
            parts.append((index, _tag_unit(block[:cut], originals[index])))
            has_new_content = True
            block = block[cut:]
            if block:
                flush()
    if has_new_content:
        flush()
    return chunks


def _context_length(unit_texts: list[str], size: int, overlap: int, strat: str) -> list[Chunk]:
    return _pack(list(enumerate(unit_texts)), unit_texts, size, overlap, strat)


def _semantic(unit_texts: list[str], size: int, overlap: int, strat: str) -> list[Chunk]:
    # Heading/paragraph grouping is deterministic, not semantic model inference.
    blocks: list[tuple[int, str]] = []
    for index, text in enumerate(unit_texts):
        current: list[str] = []
        for line in text.split("\n"):
            boundary = line.startswith(("<title>", "<sectionHeading>", "===")) or not line.strip()
            if boundary and current:
                blocks.append((index, "\n".join(current)))
                current = []
            if line.strip():
                current.append(line)
        if current:
            blocks.append((index, "\n".join(current)))
    return _pack(blocks, unit_texts, size, overlap, strat)
