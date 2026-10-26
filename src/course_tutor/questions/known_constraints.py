"""Hash-bound HN101 review annotations; originals and review gates stay unchanged."""
import re

# Reviewed against unchanged HN101 final papers. Keys are immutable original hashes.
KNOWN = {
    '4229b2ab967c5ed2dbd8526388fd2a6c6c88bd5e0d9b4ff097804fb37f3ff44f': {
        '2': {'depends_on': [('1', 'a')]},
        '8': {'gives_away': [('3', 'a'), ('7', 'a')]}},
    '92292723d8fd9235834e42e52f310aa0c103a25269619453f3ac8e5252faf9d7': {
        '2': {'depends_on': [('1', 'b')]},
        '8': {'gives_away': [('1', 'b')]}},
    'c82dda13fff564ede7a317e8350b2f03145d5d06fb36debc9aa22ec139700c75': {
        '2': {'depends_on': [('1', 'a')]},
        '8': {'depends_on': [('1', None)], 'gives_away': [('2', 'a')]}},
}

# These common rules were checked in all five unchanged final-examination sources.
INSTRUCTIONS = [
    'Answer all questions.', 'Calculator permitted.', 'Carry full precision until display.',
    'All cases are fictional. Use extra paper as needed; label each answer by question and part.',
    'No physical test is required.',
]
INSTRUCTION_HASHES = set(KNOWN) | {
    '2625b75b73caaeb0fde9fc8e29e3a586ecae744a9a44290718521e1646139109',
    'bc641c02418f30cbe5ac05bf769b8b1ff01229c702bbfc1493b3bfe18ed6b903',
}


def paper_settings(con, selected, blueprint):
    result = dict(blueprint or {})
    if 'instructions' not in result:
        for vid in selected:
            row = con.execute('''SELECT s.file_hash FROM question_occurrences q JOIN source_versions s
                ON s.id=q.source_version_id WHERE q.exercise_version_id=?''', (vid,)).fetchone()
            if row and row['file_hash'] in INSTRUCTION_HASHES:
                result['instructions'] = list(INSTRUCTIONS)
                break
    return result

def known_metadata(con, course):
    if 'metadata_json' not in {r[1] for r in con.execute('PRAGMA table_info(question_occurrences)')}:
        return {}  # Migration 9 catalogs before metadata is introduced in v10.
    rows = list(con.execute('''SELECT q.id,q.exercise_version_id,q.question_key,q.metadata_json,q.revision,
        q.source_version_id,s.file_hash FROM question_occurrences q
        JOIN source_versions s ON s.id=q.source_version_id WHERE q.course_id=?''', (course,)))
    def normal_key(value):
        match = re.search(r'(?:^Q|^|[-_]Q)0*([1-8])$', value)
        return match[1] if match else value
    lookup = {(r['source_version_id'], normal_key(r['question_key'])): r for r in rows}
    result = {}
    for row in rows:
        rules = KNOWN.get(row['file_hash'], {}).get(normal_key(row['question_key']), {})
        if not rules:
            continue
        metadata = {}
        for field, targets in rules.items():
            links = []
            for key, part in targets:
                target = lookup.get((row['source_version_id'], key))
                # An absent prerequisite must still block assembly, even in partial catalogs.
                link = {'exercise_version_id': target['exercise_version_id'] if target else 'missing:'+row['source_version_id']+':'+key}
                if part:
                    link['part'] = part
                links.append(link)
            metadata[field] = links
        result[row['exercise_version_id']] = (row, metadata)
    return result


