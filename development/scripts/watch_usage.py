# TL;DR: Start the existing usage watcher with a label using system Python only.
# Status: active; date: 2026-10-26.
"""Run before bootstrap; Ctrl-C/SIGTERM collects a final snapshot and stops."""
import argparse
import json
from pathlib import Path
import re
import signal
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--label', required=True, help='Safe run label, e.g. solo-default')
    parser.add_argument('--project', type=Path, default=ROOT)
    parser.add_argument('--host', action='append', choices=('codex', 'claude', 'antigravity', 'antigravity-app'))
    parser.add_argument('--usage-log-location', action='append')
    parser.add_argument('--duration-seconds', type=float)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', args.label):
        parser.error('label must contain only letters, digits, hyphens or underscores')
    from course_tutor.usage_collector import collect_usage, watch_usage

    def interrupt(signum, frame):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)
    params = dict(log_path=args.project / '.tmp/usage' / args.label / 'usage.jsonl',
                  project_path=args.project, hosts=args.host, log_locations=args.usage_log_location)
    emit = lambda event: print(json.dumps({'label': args.label, **event}), flush=True)
    emit({'event': 'started', 'log_path': str(params['log_path'])})
    try:
        result = watch_usage(**params, duration_seconds=args.duration_seconds, emit=emit)
    except KeyboardInterrupt:
        result = {'stopped': 'interrupt'}
    finally:
        # Finish outside the interrupted poll so the last observed counters persist.
        collect_usage(**params)
    emit({'event': 'stopped', **result})


if __name__ == '__main__':
    main()
