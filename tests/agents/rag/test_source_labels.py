"""F-KnowledgeBaseExpansion (v0.55.7.1) — pretty source label tests."""

from __future__ import annotations

import pytest

from cryodaq.agents.rag.source_labels import prettify_source_label


def test_prettify_equipment_manual_includes_page() -> None:
    label = prettify_source_label(
        "equipment_manual",
        {"document_name": "Etalon MultiLine", "page_number": 5},
    )
    assert label == "Etalon MultiLine — стр. 5"


def test_prettify_equipment_manual_no_page_uses_doc() -> None:
    label = prettify_source_label(
        "equipment_manual", {"document_name": "Etalon MultiLine"}
    )
    assert label == "Etalon MultiLine"


def test_prettify_equipment_manual_no_doc_uses_default() -> None:
    label = prettify_source_label("equipment_manual", {})
    assert label == "Документация"


def test_prettify_procedure_uses_title() -> None:
    label = prettify_source_label(
        "procedure", {"title": "Аварийное отключение"}
    )
    assert label == "Процедура: Аварийное отключение"


def test_prettify_procedure_default_title_when_missing() -> None:
    label = prettify_source_label("procedure", {})
    assert label == "Процедура: Процедура"


def test_prettify_operator_manual_static() -> None:
    assert prettify_source_label("operator_manual", {}) == "Operator Manual"


def test_prettify_readme() -> None:
    assert prettify_source_label("readme", {}) == "Project README"


def test_prettify_readme_en() -> None:
    assert prettify_source_label("readme_en", {}) == "Project README (EN)"


def test_prettify_changelog_includes_version() -> None:
    label = prettify_source_label("changelog", {"version": "0.55.7"})
    assert label == "CHANGELOG v0.55.7"


def test_prettify_changelog_strips_leading_v_to_avoid_double() -> None:
    label = prettify_source_label("changelog", {"version": "v0.55.7"})
    assert label == "CHANGELOG v0.55.7"
    assert "v v" not in label


def test_prettify_changelog_no_version() -> None:
    assert prettify_source_label("changelog", {}) == "CHANGELOG"


def test_prettify_experiment_metadata_includes_date() -> None:
    label = prettify_source_label(
        "experiment_metadata",
        {"title": "Cooldown S-001", "started_at": "2026-04-15T03:30:00+00:00"},
    )
    assert label == "Эксперимент: Cooldown S-001 — 2026-04-15"


def test_prettify_experiment_metadata_title_only() -> None:
    label = prettify_source_label(
        "experiment_metadata", {"title": "Cooldown S-001"}
    )
    assert label == "Эксперимент: Cooldown S-001"


def test_prettify_experiment_metadata_no_title() -> None:
    assert prettify_source_label("experiment_metadata", {}) == "Эксперимент"


def test_prettify_operator_log_with_author_and_ts() -> None:
    label = prettify_source_label(
        "operator_log",
        {"timestamp": "2026-04-15T08:00:00+00:00", "author": "Vladimir"},
    )
    assert label == "Журнал: Vladimir — 2026-04-15"


def test_prettify_operator_log_author_only() -> None:
    label = prettify_source_label("operator_log", {"author": "Vladimir"})
    assert label == "Журнал: Vladimir"


def test_prettify_operator_log_default() -> None:
    assert prettify_source_label("operator_log", {}) == "Журнал оператора"


def test_prettify_vault_note() -> None:
    label = prettify_source_label("vault_note", {"title": "F-MultiLine spec"})
    assert label == "Заметка: F-MultiLine spec"


def test_prettify_unknown_kind_returns_kind_string() -> None:
    """Future loaders not yet mapped fall back gracefully."""
    label = prettify_source_label("future_kind_xyz", {"foo": "bar"})
    assert label == "future_kind_xyz"


def test_prettify_handles_none_metadata() -> None:
    """Defensive: if metadata is None (legacy callers), no crash."""
    assert prettify_source_label("operator_manual", None) == "Operator Manual"
