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
    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._experiments_dir = data_dir / "experiments"
        self._extractor = ReportDataExtractor(data_dir)

    def generate(self, experiment_id: str) -> ReportGenerationResult:
        metadata_path = self._experiments_dir / experiment_id / "metadata.json"
        dataset = self._extractor.load_dataset(metadata_path)
        experiment = dataset.metadata["experiment"]
        template = dataset.metadata["template"]
        if not bool(experiment.get("report_enabled", template.get("report_enabled", True))):
            return ReportGenerationResult(
                docx_path=metadata_path.parent / "reports" / "report.docx",
                pdf_path=None,
                assets_dir=metadata_path.parent / "reports" / "assets",
                sections=tuple(),
                skipped=True,
                reason="report disabled by template",
            )

        section_names = self._resolve_sections(dataset.metadata)
        reports_dir = metadata_path.parent / "reports"
        assets_dir = reports_dir / "assets"
        reports_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)

        document = Document()
        for index, section_name in enumerate(section_names):
            renderer = SECTION_REGISTRY[section_name]
            renderer(document, dataset, assets_dir)
            if index < len(section_names) - 1:
                document.add_page_break()

        docx_path = reports_dir / "report.docx"
        document.save(str(docx_path))
        pdf_path = self._try_convert_pdf(docx_path)
        return ReportGenerationResult(
            docx_path=docx_path,
            pdf_path=pdf_path,
            assets_dir=assets_dir,
            sections=tuple(section_names),
        )

    def _resolve_sections(self, metadata: dict) -> list[str]:
        template = metadata.get("template", {})
        section_names = list(template.get("report_sections") or [])
        if not section_names:
            section_names = ["title_page", "operator_log_section", "config_section"]
        return [name for name in section_names if name in SECTION_REGISTRY]

    def _try_convert_pdf(self, docx_path: Path) -> Path | None:
        soffice = shutil.which("soffice") or shutil.which("libreoffice")
        if not soffice:
            return None
        output_dir = docx_path.parent
        subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", str(docx_path), "--outdir", str(output_dir)],
            check=False,
            capture_output=True,
        )
        pdf_path = output_dir / f"{docx_path.stem}.pdf"
        return pdf_path if pdf_path.exists() else None
