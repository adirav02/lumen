"""Directional, text-bound question constraints; no learner or review inference."""
import json
import re

from ..errors import ValidationError
from .catalog import digest, normalized

from .known_constraints import known_metadata, paper_settings

FIELDS = ('depends_on', 'gives_away')

def identity(text_hash, subparts):
    return digest(json.dumps([text_hash, json.loads(subparts)], sort_keys=True, ensure_ascii=False))


def _version(con, course, vid):
    row = con.execute('SELECT question_text,subparts_json FROM exercise_versions WHERE id=? AND course_id=?',
                      (vid, course)).fetchone()
    if row is None:
        raise ValidationError('Question constraint target must belong to this course.')
    return row


def validate_metadata(con, course, vid, metadata):
    """Detach, validate and bind explicitly supplied relations to both texts."""
    metadata = json.loads(json.dumps(metadata))
    source = _version(con, course, vid)
    for field in FIELDS:
        if field not in metadata:
            continue
        links = metadata[field]
        if not isinstance(links, list):
            raise ValidationError(field + ' must be a list.')
        seen = set()
        for link in links:
            if (not isinstance(link, dict) or set(link) - {'exercise_version_id', 'part', 'from_part', 'source_hash', 'target_hash'}
                    or not isinstance(link.get('exercise_version_id'), str) or link['exercise_version_id'] == vid):
                raise ValidationError('Invalid directional question constraint.')
            target = _version(con, course, link['exercise_version_id'])
            for key, version in (('part', target), ('from_part', source)):
                if key not in link:
                    continue
                part = link[key]
                keys = {p if isinstance(p, str) else p.get('key', p.get('subpart_key', p.get('id')))
                        for p in json.loads(version['subparts_json'])}
                if (not isinstance(part, str) or not part.strip() or
                        (part not in keys and not re.search(r'(?m)^\s*'+re.escape(part)+r'\)', version['question_text']))):
                    raise ValidationError('Question constraint references an unknown part.')
            link_identity = (link['exercise_version_id'], link.get('part'), link.get('from_part'))
            if link_identity in seen:
                raise ValidationError('Duplicate question constraint.')
            seen.add(link_identity)
            link['source_hash'] = identity(digest(normalized(source['question_text'])), source['subparts_json'])
            link['target_hash'] = identity(digest(normalized(target['question_text'])), target['subparts_json'])
    return metadata


def apply_known(con, course):
    from .review import QuestionReview
    changed = []
    for vid, (row, metadata) in known_metadata(con, course).items():
        # Partial catalogs are protected at read time; persist once targets exist.
        if any(link['exercise_version_id'].startswith('missing:') for links in metadata.values() for link in links):
            continue
        bound = validate_metadata(con, course, vid, metadata)
        current = json.loads(row['metadata_json'])
        merged = {}
        for field, values in bound.items():
            existing = current.get(field, [])
            keys = {(v['exercise_version_id'], v.get('part'), v.get('from_part')) for v in existing}
            merged[field] = existing + [v for v in values if (v['exercise_version_id'], v.get('part'), v.get('from_part')) not in keys]
        if all(current.get(k) == v for k, v in merged.items()):
            continue
        # Existing links are left unchanged; adding a known link never reattests them.
        additions = {field: [v for v in values if v not in current.get(field, [])] for field, values in merged.items()}
        changes = QuestionReview(con).annotate(course, row['id'], row['revision'], additions)
        metadata = {**current, **merged}
        con.execute('UPDATE question_occurrences SET metadata_json=? WHERE id=?',
                    (json.dumps(metadata, ensure_ascii=False), row['id']))
        changes['metadata'] = metadata
        changed.append(changes)
    return {'annotated': changed, 'count': len(changed)}


def load(con, course):
    """Known original constraints also protect banks cataloged before this repair."""
    rows = {r['id']: dict(r) for r in con.execute(
        'SELECT v.id,f.exact_hash,v.subparts_json FROM exercise_versions v LEFT JOIN question_fingerprints f ON f.exercise_version_id=v.id WHERE v.course_id=?', (course,))}
    links = {vid: {field: [] for field in FIELDS} for vid in rows}
    for q in con.execute('SELECT exercise_version_id,metadata_json FROM question_occurrences WHERE course_id=?', (course,)):
        metadata = json.loads(q['metadata_json'])
        for field in FIELDS:
            for link in metadata.get(field, []):
                target = rows.get(link['exercise_version_id'])
                if (target is None or link.get('source_hash') != identity(rows[q['exercise_version_id']]['exact_hash'], rows[q['exercise_version_id']]['subparts_json'])
                        or link.get('target_hash') != identity(target['exact_hash'], target['subparts_json'])):
                    links[q['exercise_version_id']].setdefault('stale', True)
                links[q['exercise_version_id']][field].append(link)
    for vid, (_, metadata) in known_metadata(con, course).items():
        for field, values in metadata.items():
            existing = {l['exercise_version_id'] for l in links[vid][field]}
            links[vid][field].extend(v for v in values if v['exercise_version_id'] not in existing)
    return links


def ordered_selection(picked, constraints):
    """Stable topological order or None for missing/stale/cyclic/answer-giving sets."""
    selected = set(picked)
    for vid in picked:
        rule = constraints.get(vid, {})
        if rule.get('stale') or any(l['exercise_version_id'] not in selected for l in rule.get('depends_on', [])):
            return None
        if any(l['exercise_version_id'] in selected for l in rule.get('gives_away', [])):
            return None
    result, remaining = [], list(picked)
    while remaining:
        ready = next((v for v in remaining if all(l['exercise_version_id'] in result
                     for l in constraints.get(v, {}).get('depends_on', []))), None)
        if ready is None:
            return None
        result.append(ready)
        remaining.remove(ready)
    return result
