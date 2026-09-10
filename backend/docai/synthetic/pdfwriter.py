"""Minimal PDF writer for SYNTHETIC test documents. Hand-rolled on purpose:
the platform's only PDF library is pypdf (which cannot create PDFs), and we
will not introduce another. Output is a valid PDF 1.4 with one Helvetica text
stream per page; pypdf extracts text with positions from it."""
from __future__ import annotations

PAGE_W, PAGE_H = 612, 792


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _content(lines: list[str], size: int = 11, leading: int = 15) -> bytes:
    ops = [f"BT /F1 {size} Tf 72 {PAGE_H - 72} Td"]
    for i, line in enumerate(lines):
        if i:
            ops.append(f"0 -{leading} Td")
        ops.append(f"({_esc(line)}) Tj")
    ops.append("ET")
    return "\n".join(ops).encode("latin-1", "replace")


def write_pdf(pages: list[list[str]]) -> bytes:
    objs: list[bytes] = []
    n_pages = len(pages)
    # object numbering: 1 catalog, 2 pages, 3 font, then per page: page obj, content obj
    page_ids = [4 + 2 * i for i in range(n_pages)]
    objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n_pages} >>".encode())
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for i, lines in enumerate(pages):
        cid = page_ids[i] + 1
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                    f"/Resources << /Font << /F1 3 0 R >> >> /Contents {cid} 0 R >>".encode())
        stream = _content(lines)
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
