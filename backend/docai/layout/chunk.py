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
) -> ChunkPlan:
    indexes = [i for i in range(len(unit_texts)) if i not in (excluded_unit_indexes or set())]
    unit_texts = [unit_texts[i] for i in indexes]
    if not unit_texts:
        return ChunkPlan(chunks=[], strategy_used=cfg.strategy)
    total = sum(len(t) + 1 for t in unit_texts)
    strat = cfg.strategy
    fallback = None
    if strat == "whole_document" and total > cfg.whole_document_max_chars:
        if not cfg.fallback:
            raise ContextLimitExceeded(errors={"chars": total, "max": cfg.whole_document_max_chars})
        fallback = f"whole_document→{cfg.fallback} (document {total} chars > {cfg.whole_document_max_chars})"
        strat = cfg.fallback

    chunks: list[Chunk] = []
    if strat == "whole_document":
        chunks.append(Chunk(0, UNIT_SEP.join(unit_texts), list(range(len(unit_texts))), strat))
    elif strat in ("page", "sheet"):
        for i, t in enumerate(unit_texts):
            chunks.append(Chunk(i, t, [i], strat))
    elif strat == "context_length":
        chunks = _context_length(unit_texts, cfg.chunk_chars, cfg.overlap_chars, strat)
    elif strat == "semantic":
        # paragraph/section-boundary aware windows (no embeddings): break only at
        # blank lines, headings (<title>/<sectionHeading>), or unit boundaries.
        chunks = _semantic(unit_texts, cfg.chunk_chars, cfg.overlap_chars, strat)
    else:
        raise ValueError(strat)
    for chunk in chunks:
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


def _overlap(
    buffer: str, ends: list[tuple[int, int]], count: int, originals: list[str]
) -> tuple[str, list[int]]:
    """Carry original identity with every fragment retained as overlap."""
    if not count:
        return "", []
    start, previous = max(0, len(buffer) - count), 0
    parts, indexes = [], []
    for index, end in ends:
        if end > start:
            parts.append(_tag_unit(buffer[max(start, previous) : end], originals[index]))
            indexes.append(index)
        previous = end
    return UNIT_SEP.join(parts), indexes


def _context_length(unit_texts: list[str], size: int, overlap: int, strat: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    buf = ""
    units: list[int] = []
    prev_tail = ""
    prev_units: list[int] = []
    ends: list[tuple[int, int]] = []
    idx = 0
    for i, t in enumerate(unit_texts):
        pieces = [t[j : j + size] for j in range(0, max(len(t), 1), size)] or [""]
        for piece in pieces:
            piece = _tag_unit(piece, t)
            if buf and len(buf) + len(piece) + 1 > size:
                chunks.append(
                    Chunk(
                        idx,
                        (prev_tail + UNIT_SEP if prev_tail else "") + buf,
                        sorted(set(prev_units + units)),
                        strat,
                        continuation=bool(prev_tail),
                        meta={"overlap_chars": len(prev_tail)},
                    )
                )
                prev_tail, prev_units = _overlap(buf, ends, overlap, unit_texts)
                ends = []
                buf, units, idx = "", [], idx + 1
            buf = (buf + UNIT_SEP + piece) if buf else piece
            units.append(i)
            ends.append((i, len(buf)))
    if buf or not chunks:
        chunks.append(
            Chunk(
                idx,
                (prev_tail + UNIT_SEP if prev_tail else "") + buf,
                sorted(set(prev_units + units)),
                strat,
                continuation=bool(prev_tail),
                meta={"overlap_chars": len(prev_tail)},
            )
        )
    return chunks


def _semantic(unit_texts: list[str], size: int, overlap: int, strat: str) -> list[Chunk]:
    # split each unit into blocks at blank lines / headings, then pack blocks
    blocks: list[tuple[int, str]] = []
    for i, t in enumerate(unit_texts):
        cur: list[str] = []
        for line in t.split("\n"):
            is_heading = (
                line.startswith("<title>")
                or line.startswith("<sectionHeading>")
                or line.startswith("===")
            )
            if (is_heading or not line.strip()) and cur:
                blocks.append((i, "\n".join(cur)))
                cur = []
            if line.strip():
                cur.append(line)
        if cur:
            blocks.append((i, "\n".join(cur)))
    chunks: list[Chunk] = []
    buf = ""
    units: list[int] = []
    idx = 0
    prev_tail = ""
    prev_units: list[int] = []
    ends: list[tuple[int, int]] = []
    for i, b in blocks:
        b = _tag_unit(b, unit_texts[i])
        if buf and len(buf) + len(b) + 1 > size:
            chunks.append(
                Chunk(
                    idx,
                    (prev_tail + "\n" if prev_tail else "") + buf,
                    sorted(set(prev_units + units)),
                    strat,
                    continuation=bool(prev_tail),
                )
            )
            prev_tail, prev_units = _overlap(buf, ends, overlap, unit_texts)
            ends = []
            buf, units, idx = "", [], idx + 1
        buf = (buf + "\n\n" + b) if buf else b
        units.append(i)
        ends.append((i, len(buf)))
    if buf or not chunks:
        chunks.append(
            Chunk(
                idx,
                (prev_tail + "\n" if prev_tail else "") + buf,
                sorted(set(prev_units + units)),
                strat,
                continuation=bool(prev_tail),
            )
        )
    return chunks
