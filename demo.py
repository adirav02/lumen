#!/usr/bin/env python3
"""Self-contained synthetic tutoring demo; run with the development environment's Python."""
from pathlib import Path
import tempfile

from course_tutor.api import LumenCore

# End-user demo data lives here, independently of the test fixture collection.
LECTURE = """### Definition: Conditional Probability
Content: P(A|B) = P(A intersection B) / P(B).
Assumptions: P(B) > 0
Symbols: P(B) = marginal probability

### Theorem: Bayes' Theorem
Content: P(A|B) = P(B|A) * P(A) / P(B).
Assumptions: P(B) > 0
Symbols: P(A|B) = posterior probability
Dependencies: Conditional Probability
"""


def demonstrate(root):
    workspace = root / 'workspace'
    with LumenCore(workspace) as core:
        caps = core.capabilities()
        assert caps['runtime']['fts5_supported']
        print('Runtime: SQLite', caps['runtime']['sqlite_version'], 'with FTS5')
        course_id = core.create_course('Synthetic Probability', course_id='prob-demo',
                                       request_id='create-course')['data']['id']
        bayes = core.create_topic(course_id, name="Bayes' Theorem", slug='bayes')
        core.add_topic_alias(course_id, bayes['id'], alias='משפט בייס', language='he')
        poisson = core.create_topic(course_id, name='Poisson Distribution', slug='poisson')
        source = root / 'lecture.txt'
        source.write_text(LECTURE, encoding='utf-8')
        ingested = core.ingest_source(course_id, source, role='lecture', topic_slugs=['bayes'])['data']
        hit = next(h for h in core.search(course_id, 'משפט בייס')['results']
                   if h['title'] == "Bayes' Theorem")
        read = core.read_units(course_id, [hit['unit_id']], expand_dependencies=True)
        assert read['closure_complete'] and read['total_units_returned'] == 2
        unit = next(u for u in read['units'] if u['id'] == hit['unit_id'])
        assert unit['assumptions'] == ['P(B) > 0']
        assert unit['provenance'][0]['source_version_id'] == ingested['source_version_id']
        print('Ingestion: immutable source; Hebrew retrieval; assumptions and prerequisites preserved')

        exercise = core.create_exercise(
            course_id, 'synthetic-bayes',
            'A condition has prevalence 1%. Sensitivity is 90%, specificity is 90%. Find P(D|+).',
            topic_mappings=['bayes'], skill_mappings=['bayes_calc'],
            reference_solution='0.009 / (0.009 + 0.099) = 1/12',
            rubric={'max_points': 10},
        )
        core.validate_exercise_version(
            exercise['exercise_version_id'], expected_revision=1,
            checks={'posterior_calculation': {'status': 'passed', 'reason': '0.009/0.108 = 1/12'}},
        )
        attempt = core.start_attempt(course_id, exercise['exercise_version_id'], learner_id='demo-learner')['data']
        core.record_attempt_event(attempt['id'], expected_revision=1, event_type='hint_request')
        core.record_attempt_event(attempt['id'], expected_revision=2, event_type='hint_given',
                                  content='Include false positives in the denominator.')
        core.record_attempt_event(attempt['id'], expected_revision=3, event_type='work_submission',
                                  content='0.009 / (0.009 + 0.099) = 1/12')
        evidence = core.commit_evidence(attempt['id'], evaluations=[{
            'subpart_key': 'default', 'topic_id': bayes['id'], 'skill_id': 'bayes_calc',
            'correct': True, 'rationale': 'Correct posterior after a hint.',
        }], complete_attempt=True)['data']['evidence_created'][0]
        assert evidence['demonstrated_level'] == 'assisted_success'
        brief = core.course_brief(course_id, learner_id='demo-learner')
        assert brief['coverage']['assessed_topics'][0]['assisted'] == 1
        print('Learning: a correct submission after a hint records assisted success')
        correction = core.correct_evidence(evidence['id'], correction_reason='Synthetic retraction demonstration')['data']
        state = correction['recomputed_topic_states'][bayes['id']]
        assert state['independent_success_count'] == state['assisted_success_count'] == 0
        assessment = core.create_assessment(
            course_id, title='Synthetic diagnostic',
            blueprint={'topic_ids': [bayes['id'], poisson['id']]},
            selected_exercise_version_ids=[exercise['exercise_version_id']],
        )['data']
        progress = core.assessment_progress(assessment['assessment_id'])
        assert progress['coverage']['Poisson Distribution']['assessed'] is False
        print('Audit: retraction recomputes state; unattempted diagnostic topics remain unassessed')
        archive = root / 'snapshot.zip'
        assert core.backup(archive)['source_count'] == 1
    restored = root / 'restored'
    assert LumenCore.restore(archive, restored)['sources_verified'] == 1
    with LumenCore(restored) as core:
        assert core.course_brief(course_id)['course']['name'] == 'Synthetic Probability'
        region = core.read_source_region(ingested['source_version_id'])
        assert region['hash_verified'] and Path(region['absolute_path']).read_bytes() == source.read_bytes()
        assert core.read_units(course_id, [hit['unit_id']], expand_dependencies=True) == read
    print('Backup/restore: source bytes, provenance and retrieval verified')


def main():
    with tempfile.TemporaryDirectory(prefix='lumen-demo-') as directory:
        demonstrate(Path(directory))
    print('DEMO COMPLETE')


if __name__ == '__main__':
    main()
