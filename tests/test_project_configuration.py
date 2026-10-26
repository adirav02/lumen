"""Static routing and release safety; these do not launch an agent or Actions."""

from pathlib import Path
import re

import yaml

ROOT = Path(__file__).resolve().parents[1]


def frontmatter(path):
    return yaml.safe_load(path.read_text().split('---', 2)[1])


def test_claude_exposes_each_shared_skill_without_workflow_copies():
    canonical = ROOT / '.agents/skills'
    pointers = ROOT / '.claude/skills'
    assert {p.name for p in canonical.iterdir()} == {p.name for p in pointers.iterdir()}
    for skill in canonical.glob('*/SKILL.md'):
        pointer = pointers / skill.parent.name / 'SKILL.md'
        assert frontmatter(pointer) == frontmatter(skill)
        text = pointer.read_text()
        targets = [(pointer.parent / target).resolve() for target in re.findall(r'\]\(([^)]+)\)', text)]
        assert skill.resolve() in targets
        assert all(target.is_file() for target in targets)


def test_claude_profiles_use_native_fields_and_bounded_tools():
    profiles = list((ROOT / '.claude/agents').glob('course-*.md'))
    expected = {'lookup': 'haiku', 'practice': 'sonnet', 'reasoning': 'opus'}
    assert len(profiles) == len(expected)
    for role, model in expected.items():
        profile = ROOT / f'.claude/agents/course-{role}.md'
        data = frontmatter(profile)
        assert set(data) == {'name', 'description', 'tools', 'model'}
        assert data['name'] == f'course-{role}'
        assert data['model'] == model and data['description']
        tools = set(data['tools'].split(', '))
        assert 'Bash' in tools and 'Read' in tools and 'Agent' not in tools
        if role != 'practice':
            assert not tools & {'Write', 'Edit'}


def test_release_requires_reusable_ci_and_publishes_its_artifact():
    # BaseLoader preserves GitHub's "on" key rather than YAML 1.1's boolean True.
    ci = yaml.load((ROOT / '.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
    release = yaml.load((ROOT / '.github/workflows/release.yml').read_text(), Loader=yaml.BaseLoader)
    assert 'workflow_call' in ci['on']
    assert release['jobs']['checks']['uses'] == './.github/workflows/ci.yml'
    assert release['jobs']['checks']['needs'] == 'validate-tag'
    assert release['jobs']['release']['needs'] == 'checks'
    publish = release['jobs']['release']['steps'][-1]['run']
    assert '--draft' in publish
    assert ci['permissions'] == release['permissions'] == {'contents': 'read'}
    assert release['jobs']['release']['permissions'] == {'contents': 'write'}
    upload = ci['jobs']['package']['steps'][-1]
    download = release['jobs']['release']['steps'][0]
    assert upload['with']['name'] == download['with']['name'] == 'distributions'
    assert ci['concurrency']['group'].startswith('ci-')
    assert release['concurrency']['group'].startswith('release-')
    for workflow in (ci, release):
        for job in workflow['jobs'].values():
            for step in job.get('steps', []):
                if 'uses' in step:
                    assert re.fullmatch(r'[\w/-]+@[0-9a-f]{40}', step['uses'])


def test_ci_uses_the_test_wrapper_and_preserves_junit_results():
    workflow = yaml.load((ROOT / '.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
    commands = [step.get('run', '') for step in workflow['jobs']['test']['steps']]
    assert any('python scripts/run_tests.py' in command and
               '--junitxml=test-results/pytest.xml' in command for command in commands)
    assert all('python -m pytest' not in command for command in commands)
    build_steps = workflow['jobs']['package']['steps']
    assert any('python scripts/build_public.py' in step.get('run', '') for step in build_steps)


def test_ci_preserves_runtime_gates_and_isolated_distribution_smoke():
    ci = yaml.load((ROOT / '.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
    assert ci['jobs']['test']['strategy']['matrix']['python-version'] == [
        '3.10', '3.11', '3.12', '3.13', '3.14', '3.15']
    commands = '\n'.join(step.get('run', '') for step in ci['jobs']['test']['steps'])
    assert '.[dev]' in commands
    assert 'scripts/check_docs.py' in commands and 'scripts/sync_agents.py --check' in commands
    assert 'browser_executable' in commands and 'raise SystemExit' in commands
    assert 'lumen capabilities' in commands and 'python demo.py' in commands
    package = '\n'.join(step.get('run', '') for step in ci['jobs']['package']['steps'])
    assert 'scripts/check_release_version.py' in package and 'twine check dist/*' in package
    assert 'scripts/smoke_installed.py --wheel dist/*.whl' in package
    assert 'examples/' not in package
    for workflow in (ci, yaml.load((ROOT / '.github/workflows/release.yml').read_text(), Loader=yaml.BaseLoader)):
        for job in workflow['jobs'].values():
            assert 'continue-on-error' not in job
            if 'uses' not in job:
                assert int(job['timeout-minutes']) > 0
            for step in job.get('steps', []):
                assert 'continue-on-error' not in step


def test_workflow_embedded_shell_parses_and_release_cannot_rebuild_artifacts(tmp_path):
    import subprocess
    for path in (ROOT / '.github/workflows').glob('*.yml'):
        workflow = yaml.load(path.read_text(), Loader=yaml.BaseLoader)
        assert workflow['name'] and workflow['on'] and workflow['jobs']
        for job in workflow['jobs'].values():
            for index, step in enumerate(job.get('steps', [])):
                if 'run' in step:
                    script = tmp_path / f'{path.stem}-{index}.sh'
                    script.write_text(step['run'])
                    result = subprocess.run(['bash', '-n', str(script)], capture_output=True, text=True)
                    assert result.returncode == 0, result.stderr
    release = yaml.load((ROOT / '.github/workflows/release.yml').read_text(), Loader=yaml.BaseLoader)
    job = release['jobs']['release']
    assert 'if' not in job  # Default success() dependency gate must apply.
    assert all('if' not in step for step in job['steps'])
    commands = '\n'.join(step.get('run', '') for step in job['steps'])
    assert '--verify-tag' in commands and 'dist/*' in commands and '--draft' in commands
    assert 'build' not in commands and 'pip' not in commands


def test_ci_uploads_compact_runner_diagnostics_even_on_failure():
    ci = yaml.load((ROOT / '.github/workflows/ci.yml').read_text(), Loader=yaml.BaseLoader)
    uploads = [s for s in ci['jobs']['test']['steps'] if 'actions/upload-artifact@' in s.get('uses', '')]
    assert len(uploads) == 1
    assert uploads[0]['if'] == '${{ always() }}'
    config = uploads[0]['with']
    assert set(config['path'].splitlines()) == {'test-results/*.xml', '.tmp/test-last.log'}
    assert config['include-hidden-files'] == 'true'
