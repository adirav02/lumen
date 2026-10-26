"""Explicit, terminal reservation dispositions with publication-lock coordination."""
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os

from ..errors import ConflictError, ValidationError
from ..models import OperationReceipt
from ..storage.db import atomic_transaction
from ..storage.repositories import AssemblyRepository, ReceiptRepository, ReservationRepository
from . import assembly

RESERVATION_TTL_DAYS = 7


def _now():
    return datetime.now(timezone.utc)


def _age_reason(created_at, now):
    try:
        created = datetime.fromisoformat(created_at)
        if created.tzinfo is None or created.utcoffset() is None:
            return 'invalid_timestamp'
        return 'recent' if created > now - timedelta(days=RESERVATION_TTL_DAYS) else None
    except (ValueError, TypeError, OverflowError):
        return 'invalid_timestamp'


def _validate(core, course_id, learner_id, request_id):
    core._verify_not_detached()
    if core.con.in_transaction:
        raise ValidationError('Reservation operations require a connection without an active transaction.')
    for name, value in [('course_id', course_id), ('request_id', request_id)]:
        if not isinstance(value, str) or not value.strip():
            raise ValidationError(name + ' must be a nonempty string.')
    if learner_id is not None and (not isinstance(learner_id, str) or not learner_id.strip()):
        raise ValidationError('learner_id must be a nonempty string or explicit null.')
    if core.con.execute('SELECT 1 FROM courses WHERE id=?', (course_id,)).fetchone() is None:
        raise ValidationError('Reservation course not found.')


def _response(receipt, replay=False):
    result = {'status': 'success', 'receipt': receipt.to_dict(), 'data': receipt.response_data}
    if replay:
        result['idempotent_replay'] = True
    return result


def _run_impl(core, course_id, learner_id, request_id, assessment_id=None, reason=None):
    _validate(core, course_id, learner_id, request_id)
    operation = 'release_reservation' if assessment_id is not None else 'expire_reservations'
    params = {'learner_id': learner_id}
    if assessment_id is not None:
        params.update(assessment_id=assessment_id, reason=reason)
    digest = hashlib.sha256(json.dumps({'operation': operation, 'course_id': course_id,
        'params': params}, sort_keys=True, allow_nan=False).encode()).hexdigest()
    receipts, repo = ReceiptRepository(core.con), ReservationRepository(core.con)
    # Pending assembly IDs have no receipt yet, but still own their mutation key.
    AssemblyRepository(core.con).get(request_id, digest)
    prior = receipts.check_idempotency(request_id, digest)
    if prior:
        return _response(prior, True)
    candidates = ([repo.identity(course_id, learner_id, assessment_id)] if assessment_id is not None
                  else repo.candidates(course_id, learner_id))
    now = _now()
    with ExitStack() as locks:
        blocked = {}
        for candidate in candidates:
            job = candidate['job']
            if job is None or job['state'] == 'published':
                continue
            try:
                fd = assembly._lock(core, job['request_id'])
            except ConflictError:
                blocked[candidate['assessment_id']] = 'active'
                continue
            if fd is not None:
                locks.callback(os.close, fd)
        with atomic_transaction(core.con):
            core._verify_not_detached()
            AssemblyRepository(core.con).get(request_id, digest)
            prior = receipts.check_idempotency(request_id, digest)
            if prior:
                return _response(prior, True)
            released, skipped = [], []
            for old in candidates:
                aid = old['assessment_id']
                current = repo.identity(course_id, learner_id, aid)
                unsafe = blocked.get(aid)
                job = current['job']
                if not unsafe and job and job['state'] != 'published':
                    # Conservatively protect a complete rename even if verification
                    # would currently fail: recovery owns that immutable artifact.
                    if assembly._owned(job, job['final_path'], complete=True):
                        unsafe = 'recovery_required'
                unsafe = unsafe or repo.unused_reason(aid)
                if assessment_id is None:
                    created_at = job['created_at'] if job else current['created_at']
                    unsafe = unsafe or _age_reason(created_at, now)
                if repo.get(aid) is not None and assessment_id is None:
                    unsafe = 'already_released'
                if unsafe:
                    if assessment_id is not None:
                        raise ValidationError('Reservation cannot be released: ' + unsafe + '.',
                                              {'assessment_id': aid, 'reason': unsafe})
                    skipped.append({'assessment_id': aid, 'reason': unsafe})
                    continue
                released.append(repo.release(course_id=course_id, learner_id=learner_id,
                    assessment_id=aid, reason=reason or 'expired', released_at=now.isoformat()))
            data = (released[0] if assessment_id is not None else
                    {'released': released, 'skipped': skipped, 'ttl_days': RESERVATION_TTL_DAYS})
            receipt = OperationReceipt(request_id=request_id, course_id=course_id,
                canonical_request_hash=digest, operation_name=operation,
                affected_ids=[r['assessment_id'] for r in released], response_data=data)
            receipts.record_receipt(receipt)
        return _response(receipt)


def _run(core, course_id, learner_id, request_id, assessment_id=None, reason=None):
    result = _run_impl(core, course_id, learner_id, request_id, assessment_id, reason)
    from .retirement import reconcile
    records = [result['data']] if assessment_id is not None else result['data']['released']
    for record in records:
        reconcile(core, course_id, record['assessment_id'])
    return result


def release_reservation(core, course_id, learner_id, assessment_id, request_id, reason='released'):
    if not isinstance(assessment_id, str) or not assessment_id.strip():
        raise ValidationError('assessment_id must be a nonempty string.')
    if not isinstance(reason, str) or reason not in {'released', 'cancelled'}:
        raise ValidationError('reason must be released or cancelled.')
    return _run(core, course_id, learner_id, request_id, assessment_id, reason)


def expire_reservations(core, course_id, learner_id, request_id):
    return _run(core, course_id, learner_id, request_id)
