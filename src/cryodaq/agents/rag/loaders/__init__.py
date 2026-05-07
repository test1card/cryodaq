"""F-KnowledgeBaseExpansion (v0.55.7.1): additional document loaders для RAG.

Stage 1 loaders (experiment metadata, vault notes, operator log) live in
:mod:`cryodaq.agents.rag.document_loader`. The loaders here extend that
corpus with operator-facing knowledge sources: PDF equipment manuals,
markdown procedures, and project reference docs. Each module exposes a
single ``load_*`` function returning ``list[DocumentChunk]`` so the
indexer can append them to the existing corpus without schema changes.
"""

from __future__ import annotations
