"""Opt-in finite answer sets for scalar submitted work, with no answer exposure."""
import json
import math
from ..errors import ValidationError


def accepts_answer(rubric, key, submitted_text):
    rule = rubric.get('answer_sets', {}).get(key)
    if not isinstance(rule, dict) or set(rule) != {'values'} or not isinstance(rule['values'], list) or not rule['values']:
        raise ValidationError('A checked private answer set with finite numeric values is required.')
    values = rule['values']
    if any(type(value) not in (int,float) or not math.isfinite(value) for value in values):
        raise ValidationError('Answer sets must contain only finite numeric values.')
    try:
        submitted = json.loads(submitted_text)
    except (ValueError, TypeError):
        raise ValidationError('Answer-set evaluation requires a scalar numeric submission; use tutor evaluation for worked solutions.') from None
    if type(submitted) not in (int,float) or not math.isfinite(submitted):
        raise ValidationError('Answer-set evaluation requires a finite numeric submission.')
    return submitted in values
