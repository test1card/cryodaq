"""F-KnowledgeBaseExpansion (v0.55.7.1): PDF ingestion для equipment manuals.

Per-page chunking. Metadata records ``page_number`` and ``document_name``
so the operator UI can render citations like «Etalon MultiLine — стр. 5»
instead of opaque chunk ids. Encrypted and corrupt PDFs are skipped
with a warning rather than crashing the bootstrap batch — partial
corpus is always preferred to none.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from cryodaq.agents.rag.document_loader import DocumentChunk, _chunk_text

logger = logging.getLogger(__name__)


def load_pdf_documents(
    pdf_dir: Path,
    *,
    source_kind: str = "equipment_manual",
    max_chars: int = 1000,
    overlap: int = 100,
) -> list[DocumentChunk]:
    """Walk ``pdf_dir`` recursively → chunks per PDF page with metadata.

    One chunk per page if the page text fits, otherwise multiple chunks
    via the standard sliding-window chunker so a long page does not
    blow the embedder's input window. Whitespace inside extracted text
    is normalised (collapse runs to a single space) — pypdf's layout
    extraction tends to scatter line breaks across phrases.

    Skips:
    - Missing ``pdf_dir`` (returns ``[]``);
    - Encrypted PDFs (warning, skip — operator must decrypt before
      drop, not the loader's job);
    - PDFs that fail to parse (warning, continue with the next file);
    - Empty pages (no text content — silently dropped, common for
      title pages and image-only sections).
    """
    chunks: list[DocumentChunk] = []
    if not pdf_dir.exists():
        return chunks

    pdf_files = sorted(p for p in pdf_dir.rglob("*.pdf") if p.is_file())
    logger.info(
        "PDF loader: scanning %s, found %d PDFs", pdf_dir, len(pdf_files)
    )

    for pdf_path in pdf_files:
        try:
            reader = PdfReader(str(pdf_path))
        except (PdfReadError, OSError, Exception) as exc:  # noqa: BLE001
            logger.warning("PDF load failed %s: %s", pdf_path.name, exc)
            continue

        if reader.is_encrypted:
            logger.warning("PDF encrypted, skipped: %s", pdf_path.name)
            continue

        document_name = pdf_path.stem.replace("_", " ").replace("-", " ")
        # as_posix() so source ids use forward slashes on every OS — keeps the
        # RAG corpus portable between Mac dev and Windows operator PCs.
        relative_path = pdf_path.relative_to(pdf_dir).as_posix()
        try:
            total_pages = len(reader.pages)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "PDF page count failed %s: %s", pdf_path.name, exc
            )
            continue

        for page_idx, page in enumerate(reader.pages, start=1):
            try:
                page_text = page.extract_text() or ""
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "PDF page extract failed %s page %d: %s",
                    pdf_path.name,
                    page_idx,
                    exc,
                )
                continue

            page_text = re.sub(r"\s+", " ", page_text).strip()
            if not page_text:
                continue

            page_chunks = _chunk_text(
                page_text, max_chars=max_chars, overlap=overlap
            )
            for chunk_idx, chunk_text in enumerate(page_chunks):
                chunk_id = f"pdf:{relative_path}:p{page_idx}:c{chunk_idx}"
                chunks.append(
                    DocumentChunk(
                        chunk_id=chunk_id,
                        source_kind=source_kind,
                        source_id=relative_path,
                        text=chunk_text,
                        metadata={
                            "document_name": document_name,
                            "page_number": page_idx,
                            "total_pages": total_pages,
                            "chunk_index": chunk_idx,
                            "source_path": relative_path,
                        },
                    )
                )

    logger.info(
        "PDF loader: %d chunks from %d PDFs in %s",
        len(chunks),
        len(pdf_files),
        pdf_dir,
    )
    return chunks
