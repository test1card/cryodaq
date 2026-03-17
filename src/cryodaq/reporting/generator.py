from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from docx import Document

from cryodaq.reporting.data import ReportDataExtractor
from cryodaq.reporting.sections import SECTION_REGISTRY


@dataclass(frozen=True, slots=True)
class ReportGenerationResult:
    docx_path: Path
    pdf_path: Path | None
    assets_dir: Path
    sections: tuple[str, ...]
    skipped: bool = False
    reason: str = ""


class ReportGenerator:
    _BASE_RAW_SECTIONS = (
        "title_page",
        "experiment_metadata_section",
        "run_timeline_section",
        "run_parameters_section",
        "result_tables_section",
        "conductivity_section",
        "artifact_manifest_section",
    )
    _EDITABLE_ONLY_SECTIONS = (
        "operator_comments_section",
        "operator_interpretation_section",
        "operator_photos_section",
    )

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._experiments_dir = data_dir / "experiments"
        self._extractor = ReportDataExtractor(data_dir)

    def generate(self, experiment_id: str) -> ReportGenerationResult:
        metadata_path = self._experiments_dir / experiment_id / "metadata.json"
        dataset = self._extractor.load_dataset(metadata_path)
        experiment = dataset.metadata["experiment"]
        template = dataset.metadata["template"]
        reports_dir = metadata_path.parent / "reports"
        assets_dir = reports_dir / "assets"
        editable_docx_path = reports_dir / "report_editable.docx"
        raw_source_docx_path = reports_dir / "report_raw.docx"
        raw_pdf_path = reports_dir / "report_raw.pdf"

        if not bool(experiment.get("report_enabled", template.get("report_enabled", True))):
            return ReportGenerationResult(
                docx_path=editable_docx_path,
                pdf_path=None,
                assets_dir=assets_dir,
                sections=tuple(),
                skipped=True,
                reason="Формирование отчёта отключено шаблоном.",
            )

        reports_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)

        raw_sections = self._resolve_raw_sections(dataset.metadata)
        editable_sections = tuple(list(raw_sections) + list(self._EDITABLE_ONLY_SECTIONS))

        raw_document = self._build_document(dataset, assets_dir, raw_sections)
        raw_document.save(str(raw_source_docx_path))
        pdf_path = self._try_convert_pdf(raw_source_docx_path, raw_pdf_path)

        editable_document = self._build_document(dataset, assets_dir, editable_sections)
        editable_document.save(str(editable_docx_path))

        return ReportGenerationResult(
            docx_path=editable_docx_path,
            pdf_path=pdf_path,
            assets_dir=assets_dir,
            sections=editable_sections,
        )

    def _build_document(self, dataset, assets_dir: Path, sections: tuple[str, ...]) -> Document:
        document = Document()
        for index, section_name in enumerate(sections):
            renderer = SECTION_REGISTRY[section_name]
            renderer(document, dataset, assets_dir)
            if index < len(sections) - 1:
                document.add_page_break()
        return document

    def _resolve_raw_sections(self, metadata: dict) -> tuple[str, ...]:
        template = metadata.get("template", {})
        configured = [name for name in list(template.get("report_sections") or []) if name in SECTION_REGISTRY]
        ordered: list[str] = []
        for name in self._BASE_RAW_SECTIONS + tuple(configured):
            if name not in ordered:
                ordered.append(name)
        if "config_section" not in ordered and "config_section" in SECTION_REGISTRY:
            ordered.append("config_section")
        return tuple(ordered)

    def _try_convert_pdf(self, source_docx_path: Path, target_pdf_path: Path) -> Path | None:
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            return None
        output_dir = source_docx_path.parent
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", str(source_docx_path), "--outdir", str(output_dir)],
            check=False,
            capture_output=True,
        )
        produced = output_dir / f"{source_docx_path.stem}.pdf"
        if not produced.exists():
            return None
        if produced != target_pdf_path:
            if target_pdf_path.exists():
                target_pdf_path.unlink()
            produced.replace(target_pdf_path)
        return target_pdf_path if target_pdf_path.exists() else None
