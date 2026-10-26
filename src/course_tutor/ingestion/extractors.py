"""File format extractors for text, PDF, and PPTX with quality and uncertainty flags."""

import hashlib

from dataclasses import dataclass, field
from pathlib import Path
from typing import List


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
        original = file_path.read_bytes()
        try:
            content = original.decode('utf-8')
        except UnicodeDecodeError:
            content = original.decode('latin-1', errors='replace')
        content = content.replace('\r\n', '\n').replace('\r', '\n')
        original_hash = hashlib.sha256(original).hexdigest()

        def provenance(sections):
            for section in sections:
                section.metadata.update(original_sha256=original_hash,
                    extracted_text_sha256=hashlib.sha256(section.text.encode('utf-8')).hexdigest(),
                    text_normalization='Decoded text; universal LF line endings, heading sections and trimmed section boundaries. Original bytes unchanged.')
            return sections

        if not content.strip():
            return provenance([ExtractedSection(0, "Full Document", "", quality_flag="empty", notes="Empty text file")])

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

        return provenance(sections or [ExtractedSection(0, "Document", content, quality_flag="clean")])


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
            elif has_images:
                quality = "has_images"
                notes = "Text extracted; embedded images or diagrams require host visual review."
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
            has_visuals = False

            def shapes_with_groups(shapes):
                for shape in shapes:
                    yield shape
                    if hasattr(shape, "shapes"):
                        yield from shapes_with_groups(shape.shapes)

            for shape in shapes_with_groups(slide.shapes):
                if shape.has_table:
                    for row in shape.table.rows:
                        slide_texts.append("\t".join(cell.text for cell in row.cells))
                if shape.has_text_frame:
                    shape_text = shape.text_frame.text.strip()
                    if shape_text:
                        if not slide_title and shape == slide.shapes[0]:
                            slide_title = shape_text
                        slide_texts.append(shape_text)
                # Pictures, charts, embedded objects and unparsed drawing shapes
                # retain their original slide and explicitly require review.
                if not shape.has_text_frame and not shape.has_table and not hasattr(shape, "shapes"):
                    has_visuals = True

            combined_text = "\n\n".join(slide_texts).strip()
            quality = "clean" if combined_text else "empty"
            notes = "" if combined_text else "Slide contains no text shapes."
            if has_visuals:
                quality = "has_images"
                notes = "Slide contains visual elements requiring host inspection; extracted text/tables may be incomplete."

            sections.append(
                ExtractedSection(
                    section_index=idx,
                    label=slide_label,
                    text=combined_text,
                    quality_flag=quality,
                    notes=notes,
                    metadata={"slide_index": idx, "slide_title": slide_title, "has_images": has_visuals},
                )
            )

        return sections


class VisualOnlyExtractor:
    """Preserve visual originals without fabricating text or OCR support."""

    def extract(self, file_path: Path) -> List[ExtractedSection]:
        return [ExtractedSection(
            0, "Image", "", quality_flag="uncertain_scanned",
            notes="Image has no core text extraction; host visual inspection is required.",
            metadata={"has_images": True},
        )]


class UnsupportedExtractor:
    def extract(self, file_path: Path) -> List[ExtractedSection]:
        return [ExtractedSection(
            0, "Original file", "", quality_flag="unsupported",
            notes=f"Unsupported extraction format '{file_path.suffix}'; original preserved for review.",
        )]


def get_extractor(file_path: Path):
    """Factory selecting the appropriate extractor based on file extension."""
    suffix = file_path.suffix.lower()
    if suffix in (".pdf",):
        return PDFExtractor()
    elif suffix == ".docx":
        from .docx import DOCXExtractor
        return DOCXExtractor()
    elif suffix == ".pptx":
        return PPTXExtractor()
    elif suffix in (".txt", ".md", ".markdown", ".rst", ".tex", ".csv", ".tsv"):
        return TextExtractor()
    elif suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".tif", ".tiff", ".bmp"):
        return VisualOnlyExtractor()
    return UnsupportedExtractor()
