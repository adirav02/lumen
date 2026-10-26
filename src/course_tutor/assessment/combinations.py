"""Bounded counts of complete slot assignments, ignoring order within each slot."""
from math import comb

from ..questions.constraints import ordered_selection


def enumerate_exams(slots, candidates, rows, conflicts, constraints, budget):
    slots = sorted(slots, key=lambda s: (len(candidates[s['id']]), s['id']))
    units = [s['id'] for s in slots for _ in range(s['count'])]
    upper = 1
    for slot in slots:
        upper *= comb(len(candidates[slot['id']]), slot['count']) if len(candidates[slot['id']]) >= slot['count'] else 0
    count, witness, nodes, exhausted = 0, None, 0, False

    def visit(index, assignment, picked, families, last):
        nonlocal count, witness, nodes, exhausted
        if nodes >= budget:
            exhausted = True
            return
        nodes += 1
        if index == len(units):
            if ordered_selection([v for _, v in assignment], constraints) is not None:
                count += 1
                if witness is None:
                    witness = assignment[:]
            return
        sid = units[index]
        for vid in candidates[sid]:
            family = rows[vid]['exercise_family']
            if vid <= last.get(sid, '') or family in families or conflicts[vid] & picked:
                continue
            visit(index+1, assignment+[(sid, vid)], picked | {vid}, families | {family}, {**last, sid: vid})
            if exhausted:
                return
    visit(0, [], set(), set(), {})
    return {'lower_bound': count, 'upper_bound': upper if exhausted else count,
            'exact': not exhausted, 'count': count if not exhausted else None,
            'semantics': 'Distinct version-to-slot selections; within-slot order and option permutations ignored. Exams may reuse families across alternatives.',
            'search_nodes_used': nodes}, witness
