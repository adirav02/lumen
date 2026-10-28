"""Instructor-only next operations over the existing readiness exclusions."""


def actions(slot, rows, constraints):
    blocked = {}
    for reason, group in slot['exclusions'].items():
        if reason.startswith(('extraction_', 'visual_', 'math_')) or reason in (
                'missing_required_metadata', 'question_constraints', 'missing_family'):
            for vid in group['version_ids']:
                blocked.setdefault(vid, set()).add(reason)
    result = []
    for vid, reasons in sorted(blocked.items()):
        row = rows[vid]
        operations = []
        def add(operation, target, inputs, requirement):
            operations.append({'operation': operation, 'target': target,
                               'required_inputs': inputs, 'review_requirement': requirement})
        for q in row['occurrences']:
            target = {'occurrence_id': q['id'], 'expected_revision': q['revision']}
            if any(r.startswith('extraction_') for r in reasons):
                add('review-question-occurrence', target, ['status', 'notes'],
                    'Compare complete wording and locations with the original; retain rejected or uncertain status when appropriate.')
            if any(r.startswith('visual_') for r in reasons):
                add('review-question-visual', target, ['status', 'notes', 'checks'],
                    'Open the actual source image/page and inspect formulas, diagrams and options before attesting verification.')
            fields = [f for f, group in slot['unknown_required_metadata'].items()
                      if vid in group['version_ids'] and f != 'reviewed_provenance']
            if fields or reasons & {'question_constraints'}:
                add('annotate-question', target, ['metadata'],
                    'Supply reviewed metadata or reattest current depends_on/gives_away links; never remove a real dependency merely to fit the blueprint.')
        if any(r.startswith('math_') for r in reasons):
            add('validate-exercise-version', {'version_id': vid, 'expected_revision': row['revision']},
                ['checks', 'reference_solution', 'rubric'],
                'After extraction review, independently recompute the answer and review the rubric for this exact revision.')
        rule = constraints.get(vid, {})
        result.append({'exercise_version_id': vid, 'blockers': sorted(reasons),
                       'reference_issue': 'Reannotate the current source and target text/subpart identities.' if rule.get('stale') else None,
                       'stale_relationship': bool(rule.get('stale')),
                       'required_prerequisite_version_ids': sorted({l['exercise_version_id'] for l in rule.get('depends_on', [])}),
                       'operations': operations,
                       'note': 'Operations are suggestions, not approvals. Re-read revisions after each mutation; include real prerequisite context in a matching blueprint slot.'})
    return result
