"""Semantic unit builder and parser for mathematical and course knowledge units."""

import re
from typing import Any, Dict, List, Optional
import uuid

from ..models import KnowledgeUnit, UnitProvenance


def extract_assumptions_from_text(text: str) -> List[str]:
    """Detect natural language conditions and assumption clauses in text."""
    assumptions = []
    # Match patterns like: assumes P(B) > 0, assuming X is non-negative, provided that n >= 1
    patterns = [
        r"(?:assumes?|assuming|under the assumption that|provided that|subject to the condition that)\s+([^.\n;]+)",
        r"(?:where|with)\s+([A-Za-z0-9_\(\)\|\s\>\<\=\\+\-]+>\s*0)",
    ]
    for pat in patterns:
        for match in re.finditer(pat, text, re.IGNORECASE):
            cond = match.group(1).strip()
            if cond and len(cond) < 120 and cond not in assumptions:
                assumptions.append(cond)
    return assumptions


def parse_structured_unit_blocks(
    text: str,
    course_id: str,
    source_version_id: str,
    page_index: Optional[int] = None,
    page_label: Optional[str] = None,
    slide_index: Optional[int] = None,
) -> List[tuple[KnowledgeUnit, UnitProvenance]]:
    """Parse text for structured knowledge units, preserving preambles, assumptions, symbols, exceptions, and locators.

    Automatic segmentation preserves surrounding context and marks units as pending_review.
    """
    units: List[tuple[KnowledgeUnit, UnitProvenance]] = []

    # Patterns looking for explicit definitions/theorems/formulas in English or Hebrew
    pattern = re.compile(
        r"(?:###?\s*(Definition|Theorem|Formula|Method|Example|Table|Figure|הגדרה|משפט|נוסחה|שיטה|דוגמה|טבלה):\s*(.+?)\n)(.*?)(?=(?:\n###?\s*(?:Definition|Theorem|Formula|Method|Example|Table|Figure|הגדרה|משפט|נוסחה|שיטה|דוגמה|טבלה):|\Z))",
        re.DOTALL | re.IGNORECASE,
    )

    matches = list(pattern.finditer(text))

    if matches:
        last_end = 0
        for i, m in enumerate(matches):
            kind_str = m.group(1).lower()
            # Normalize Hebrew kinds
            hebrew_kind_map = {
                "משפט": "theorem",
                "הגדרה": "definition",
                "נוסחה": "formula",
                "שיטה": "method",
                "דוגמה": "example",
                "טבלה": "table",
            }
            kind_str = hebrew_kind_map.get(kind_str, kind_str)

            title = m.group(2).strip()
            block_body = m.group(3).strip()

            # Capture preceding preamble or interstitial text between units
            preamble = text[last_end:m.start()].strip()
            last_end = m.end()

            assumptions: List[str] = []
            symbol_defs: Dict[str, str] = {}
            exceptions: List[str] = []
            dependencies: List[str] = []

            # 1. Check preamble for conditions/assumptions
            if preamble:
                assumptions.extend(extract_assumptions_from_text(preamble))

            # 2. Extract explicit fields within block body
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

            inner_content = "\n".join(content_lines).strip() or block_body
            # Combine preamble and inner content so context is preserved
            if preamble:
                content = f"{preamble}\n\n{inner_content}"
            else:
                content = inner_content

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
                status="pending_review",  # Automatic segmentation defaults to pending_review
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
            assumptions = extract_assumptions_from_text(text.strip())

            ku = KnowledgeUnit(
                id=unit_id,
                course_id=course_id,
                kind="method" if "method" in title.lower() else "definition",
                title=title,
                content=text.strip(),
                summary=text.strip()[:200] + ("..." if len(text.strip()) > 200 else ""),
                assumptions=assumptions,
                symbol_definitions={},
                exceptions=[],
                dependencies=[],
                status="pending_review",
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
        status=d.get("status", "published"),  # Agent-submitted enrichment can declare published status
    )
    prov = UnitProvenance(
        id=str(uuid.uuid4()),
        unit_id=unit_id,
        source_version_id=source_version_id,
        page_index=d.get("page_index", page_index),
        page_label=d.get("page_label", page_label),
        slide_index=d.get("slide_index", slide_index),
        region_box=d.get("region_box"),
        origin_type=d.get("origin_type", "agent_enrichment"),
    )
    return ku, prov
