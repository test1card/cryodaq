"""Test helpers для loader fixtures.

We can't install reportlab in this env, so synthetic PDFs are
hand-crafted bytes — minimal valid PDF 1.4 with N pages, each carrying
a single Tj operator. pypdf parses these correctly; that's enough to
exercise the loader's page-level walk + metadata path without pulling
in a heavier rendering dependency.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path


def _build_minimal_pdf(page_texts: Sequence[str]) -> bytes:
    """Return bytes for a valid PDF 1.4 with one Helvetica text per page.

    The PDF structure is intentionally minimal: a single Catalog → Pages
    tree with N Page leaves, one shared Font (Helvetica), and a per-page
    Contents stream that draws the supplied text at (100, 700). pypdf's
    extract_text() returns the text token-by-token; that's all the
    loader needs to verify chunking + metadata.
    """
    if not page_texts:
        page_texts = [""]
    objects: list[bytes] = []

    def _add(obj: bytes) -> int:
        objects.append(obj)
        return len(objects)

    # Reserve indices: 1 = Catalog, 2 = Pages, 3 = Font, 4..(3+N) = Pages,
    # then Contents streams interleaved. Easier to compute as we go.
    page_count = len(page_texts)
    catalog_id = 1
    pages_id = 2
    font_id = 3
    page_ids = list(range(font_id + 1, font_id + 1 + page_count))
    contents_ids = list(range(page_ids[-1] + 1, page_ids[-1] + 1 + page_count))

    objects.append(
        f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii")
    )
    kids_str = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects.append(
        f"<< /Type /Pages /Kids [{kids_str}] /Count {page_count} >>".encode("ascii")
    )
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    )
    for pid, cid in zip(page_ids, contents_ids):
        objects.append(
            (
                f"<< /Type /Page /Parent {pages_id} 0 R "
                f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
                f"/Contents {cid} 0 R "
                f"/MediaBox [0 0 612 792] >>"
            ).encode("ascii")
        )
    for text in page_texts:
        # PDF strings: escape ( and \\ — sufficient for ASCII test text.
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = (
            f"BT /F1 12 Tf 100 700 Td ({safe}) Tj ET\n".encode("latin-1")
        )
        body = (
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\n"
            b"stream\n" + stream + b"endstream"
        )
        objects.append(body)

    # Assemble file with cross-reference table.
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for idx, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{idx} 0 obj\n".encode("ascii") + body + b"\nendobj\n"
    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode("ascii")
    out += (
        b"trailer\n<< /Size "
        + str(len(objects) + 1).encode("ascii")
        + f" /Root {catalog_id} 0 R >>\n".encode("ascii")
        + b"startxref\n"
        + str(xref_offset).encode("ascii")
        + b"\n%%EOF\n"
    )
    return bytes(out)


def write_pdf(path: Path, page_texts: Sequence[str]) -> Path:
    """Write a minimal PDF with the supplied per-page text and return path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_build_minimal_pdf(page_texts))
    return path
