"""Host declarations and marker observations, never integration certification."""
import os
from .errors import ValidationError

HOSTS = ('generic_cli', 'codex', 'claude_code', 'antigravity')


def detect_host(override=None):
    declared = override if override is not None else os.environ.get('LUMEN_HOST')
    if declared is not None:
        declared = declared.replace('-', '_')
        if declared not in HOSTS:
            raise ValidationError('host must be one of: '+', '.join(HOSTS))
        return {'host': declared, 'method': 'override',
                'evidence': '--host' if override is not None else 'LUMEN_HOST',
                'verified': False, 'note': 'Caller declaration; native host integration is not verified.'}
    markers = {'claude_code': ('CLAUDE_CODE', 'ANTHROPIC'),
               'codex': ('CODEX', 'OPENAI', 'CODEX_THREAD_ID'),
               'antigravity': ('ANTIGRAVITY', 'GEMINI')}
    matches = [(host, key) for host, keys in markers.items() for key in keys if key in os.environ]
    hosts = {host for host, key in matches}
    if len(hosts) == 1:
        return {'host': matches[0][0], 'method': 'marker', 'evidence': [key for host, key in matches],
                'verified': False, 'note': 'Environment marker observation; native integration is not verified.'}
    return {'host': 'generic_cli', 'method': 'fallback', 'evidence': None, 'verified': False,
            'note': 'Conflicting host markers.' if matches else 'No host declaration or recognized marker.'}
