# TL;DR: Run pytest with a compact summary and a complete local log.
# Status: active; date: 2026-10-19.
"""Usage: python development/scripts/run_tests.py [--fail-on-skip] [pytest arguments]."""
import json
import re
from pathlib import Path
import subprocess
import sys
import tempfile
from _test_receipt import save_receipt, tree_identity

ROOT = Path(__file__).resolve().parents[2]


class Summary:
    def __init__(self):
        self.passed = 0
        self.skipped = 0
        self.failures = {}

    def record(self, report):
        if report.failed:
            crash = getattr(report.longrepr, 'reprcrash', None)
            rendered = str(report.longrepr)
            location = getattr(report, 'location', (report.nodeid, None))
            file_lines = re.findall(r'File "([^"]+)", line (\d+)', rendered)
            file_line = (f'{crash.path}:{crash.lineno}' if crash else
                         ':'.join(file_lines[-1]) if file_lines else
                         f'{location[0]}:{(location[1] or 0) + 1}')
            errors = [line[-300:] for line in rendered.splitlines()
                      if re.match(r'^E(?:\s|$)', line)]
            self.failures.setdefault(report.nodeid, {
                'location': file_line,
                'errors': errors[-2:],
            })

    def pytest_runtest_logreport(self, report):
        if report.when == 'call' and report.passed:
            self.passed += 1
        if report.skipped:
            self.skipped += 1
        self.record(report)

    def pytest_collectreport(self, report):
        if report.skipped:
            self.skipped += 1
        self.record(report)


def child(result_path, args):
    import pytest

    summary = Summary()
    code = pytest.main(['-q', *args], plugins=[summary])
    Path(result_path).write_text(json.dumps({
        'passed': summary.passed, 'skipped': summary.skipped, 'failures': summary.failures,
    }))
    return int(code)


def main(args):
    fail_on_skip = '--fail-on-skip' in args
    pytest_args = [arg for arg in args if arg != '--fail-on-skip']
    log_path = ROOT / '.tmp/test-last.log'
    log_path.parent.mkdir(parents=True, exist_ok=True)
    receipt_path = ROOT / '.tmp/test-receipt.json'
    receipt_path.unlink(missing_ok=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'src'))
    from course_tutor.doctor import check_dependencies, preflight_message
    dependencies = check_dependencies()
    if dependencies['missing']:
        message = preflight_message(dependencies)
        log_path.write_text(message+'\n')
        print(message)
        return 2
    before = tree_identity(ROOT)
    with tempfile.TemporaryDirectory(prefix='lumen-tests-') as directory:
        result_path = Path(directory) / 'summary.json'
        with log_path.open('w') as log:
            result = subprocess.run(
                [sys.executable, str(Path(__file__).resolve()),
                 '--_pytest-child', str(result_path), *pytest_args],
                stdout=log, stderr=subprocess.STDOUT,
            )
        summary = json.loads(result_path.read_text()) if result_path.exists() else {}
    code = result.returncode
    if code == 0 and fail_on_skip and summary.get('skipped'):
        message = f"FAIL: {summary['skipped']} skipped tests (--fail-on-skip requires complete execution)"
        print(message)
        with log_path.open('a') as log:
            log.write(message + '\n')
        code = 1
    if code == 0:
        receipt = save_receipt(ROOT, before, summary.get('passed', 0), args)
        print(f"PASS {summary.get('passed', 0)} tests")
        if summary.get('skipped'):
            print(f"SKIP {summary['skipped']} tests (reasons in {log_path})")
        if not receipt['tree_unchanged']:
            print('Receipt does not match: working tree changed during tests')
    else:
        for nodeid, failure in list(summary.get('failures', {}).items())[:15]:
            print(f"{nodeid} ({failure['location']})")
            for line in failure['errors']:
                print(line)
        print(log_path)
    return code


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == '--_pytest-child':
        raise SystemExit(child(sys.argv[2], sys.argv[3:]))
    raise SystemExit(main(sys.argv[1:]))
