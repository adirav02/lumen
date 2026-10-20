"""SQLite FTS5 query builder and search utilities."""

import re
import sqlite3
from typing import Any, Dict, List, Optional


def sanitize_fts_query(query: str) -> str:
    """Sanitize user query for SQLite FTS5 MATCH syntax, supporting Hebrew, English, and math notation."""
    clean = re.sub(r'["\*\+\-\^\:]', " ", query)
    tokens = [t.strip() for t in clean.split() if t.strip()]
    if not tokens:
        return ""
    # Use prefix search on tokens or quote them
    fts_tokens = [f'"{t}"*' for t in tokens]
    return " OR ".join(fts_tokens)


class FTSSearcher:
    def __init__(self, con: sqlite3.Connection):
        self.con = con

    def search_units(
        self,
        course_id: str,
        query: str,
        limit: int = 10,
        topic_id: Optional[str] = None,
        source_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search fts_units using FTS5 bm25 ranking."""
        fts_query = sanitize_fts_query(query)
        if not fts_query:
            return []

        filters = ""
        filter_params = []
        if topic_id:
            filters += " AND EXISTS (SELECT 1 FROM unit_topics ut WHERE ut.unit_id = fts_units.unit_id AND ut.topic_id = ?)"
            filter_params.append(topic_id)
        if source_id:
            filters += " AND EXISTS (SELECT 1 FROM unit_provenance p JOIN source_versions sv ON sv.id = p.source_version_id WHERE p.unit_id = fts_units.unit_id AND sv.source_id = ?)"
            filter_params.append(source_id)
        sql = """
            SELECT unit_id, course_id, title, summary, bm25(fts_units) AS rank
            FROM fts_units
            WHERE course_id = ? AND fts_units MATCH ?
        """ + filters + """
            ORDER BY rank ASC
            LIMIT ?
        """
        try:
            rows = self.con.execute(sql, (course_id, fts_query, *filter_params, limit)).fetchall()
            return [
                {
                    "unit_id": r["unit_id"],
                    "course_id": r["course_id"],
                    "title": r["title"],
                    "summary": r["summary"],
                    "score": float(r["rank"]),
                }
                for r in rows
            ]
        except sqlite3.OperationalError:
            # Fallback to simple LIKE if MATCH query encounters odd syntax
            like_pattern = f"%{query}%"
            fallback_sql = """
                SELECT unit_id, course_id, title, summary, 0.0 AS rank
                FROM fts_units
                WHERE course_id = ? AND (title LIKE ? OR content LIKE ?)
            """ + filters + """
                LIMIT ?
            """
            rows = self.con.execute(fallback_sql, (course_id, like_pattern, like_pattern, *filter_params, limit)).fetchall()
            return [
                {
                    "unit_id": r["unit_id"],
                    "course_id": r["course_id"],
                    "title": r["title"],
                    "summary": r["summary"],
                    "score": 0.0,
                }
                for r in rows
            ]
