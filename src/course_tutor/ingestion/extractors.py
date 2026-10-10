"""File format extractors for text, PDF, and PPTX with quality and uncertainty flags."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional


@dataclass
class ExtractedSection:
    section_index: int
    label: str  # e.g., "Page 1", "Slide 3", "Section 1"
    text: str
    quality_flag: str = "clean"  # 'clean', 'uncertain_scanned', 'has_images', 'empty'
    notes: str = ""
    metadata: dict = field(default_factory=dict)


class TextExtractor:
    """Extracts plain text and markdown files."""

    def extract(self, file_path: Path) -> List[ExtractedSection]:
        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = file_path.read_text(encoding="latin-1", errors="replace")

        if not content.strip():
            return [ExtractedSection(0, "Full Document", "", quality_flag="empty", notes="Empty text file")]

        # Split into logical sections by major markdown headings if present
        lines = content.splitlines()
        sections: List[ExtractedSection] = []
        current_title = "Introduction"
        current_lines: List[str] = []
        sec_idx = 0

        for line in lines:
            if line.startswith("# ") or line.startswith("## "):
                if current_lines:
                    sections.append(
                        ExtractedSection(
                            section_index=sec_idx,
                            label=current_title,
                            text="\n".join(current_lines).strip(),
                            quality_flag="clean",
                        )
                    )
                    sec_idx += 1
                    current_lines = []
                current_title = line.lstrip("#").strip()
            current_lines.append(line)

        if current_lines:
            sections.append(
                ExtractedSection(
                    section_index=sec_idx,
                    label=current_title,
                    text="\n".join(current_lines).strip(),
                    quality_flag="clean",
                )
            )

        return sections or [ExtractedSection(0, "Document", content, quality_flag="clean")]


class PDFExtractor:
    """Extracts text page-by-page from PDF files using pypdf, flagging scanned/empty pages."""

    def extract(self, file_path: Path) -> List[ExtractedSection]:
        try:
            from pypdf import PdfReader
        except ImportError:
            raise RuntimeError("pypdf is required for PDF extraction.")

        reader = PdfReader(str(file_path))
        sections: List[ExtractedSection] = []

        for idx, page in enumerate(reader.pages):
            page_label = f"Page {idx + 1}"
            raw_text = page.extract_text() or ""
            text = raw_text.strip()

            has_images = False
            try:
                has_images = len(page.images) > 0
            except Exception:
                pass

            if not text:
                if has_images:
                    quality = "uncertain_scanned"
                    notes = "Page contains images but no extractable text layer (possible scan or diagram)."
                else:
                    quality = "empty"
                    notes = "Page contains no extractable text."
            elif len(text) < 40 and has_images:
                quality = "uncertain_scanned"
                notes = "Low text density with images present; formulas or diagrams may require review."
            else:
                quality = "clean"
                notes = ""

            sections.append(
                ExtractedSection(
                    section_index=idx,
                    label=page_label,
                    text=text,
                    quality_flag=quality,
                    notes=notes,
                    metadata={"page_index": idx, "has_images": has_images},
                )
            )

        return sections


class PPTXExtractor:
    """Extracts text slide-by-slide from PPTX files using python-pptx."""

    def extract(self, file_path: Path) -> List[ExtractedSection]:
        try:
            from pptx import Presentation
        except ImportError:
            raise RuntimeError("python-pptx is required for PPTX extraction.")

        prs = Presentation(str(file_path))
        sections: List[ExtractedSection] = []

        for idx, slide in enumerate(prs.slides):
            slide_label = f"Slide {idx + 1}"
            slide_texts: List[str] = []
            slide_title = ""

            for shape in slide.shapes:
                if shape.has_text_frame:
                    shape_text = shape.text_frame.text.strip()
                    if shape_text:
                        if not slide_title and shape == slide.shapes[0]:
                            slide_title = shape_text
                        slide_texts.append(shape_text)

            combined_text = "\n\n".join(slide_texts).strip()
            quality = "clean" if combined_text else "empty"
            notes = "" if combined_text else "Slide contains no text shapes."

            sections.append(
                ExtractedSection(
                    section_index=idx,
                    label=slide_label,
                    text=combined_text,
                    quality_flag=quality,
                    notes=notes,
                    metadata={"slide_index": idx, "slide_title": slide_title},
                )
            )

        return sections


def get_extractor(file_path: Path):
    """Factory selecting the appropriate extractor based on file extension."""
    suffix = file_path.suffix.lower()
    if suffix in (".pdf",):
        return PDFExtractor()
    elif suffix in (".pptx", ".ppt"):
        return PPTXExtractor()
    else:
        return TextExtractor()
