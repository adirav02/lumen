"""Import source/catalog exports into a workspace without importing learner history.

Review retention is explicit and requires matching source, text, teacher reference
and stored rendered evidence. Unchecked questions remain pending.
"""

import argparse
import hashlib
import json
from pathlib import Path

from course_tutor.api import LumenCore


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local(root, name):
    path = (root/name).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError('Collection file is missing or outside its course folder.')
    return path


def import_collection(collection, workspace, retain_reviewed=False):
    collection = Path(collection).resolve()
    prepared = []
    # Validate all originals and optional review evidence before any core writes.
    for manifest in sorted(collection.glob('*/course.json')):
        root = manifest.parent
        data = read(manifest)
        sources = []
        for source in data['sources']:
            path = local(root, source['path'])
            if sha(path) != source['sha256']:
                raise ValueError('Original source hash differs from the course manifest.')
            sources.append((source, path))
        catalog = local(root, 'catalog/questions.jsonl')
        questions = [json.loads(line) for line in catalog.read_text().splitlines() if line.strip()]
        if any(q['course_id'] != data['course_id'] for q in questions):
            raise ValueError('Catalog contains a question from another course.')
        source_hashes = {source['sha256'] for source, _ in sources}
        if any(q['file_hash'] not in source_hashes for q in questions):
            raise ValueError('Catalog references an original missing from the course manifest.')
        references = {}
        ref_path = root/'private/presentation-keys.json'
        if retain_reviewed and ref_path.exists():
            references = {q['id']: q for q in read(ref_path)['questions']}
        evidence = {}
        evidence_path = root/'private/evidence/manifest.json'
        if references and evidence_path.exists():
            for item in read(evidence_path)['question_crops']:
                if sha(local(root, item['file'])) != item['sha256']:
                    raise ValueError('Rendered evidence hash differs from its manifest.')
                evidence.setdefault(item['stable_question_id'], []).append(item)
        title = read(manifest).get('name') or root.name
        if (root/'README.md').exists():
            heading = (root/'README.md').read_text().splitlines()[0]
            if heading.startswith('# '):
                title = heading[2:]
        identity = hashlib.sha256(manifest.read_bytes()+catalog.read_bytes()+
                                  (ref_path.read_bytes() if references else b'')+
                                  (evidence_path.read_bytes() if references and evidence_path.exists() else b'')).hexdigest()
        prepared.append((data, sources, questions, references, evidence, title, identity))
    if not prepared:
        raise ValueError('No course manifests found in this collection.')
    reports = []
    with LumenCore(workspace) as core:
        for data, sources, questions, references, evidence, title, identity in prepared:
            cid = data['course_id']
            def call(op, key, *args, **kw):
                result = getattr(core, op)(*args, **kw, request_id=f'collection:{cid}:{identity}:{op}:{key}')
                return result['data'] if result.get('status') == 'success' and 'data' in result else result
            call('create_course', cid, title, course_id=cid, default_language=data.get('default_language', 'en'))
            uploaded = {}
            for source, path in sources:
                result = call('ingest_source', source['source_label'], cid, path,
                              logical_name=source['source_label'], role=source['role'], catalog_questions=False)
                uploaded[source['sha256']] = result['source_version_id']
            old_to_new = {q['source_version_id']: uploaded[q['file_hash']] for q in questions}
            topic_names = sorted({t for q in questions for t in q.get('metadata', {}).get('topics', [])})
            topics = {name: call('create_topic', name, cid, name,
                                slug='imported-'+hashlib.sha256(name.encode()).hexdigest()[:16])['id']
                      for name in topic_names}
            grouped = {}
            for q in questions:
                ref = references.get(q['exercise_version_id'], {})
                grouped.setdefault(q['source_version_id'], []).append({
                    'question_key': q['question_key'], 'question_text': q['question_text'],
                    'subparts': ref.get('subparts', []),
                    'topic_mappings': [topics[t] for t in q.get('metadata', {}).get('topics', [])],
                    'source_spans': [{k: v for k, v in span.items() if k in ('section_index','start_offset','end_offset')}
                                     for span in q['source_spans']],
                    'quality_flags': q.get('quality_flags', [])})
            actual = {}
            for old_sid, candidates in grouped.items():
                sid = old_to_new[old_sid]
                call('catalog_exam_questions', old_sid, cid, sid, questions=candidates)
                cursor = ''
                while True:
                    page = core.list_questions(cid, sid, limit=100, after_id=cursor)
                    actual.update({(old_sid, q['question_key']): q for q in page['questions']})
                    cursor = page['next_after_id']
                    if cursor is None:
                        break
            retained = 0
            for q in questions:
                current = actual[q['source_version_id'], q['question_key']]
                key = q['id']
                links = [{**link, 'source_version_id': old_to_new[link['source_version_id']]}
                         for link in q.get('solution_links', []) if link['source_version_id'] in old_to_new]
                call('annotate_question', key, cid, current['id'], 1,
                     {**q.get('metadata', {}), 'imported_catalog_hash': identity,
                      'import_origin': str(collection/cid), 'learner_history_imported': False}, solution_links=links)
                ref = references.get(q['exercise_version_id'])
                matches = [e for e in evidence.get(q.get('metadata', {}).get('stable_id'), [])
                           if e['original_sha256'] == q['file_hash'] and e['source_version_id'] == q['source_version_id']]
                # No blanket acceptance of exports or previous learner submissions.
                if not (retain_reviewed and ref and ref.get('validation_state') == 'validated'
                        and ref['question_text'] == q['question_text'] and ref.get('reference_solution')
                        and q['review_status'] == 'accepted' and q['visual_review_status'] == 'verified'
                        and q.get('visual_review_history') and q.get('review_history') and matches):
                    continue
                note = 'Retained recorded review from unchanged course export; source/text/render hashes matched. No learner history imported.'
                call('review_question_occurrence', key, cid, current['id'], 2, 'accepted', note)
                call('review_question_visual', key, cid, current['id'], 3, 'verified', note,
                     checks={'source_render_checked': True, 'formulas_options_diagrams_checked': True,
                             'historical_review_origin': str(collection/cid/'catalog/questions.jsonl')})
                call('validate_exercise_version', key, current['exercise_version_id'], expected_revision=1,
                     expected_question_text=q['question_text'], reference_solution=ref['reference_solution'],
                     rubric=ref.get('rubric', {}), notes=note, reviewer='imported_recorded_review',
                     checks={'recorded_source_review': True, 'recorded_mathematical_review': True,
                             'review_provenance': {'status': 'verified', 'metadata': {'catalog_hash': identity}}})
                retained += 1
            reports.append({'course_id': cid, 'sources': len(sources), 'questions': len(questions),
                            'retained_reviewed_questions': retained, 'learner_history_imported': False})
    return {'workspace': str(Path(workspace).resolve()), 'courses': reports}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('collection', type=Path)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--retain-reviewed', action='store_true')
    args = parser.parse_args()
    print(json.dumps(import_collection(args.collection, args.workspace, args.retain_reviewed), ensure_ascii=False))
