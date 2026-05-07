"""F-KnowledgeBaseExpansion (v0.55.7.1): pretty source labels для citations.

Without this, the GUI и Гемма format prompts dump raw chunk metadata
(``source_kind=equipment_manual, source_id=etalon_multiline.pdf,
metadata.page_number=5``) into the operator's view. Operator-readable
labels — «Etalon MultiLine — стр. 5», «Процедура: Аварийное
отключение», «CHANGELOG v0.55.7» — are produced by a single function
shared by both surfaces so the wording stays consistent.
"""

from __future__ import annotations

from typing import Any


def prettify_source_label(source_kind: str, metadata: dict[str, Any]) -> str:
    """Render a human-readable citation label for one search hit.

    Recognises the source_kind variants emitted by the loaders shipped
    in PHASES 2-4 plus the F32 Stage 1 originals (experiment_metadata,
    operator_log, vault_note). Unknown kinds fall back к the raw kind
    string so a future loader doesn't silently ghost the operator —
    the citation just looks slightly less pretty until the helper is
    extended.
    """
    md = metadata or {}

    if source_kind == "equipment_manual":
        doc = md.get("document_name") or "Документация"
        page = md.get("page_number")
        if page:
            return f"{doc} — стр. {page}"
        return str(doc)

    if source_kind == "procedure":
        title = md.get("title") or "Процедура"
        return f"Процедура: {title}"

    if source_kind == "operator_manual":
        return "Operator Manual"

    if source_kind in ("readme", "readme_en"):
        suffix = " (EN)" if source_kind == "readme_en" else ""
        return f"Project README{suffix}"

    if source_kind == "changelog":
        version = md.get("version") or ""
        # Strip a leading 'v' if the version string already carries one
        # so we don't end up rendering «CHANGELOG v v0.55.7».
        v = version.lstrip("v") if isinstance(version, str) else version
        return f"CHANGELOG{f' v{v}' if v else ''}"

    if source_kind == "experiment_metadata":
        title = md.get("title") or ""
        started_raw = md.get("started_at") or ""
        # Trim к YYYY-MM-DD; the metadata stores ISO timestamp.
        started = started_raw[:10] if isinstance(started_raw, str) else ""
        if title and started:
            return f"Эксперимент: {title} — {started}"
        if title:
            return f"Эксперимент: {title}"
        return "Эксперимент"

    if source_kind == "operator_log":
        ts_raw = md.get("timestamp") or ""
        ts = ts_raw[:10] if isinstance(ts_raw, str) else ""
        author = md.get("author") or ""
        if author and ts:
            return f"Журнал: {author} — {ts}"
        if author:
            return f"Журнал: {author}"
        if ts:
            return f"Журнал: {ts}"
        return "Журнал оператора"

    if source_kind == "vault_note":
        title = md.get("title") or md.get("source_id") or "?"
        return f"Заметка: {title}"

    return source_kind
