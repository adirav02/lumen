"""Dependency preflight, usable before package installation and without network."""
import ast
import importlib
import importlib.metadata
from pathlib import Path
import re
import shlex
import sys

MODULES = {'python-pptx': 'pptx', 'PyYAML': 'yaml', 'latex2mathml': 'latex2mathml.converter'}


def declared_dependencies(include_dev=True):
    """Read source declarations, or installed distribution metadata in a wheel.

    Literal arrays keep this bootstrap usable on Python 3.10 without tomli.
    """
    source = Path(__file__).resolve().parents[2]/'pyproject.toml'
    if source.exists():
        text = source.read_text()
        declarations = []
        for section, key, group in [('project', 'dependencies', 'runtime'),
                                    ('project.optional-dependencies', 'dev', 'dev'),
                                    ('build-system', 'requires', 'build')]:
            if group == 'dev' and not include_dev:
                continue
            body = text.split('['+section+']', 1)[1].split('\n[', 1)[0]
            match = re.search(r'(?m)^'+key+r'\s*=\s*(\[[\s\S]*?\])', body)
            declarations.extend((spec, group) for spec in ast.literal_eval(match[1]))
        return declarations
    requirements = importlib.metadata.requires('lumen') or []
    return [(spec.split(';')[0].strip(), 'dev' if ';' in spec else 'runtime')
            for spec in requirements if ';' not in spec or include_dev]


def check_dependencies(include_dev=True):
    checks = []
    for spec, group in declared_dependencies(include_dev):
        name = re.match(r'[A-Za-z0-9_.-]+', spec)[0]
        module = MODULES.get(name, name.replace('-', '_'))
        error = None
        try:
            importlib.import_module(module)
        except Exception as exc:
            error = f'{type(exc).__name__}: {exc}'
        checks.append({'dependency': spec, 'group': group, 'module': module,
                       'importable': error is None, 'error': error})
    missing = [item['dependency'] for item in checks if not item['importable']]
    command = shlex.join([sys.executable, '-m', 'pip', 'install', *missing]) if missing else None
    return {'status': 'blocked' if missing else 'ready', 'dependencies': checks,
            'missing': missing, 'install_command': command,
            'offline_hint': 'Use --no-index --find-links /path/to/wheelhouse with the same dependency specs.'}


def preflight_message(report):
    return ('Missing required dependencies: '+', '.join(report['missing'])+'\n'
            'Install: '+report['install_command']+'\n'+report['offline_hint'])
