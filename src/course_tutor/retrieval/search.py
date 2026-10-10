"""Search service combining FTS5, multilingual topic aliases, and provenance metadata."""

import sqlite3
from typing import Any, Dict, List, Optional, Set

from ..models import KnowledgeUnit
from ..storage.repositories import (
    KnowledgeRepository,
    SourceRepository,
    TopicRepository,
)
from .fts import FTSSearcher


class SearchService:
    def __init__(self, con: sqlite3.Connection):
        self.con = con
        self.fts = FTSSearcher(con)
        self.knowledge_repo = KnowledgeRepository(con)
        self.topic_repo = TopicRepository(con)
        self.source_repo = SourceRepository(con)

    def search(
        self,
        course_id: str,
        query: str,
        topic_id: Optional[str] = None,
        source_id: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Search knowledge units using FTS5 and topic aliases (English, Hebrew, math notation).

        Returns compact results first, with provenance references and match origins.
        """
        seen_unit_ids: Set[str] = set()
        results: List[Dict[str, Any]] = []

        # 1. Direct FTS search
        fts_hits = self.fts.search_units(course_id, query, limit=limit)
        for hit in fts_hits:
            uid = hit["unit_id"]
            unit = self.knowledge_repo.get_unit(uid)
            if not unit or unit.course_id != course_id:
                continue

            # Topic filter if specified
            if topic_id:
                unit_topics = self.knowledge_repo.get_unit_topics(uid)
                if topic_id not in unit_topics:
                    continue

            seen_unit_ids.add(uid)
            results.append(self._format_hit(unit, hit["score"], match_type="fts"))

        # 2. Multilingual topic alias search (F03: Hebrew / English / notation aliases)
        alias_topics = self.topic_repo.find_by_alias(course_id, query)
        for t in alias_topics:
            if topic_id and t.id != topic_id:
                continue

            # Find units mapped to this topic
            rows = self.con.execute(
                "SELECT unit_id FROM unit_topics WHERE topic_id = ?",
                (t.id,),
            ).fetchall()

            for r in rows:
                uid = r["unit_id"]
                if uid in seen_unit_ids:
                    continue
                unit = self.knowledge_repo.get_unit(uid)
                if not unit or unit.course_id != course_id:
                    continue

                seen_unit_ids.add(uid)
                results.append(self._format_hit(unit, score=0.5, match_type=f"alias_topic:{t.name}"))

        # Sort results: lower score is better in FTS BM25, alias matches placed appropriately
        results.sort(key=lambda x: x["score"])
        return results[:limit]

    def _format_hit(self, unit: KnowledgeUnit, score: float, match_type: str) -> Dict[str, Any]:
        provenance_list = self.knowledge_repo.get_provenance(unit.id)
        prov_summaries = []

        for p in provenance_list:
            s_ver = self.source_repo.get_source_version(p.source_version_id)
            src_name = s_ver.original_filename if s_ver else "source"
            loc = []
            if p.page_label:
                loc.append(p.page_label)
            elif p.page_index is not None:
                loc.append(f"Page {p.page_index + 1}")
            if p.slide_index is not None:
                loc.append(f"Slide {p.slide_index + 1}")

            loc_str = f" ({', '.join(loc)})" if loc else ""
            prov_summaries.append(f"{src_name}{loc_str}")

        topic_ids = self.knowledge_repo.get_unit_topics(unit.id)
        topic_names = []
        for tid in topic_ids:
            t = self.topic_repo.get_topic(tid)
            if t:
                topic_names.append(t.name)

        return {
            "unit_id": unit.id,
            "kind": unit.kind,
            "title": unit.title,
            "summary": unit.summary,
            "assumptions_count": len(unit.assumptions),
            "has_formulas_or_symbols": len(unit.symbol_definitions) > 0,
            "score": score,
            "match_type": match_type,
            "provenance": prov_summaries,
            "topics": topic_names,
        }
