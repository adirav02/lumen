"""Semantic unit builder and parser for mathematical and course knowledge units."""

import re
from typing import Any, Dict, List, Optional
import uuid

from ..models import KnowledgeUnit, UnitProvenance


def parse_structured_unit_blocks(
    text: str,
    course_id: str,
    source_version_id: str,
    page_index: Optional[int] = None,
    page_label: Optional[str] = None,
    slide_index: Optional[int] = None,
) -> List[tuple[KnowledgeUnit, UnitProvenance]]:
    """Parse text for structured knowledge units, preserving assumptions, symbols, exceptions, and locators."""
    units: List[tuple[KnowledgeUnit, UnitProvenance]] = []

    # Patterns looking for explicit definitions/theorems/formulas
    pattern = re.compile(
        r"(?:###?\s*(Definition|Theorem|Formula|Method|Example|Table|Figure):\s*(.+?)\n)(.*?)(?=(?:\n###?\s*(?:Definition|Theorem|Formula|Method|Example|Table|Figure):|\Z))",
        re.DOTALL | re.IGNORECASE,
    )

    matches = list(pattern.finditer(text))

    if matches:
        for m in matches:
            kind_str = m.group(1).lower()
            title = m.group(2).strip()
            block_body = m.group(3).strip()

            assumptions: List[str] = []
            symbol_defs: Dict[str, str] = {}
            exceptions: List[str] = []
            dependencies: List[str] = []

            # Extract fields within block body
            lines = block_body.splitlines()
            content_lines: List[str] = []

            for line in lines:
                stripped = line.strip()
                if stripped.lower().startswith("assumptions:") or stripped.lower().startswith("assumption:"):
                    raw = stripped.split(":", 1)[1].strip()
                    if raw:
                        assumptions.extend([a.strip() for a in raw.split(";") if a.strip()])
                elif stripped.lower().startswith("symbols:") or stripped.lower().startswith("symbol:"):
                    raw = stripped.split(":", 1)[1].strip()
                    for item in raw.split(";"):
                        if "=" in item:
                            k, v = item.split("=", 1)
                            symbol_defs[k.strip()] = v.strip()
                        elif ":" in item:
                            k, v = item.split(":", 1)
                            symbol_defs[k.strip()] = v.strip()
                elif stripped.lower().startswith("exceptions:") or stripped.lower().startswith("exception:"):
                    raw = stripped.split(":", 1)[1].strip()
                    if raw:
                        exceptions.extend([e.strip() for e in raw.split(";") if e.strip()])
                elif stripped.lower().startswith("dependencies:") or stripped.lower().startswith("dependency:"):
                    raw = stripped.split(":", 1)[1].strip()
                    if raw:
                        dependencies.extend([d.strip() for d in raw.split(",") if d.strip()])
                else:
                    content_lines.append(line)

            content = "\n".join(content_lines).strip()
            if not content:
                content = block_body

            unit_id = str(uuid.uuid4())
            ku = KnowledgeUnit(
                id=unit_id,
                course_id=course_id,
                kind=kind_str,
                title=title,
                content=content,
                summary=content[:200] + ("..." if len(content) > 200 else ""),
                assumptions=assumptions,
                symbol_definitions=symbol_defs,
                exceptions=exceptions,
                dependencies=dependencies,
                status="published",
            )
            prov = UnitProvenance(
                id=str(uuid.uuid4()),
                unit_id=unit_id,
                source_version_id=source_version_id,
                page_index=page_index,
                page_label=page_label,
                slide_index=slide_index,
                origin_type="extracted",
            )
            units.append((ku, prov))

    else:
        # Fallback: if no explicit markers, create a single general unit from the section
        if text.strip():
            first_line = text.strip().splitlines()[0][:80].lstrip("#").strip()
            title = first_line or (page_label or f"Section {page_index or 0}")
            unit_id = str(uuid.uuid4())
            ku = KnowledgeUnit(
                id=unit_id,
                course_id=course_id,
                kind="method" if "method" in title.lower() else "definition",
                title=title,
                content=text.strip(),
                summary=text.strip()[:200] + ("..." if len(text.strip()) > 200 else ""),
                assumptions=[],
                symbol_definitions={},
                exceptions=[],
                dependencies=[],
                status="published",
            )
            prov = UnitProvenance(
                id=str(uuid.uuid4()),
                unit_id=unit_id,
                source_version_id=source_version_id,
                page_index=page_index,
                page_label=page_label,
                slide_index=slide_index,
                origin_type="extracted",
            )
            units.append((ku, prov))

    return units


def build_unit_from_dict(
    d: Dict[str, Any],
    course_id: str,
    source_version_id: str,
    page_index: Optional[int] = None,
    page_label: Optional[str] = None,
    slide_index: Optional[int] = None,
) -> tuple[KnowledgeUnit, UnitProvenance]:
    """Build a KnowledgeUnit and UnitProvenance from a structured dictionary."""
    unit_id = d.get("id") or str(uuid.uuid4())
    ku = KnowledgeUnit(
        id=unit_id,
        course_id=course_id,
        kind=d.get("kind", "definition"),
        title=d["title"],
        content=d["content"],
        summary=d.get("summary", d["content"][:200]),
        assumptions=d.get("assumptions", []),
        symbol_definitions=d.get("symbol_definitions", {}),
        exceptions=d.get("exceptions", []),
        dependencies=d.get("dependencies", []),
        status=d.get("status", "published"),
    )
    prov = UnitProvenance(
        id=str(uuid.uuid4()),
        unit_id=unit_id,
        source_version_id=source_version_id,
        page_index=d.get("page_index", page_index),
        page_label=d.get("page_label", page_label),
        slide_index=d.get("slide_index", slide_index),
        region_box=d.get("region_box"),
        origin_type=d.get("origin_type", "extracted"),
    )
    return ku, prov
