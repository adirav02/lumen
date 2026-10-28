"""Resolve lexical reference candidates only through reviewed, text-bound links."""
import copy
import re
from ..errors import ValidationError
from ..student import paper_question_text

REFERENCE = re.compile(r'(?P<label>Question|Problem|שאלה)\s+(?P<number>\d+)(?:\s*\((?P<part>[\w]+)\))?', re.I)


def resolve(questions, constraints):
    """Return detached presentation fields; original wording stays in snapshots.

    A lexical hit is not a relationship. Exactly one reviewed dependency must
    identify the target occurrence (including source version), and target part.
    """
    selected = {q['exercise_version_id']: q for q in questions}
    result = []
    for q in questions:
        rule = constraints.get(q['exercise_version_id'], {})
        if rule.get('stale'):
            raise ValidationError('Stale reference relationship; reannotate both current texts.')
        def transform(text, from_part=None):
            def replace(match):
                candidates = []
                for link in rule.get('depends_on', []):
                    if link.get('from_part') not in (None, from_part):
                        continue
                    target = selected.get(link['exercise_version_id'])
                    if not target:
                        continue
                    source = target.get('source_reference') or {}
                    own = q.get('source_reference') or {}
                    explicit = link.get('reference_text') == match.group(0)
                    if (link.get('part') == match['part'] and
                        (explicit or (source.get('source_version_id') == own.get('source_version_id') and
                         source.get('question_key') == match['number']))):
                        candidates.append(target)
                if len(candidates) != 1:
                    raise ValidationError('Unresolved or ambiguous question reference: ' + match.group(0) +
                        '; review depends_on with target exercise version, part and exact reference_text for cross-source references.')
                target = candidates[0]
                if target['item_order'] >= q['item_order']:
                    raise ValidationError('Question reference requires its setup earlier in the paper.')
                return match['label'] + ' ' + str(target['item_order']) + (f"({match['part']})" if match['part'] else '')
            return REFERENCE.sub(replace, text)
        public = copy.deepcopy(q)
        public['presentation_text'] = transform(paper_question_text(q))
        for part in public.get('subparts', []):
            if isinstance(part, dict):
                for field in ('text', 'question_text'):
                    if field in part:
                        part[field] = transform(part[field], part.get('key', part.get('subpart_key', part.get('id'))))
        result.append(public)
    return result


def selection_questions(con, course, selected):
    import json
    questions = []
    for index, vid in enumerate(selected, 1):
        row = con.execute('SELECT question_text,subparts_json FROM exercise_versions WHERE id=?', (vid,)).fetchone()
        source = con.execute('SELECT source_version_id,question_key FROM question_occurrences WHERE exercise_version_id=? AND course_id=?', (vid, course)).fetchone()
        questions.append({'item_order': index, 'exercise_version_id': vid, 'question_text': row['question_text'],
                          'subparts': json.loads(row['subparts_json']), 'source_reference': dict(source) if source else None})
    return questions
