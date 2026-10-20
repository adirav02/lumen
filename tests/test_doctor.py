"""Bootstrap reports declarations and actionable missing imports without pytest tracebacks."""
from course_tutor import doctor


def test_doctor_lists_all_declared_dependencies():
    report = doctor.check_dependencies()
    assert {'pypdf', 'pptx', 'latex2mathml.converter', 'pytest', 'yaml', 'setuptools', 'wheel'} == {
        item['module'] for item in report['dependencies']}


def test_missing_import_has_exact_install_command(monkeypatch):
    monkeypatch.setattr(doctor, 'declared_dependencies', lambda dev: [('pypdf>=4.0.0', 'runtime')])
    def missing(name):
        raise ImportError('synthetic offline probe')
    monkeypatch.setattr(doctor.importlib, 'import_module', missing)
    report = doctor.check_dependencies()
    assert report['status'] == 'blocked'
    assert report['missing'] == ['pypdf>=4.0.0']
    assert "'pypdf>=4.0.0'" in report['install_command']
    assert 'synthetic offline probe' in report['dependencies'][0]['error']
