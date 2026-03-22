from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm, Mm, Pt, RGBColor

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
        "cooldown_section",
        "thermal_section",
        "pressure_section",
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
        self._apply_gost_formatting(document)

        from cryodaq.reporting.sections import _reset_counters
        _reset_counters()

        for index, section_name in enumerate(sections):
            renderer = SECTION_REGISTRY[section_name]
            renderer(document, dataset, assets_dir)
            if index < len(sections) - 1:
                document.add_page_break()
        return document

    @staticmethod
    def _apply_gost_formatting(document: Document) -> None:
        """Apply ГОСТ Р 2.105-2019 page setup and styles."""
        # Page setup: A4, margins
        sec = document.sections[0]
        sec.page_width = Mm(210)
        sec.page_height = Mm(297)
        sec.left_margin = Mm(30)
        sec.right_margin = Mm(15)
        sec.top_margin = Mm(20)
        sec.bottom_margin = Mm(20)

        # Normal style: Times New Roman 14pt, 1.5 spacing, first-line indent
        style = document.styles["Normal"]
        style.font.name = "Times New Roman"
        style.font.size = Pt(14)
        pf = style.paragraph_format
        pf.space_after = Pt(0)
        pf.space_before = Pt(0)
        pf.line_spacing = 1.5
        pf.first_line_indent = Cm(1.25)

        # Heading 1: 16pt bold black
        h1 = document.styles["Heading 1"]
        h1.font.name = "Times New Roman"
        h1.font.size = Pt(16)
        h1.font.bold = True
        h1.font.color.rgb = RGBColor(0, 0, 0)
        h1.paragraph_format.space_before = Pt(24)
        h1.paragraph_format.space_after = Pt(12)
        h1.paragraph_format.first_line_indent = Cm(0)

        # Heading 2: 14pt bold black
        h2 = document.styles["Heading 2"]
        h2.font.name = "Times New Roman"
        h2.font.size = Pt(14)
        h2.font.bold = True
        h2.font.color.rgb = RGBColor(0, 0, 0)
        h2.paragraph_format.space_before = Pt(18)
        h2.paragraph_format.space_after = Pt(6)
        h2.paragraph_format.first_line_indent = Cm(0)

        # Title: 18pt bold centered
        ts = document.styles["Title"]
        ts.font.name = "Times New Roman"
        ts.font.size = Pt(18)
        ts.font.bold = True
        ts.font.color.rgb = RGBColor(0, 0, 0)
        ts.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
        ts.paragraph_format.first_line_indent = Cm(0)

        # List Bullet
        if "List Bullet" in document.styles:
            lb = document.styles["List Bullet"]
            lb.font.name = "Times New Roman"
            lb.font.size = Pt(14)
            lb.paragraph_format.line_spacing = 1.5

        # Footer with page number (center)
        footer = sec.footer
        footer.is_linked_to_previous = False
        fp = footer.paragraphs[0] if footer.paragraphs else footer.add_paragraph()
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        from docx.oxml.ns import qn
        run = fp.add_run()
        run._element.append(run._element.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): "begin"}))
        run2 = fp.add_run()
        instr = run2._element.makeelement(qn("w:instrText"), {qn("xml:space"): "preserve"})
        instr.text = " PAGE "
        run2._element.append(instr)
        run3 = fp.add_run()
        run3._element.append(run3._element.makeelement(qn("w:fldChar"), {qn("w:fldCharType"): "end"}))

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
