"""Offline HTML/MathML and printable PDF export for any saved assessment.

Printing does not mark questions presented, answered or visually verified.
"""

import hashlib
import csv
from html import escape
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from ..errors import ValidationError
from ..student import student_paper


MATH = re.compile(r'\\\((.+?)\\\)|\\\[(.+?)\\\]|\$\$(.+?)\$\$|(?<!\\)\$([^$\n]+)\$|((?:\([^()\s]+\)|[A-Za-z][A-Za-z0-9]*)(?:[_^]\{[^{}\n]+\})+)', re.S)


def browser_executable():
    explicit = os.environ.get('LUMEN_BROWSER_EXECUTABLE')
    if explicit and Path(explicit).is_file() and os.access(explicit, os.X_OK):
        return explicit
    for name in ('google-chrome', 'google-chrome-stable', 'chromium', 'chromium-browser', 'chrome', 'msedge', 'microsoft-edge'):
        if path := shutil.which(name):
            return path
    for path in ('/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
                 '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
                 str(Path(os.environ.get('PROGRAMFILES', 'C:/Program Files'))/'Google/Chrome/Application/chrome.exe')):
        if Path(path).is_file():
            return path
    # Known user browser caches only; never search the filesystem or download.
    caches = [Path.home()/'.cache/ms-playwright', Path.home()/'Library/Caches/ms-playwright']
    if custom := os.environ.get('PLAYWRIGHT_BROWSERS_PATH'):
        caches.insert(0, Path(custom))
    if local := os.environ.get('LOCALAPPDATA'):
        caches.append(Path(local)/'ms-playwright')
    for cache in dict.fromkeys(caches):
        versions = sorted(cache.glob('chromium-*'),
                          key=lambda p: int(p.name.split('-')[-1]) if p.name.split('-')[-1].isdigit() else -1, reverse=True)
        for version in versions:
            for relative in ('chrome-linux64/chrome', 'chrome-linux/chrome', 'chrome-win/chrome.exe',
                             'chrome-win64/chrome.exe', 'chrome-mac/Chromium.app/Contents/MacOS/Chromium'):
                path = version/relative
                if path.is_file() and os.access(path, os.X_OK):
                    return str(path)
    return None


def formatted_text(text):
    """Escape all source markup, rendering only explicit math or simple indices."""
    from latex2mathml.converter import convert
    result, cursor = [], 0
    for match in MATH.finditer(text):
        result.append(escape(text[cursor:match.start()]))
        tex = next(group for group in match.groups() if group is not None)
        if len(tex) > 20000:
            raise ValidationError('Mathematical expression is too long to render.')
        try:
            math = convert(tex, display='block' if match.group(2) is not None or match.group(3) is not None else 'inline')
        except Exception:
            raise ValidationError('A formula could not be rendered; correct its notation before export.') from None
        # latex2mathml emits XML, never host/source HTML or JavaScript.
        result.append('<bdi dir="ltr" class="formula">'+math+'</bdi>')
        cursor = match.end()
    result.append(escape(text[cursor:]))
    return ''.join(result)



def render_question_text(text):
    """Keep source lines; format explicitly delimited CSV data as real tables."""
    lines, parts, index = text.splitlines(), [], 0
    while index < len(lines):
        line = lines[index]
        header = re.fullmatch(r'[A-Za-z_][A-Za-z_0-9]*(?:,[A-Za-z_][A-Za-z_0-9]*)+', line.strip())
        if header:
            rows = list(csv.reader([line]))
            cursor = index+1
            while cursor < len(lines) and lines[cursor].strip():
                row = next(csv.reader([lines[cursor]]))
                if len(row) != len(rows[0]):
                    break
                rows.append(row)
                cursor += 1
            if len(rows) > 1:
                parts.append('<table><thead><tr>'+''.join('<th>'+escape(c)+'</th>' for c in rows[0])+
                             '</tr></thead><tbody>'+''.join('<tr>'+''.join('<td>'+formatted_text(c)+'</td>'
                             for c in row)+'</tr>' for row in rows[1:])+'</tbody></table>')
                index = cursor
                continue
        if line.strip():
            parts.append('<p>'+formatted_text(line)+'</p>')
        index += 1
    return ''.join(parts)

def render_paper_html(paper):
    paper = student_paper(paper)
    text = '\n'.join(q['question_text'] for q in paper['questions'])
    hebrew = len(re.findall(r'[\u0590-\u05ff]', text))
    arabic = len(re.findall(r'[\u0600-\u06ff]', text))
    rtl = hebrew+arabic > len(re.findall('[A-Za-z]', text))
    direction, language = ('rtl', 'he' if hebrew >= arabic else 'ar') if rtl else ('ltr', 'en')
    question_label = {'he': 'שאלה', 'ar': 'سؤال', 'en': 'Question'}[language]
    sections = []
    for question in paper['questions']:
        paragraphs = render_question_text(question['question_text'])
        source = question['source_reference']
        if source:
            labels = list(dict.fromkeys(span.get('label', '') for span in source['source_spans'] if span.get('label')))
            location = ', '.join(labels[:2]) + (' … '+labels[-1] if len(labels)>2 else '')
            citation = f"{source['original_filename']} | v{source['version_num']} | {source['question_key']} | {location}"
        else:
            citation = 'Generated question'
        heading = question_label+' '+str(question['item_order'])
        if question.get('section'):
            heading = str(question['section'])+' · '+heading
        if 'max_points' in question:
            heading += ' · '+str(question['max_points'])+' points'
        for part in question.get('subparts', []):
            wording = part.get('question_text', part.get('text'))
            if wording:
                paragraphs += '<p>'+formatted_text(str(wording))+'</p>'
        sections.append('<section><h2>'+escape(heading)+'</h2><div class="question">'+paragraphs+
                        '</div><p class="source">'+escape(citation)+'</p><div class="answer-space"></div></section>')
    title = escape(paper['title'])
    point_total = (' · '+str(sum(q['max_points'] for q in paper['questions']))+' total points'
                   if all('max_points' in q for q in paper['questions']) else '')
    return f'''<!doctype html><html lang="{language}" dir="{direction}"><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; font-src data:">
<title>{title}</title><style>
@page {{size:A4;margin:18mm}}*{{box-sizing:border-box}}
body{{font-family:Arial,"DejaVu Sans",sans-serif;color:#172537;line-height:1.7;margin:0;font-size:11pt}}
main{{max-width:180mm;margin:auto}}h1{{font-size:23pt;margin:0 0 5mm}}h2{{font-size:15pt;margin:0 0 4mm;border-bottom:1px solid #ccd5df;padding-bottom:2mm}}
p{{margin:2.5mm 0;overflow-wrap:anywhere}}.meta,.source{{font-size:9pt;color:#526477}}
section{{break-before:page}}section:first-of-type{{break-before:auto}}h2,.source{{break-inside:avoid}}
.formula{{direction:ltr;unicode-bidi:isolate}}math{{font-family:"STIX Two Math","Cambria Math",serif}}
table{{border-collapse:collapse;font-size:9pt;width:100%;margin:4mm 0}}
th,td{{border:1px solid #ccd5df;padding:2mm;text-align:start;overflow-wrap:anywhere}}
thead{{display:table-header-group}}tr{{break-inside:avoid}}
.answer-space{{height:45mm;margin:7mm 0;border-bottom:1px solid #d5dde6}}
</style></head><body><main><h1>{title}</h1><p class="meta">{len(paper['questions'])} questions{point_total} · {escape(paper['assessment_id'])}</p>
{''.join(sections)}</main></body></html>'''


def print_pdf(html_path, pdf_path, executable):
    with tempfile.TemporaryDirectory(prefix='lumen-print-profile-') as profile:
        try:
            result = subprocess.run([executable, '--headless', '--disable-background-networking', '--no-first-run',
                '--no-pdf-header-footer', '--user-data-dir='+profile, '--print-to-pdf='+str(pdf_path),
                html_path.as_uri()], capture_output=True, timeout=60)
        except (OSError, subprocess.TimeoutExpired):
            raise ValidationError('PDF renderer unavailable or timed out; no PDF delivery acknowledged.') from None
        if result.returncode or not pdf_path.is_file():
            raise ValidationError('PDF rendering failed; no PDF delivery acknowledged.')


def export_paper(paper, output_directory):
    output = Path(output_directory).resolve()
    fingerprint = paper_fingerprint(paper)
    manifest_path = output/'presentation.json'
    if manifest_path.exists() and json.loads(manifest_path.read_text()).get('paper_sha256') != fingerprint:
        raise ValidationError('Saved paper content changed; preserve the earlier export and use a new version directory.')
    if not browser_executable():
        raise ValidationError('PDF export requires Chrome, Chromium or Edge. Install a supported browser; text output is not a completed test.')
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.lumen-paper-', dir=output) as temporary:
        result = render_staged_paper(paper, temporary)
        for name in ('test.html', 'test.pdf', 'presentation.json'):
            os.replace(Path(temporary)/name, output/name)
    return {**result, 'pdf_path': str(output/'test.pdf'), 'html_path': str(output/'test.html'),
            'manifest_path': str(manifest_path)}


def paper_fingerprint(paper):
    return hashlib.sha256(json.dumps(paper, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()


def render_staged_paper(paper, staging_directory):
    """Render into an existing owned directory; never publish or touch the DB.

    The coordinator owns directory markers/locks and atomic directory publication.
    This primitive refuses to replace any artifact and removes its partial files
    on failure. Its manifest is written last, after readable PDF validation.
    """
    output = Path(staging_directory).resolve()
    paths = [output/name for name in ('test.html', 'test.pdf', 'presentation.json')]
    if not output.is_dir() or any(p.exists() or p.is_symlink() for p in paths):
        raise ValidationError('Staging requires an existing directory without paper artifacts.')
    executable = browser_executable()
    if not executable:
        raise ValidationError('PDF export requires Chrome, Chromium or Edge. Install a supported browser; text output is not a completed test.')
    html_path, pdf_path, manifest_path = paths
    try:
        html_path.write_text(render_paper_html(paper), encoding='utf-8')
        print_pdf(html_path, pdf_path, executable)
        from pypdf import PdfReader
        try:
            if not pdf_path.is_file() or pdf_path.stat().st_size == 0:
                raise ValueError
            pages = len(PdfReader(pdf_path).pages)
            if not pages:
                raise ValueError
        except Exception:
            raise ValidationError('Renderer did not produce a readable PDF.') from None
        manifest = {'assessment_id': paper['assessment_id'], 'paper_sha256': paper_fingerprint(paper),
                    'presentation_status': 'rendered_pending_visual_review', 'page_count': pages,
                    'question_order': [q['exercise_version_id'] for q in paper['questions']],
                    'artifacts': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in (html_path, pdf_path)}}
        manifest_path.write_text(json.dumps(manifest, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    except Exception:
        for path in paths:
            path.unlink(missing_ok=True)
        raise
    return {**manifest, 'pdf_path': str(pdf_path), 'html_path': str(html_path),
            'manifest_path': str(manifest_path),
            'next_step': 'Render and visually inspect every PDF page before delivering its link. Export is not learner presentation or grading.'}


def publish_directory(staging, destination):
    """Linux atomic no-replace rename; never replace even an empty destination."""
    import ctypes
    import errno
    libc = ctypes.CDLL(None, use_errno=True)
    rename = getattr(libc, 'renameat2', None)
    if rename is None:
        raise ValidationError('Atomic no-replace directory publication is unavailable.')
    result = rename(-100, os.fsencode(staging), -100, os.fsencode(destination), 1)
    if result:
        code = ctypes.get_errno()
        if code == errno.EEXIST:
            raise ValidationError('Publication destination already exists.')
        raise OSError(code, os.strerror(code))


def verify_staged_paper(paper, directory):
    """Verify the complete saved set without rewriting earlier published bytes."""
    directory = Path(directory)
    try:
        paths = [directory / name for name in ('test.html', 'test.pdf', 'presentation.json')]
        if directory.is_symlink() or any(p.is_symlink() or not p.is_file() for p in paths):
            raise ValueError()
        manifest = json.loads(paths[2].read_text())
        if (manifest['paper_sha256'] != paper_fingerprint(paper)
                or manifest['presentation_status'] != 'rendered_pending_visual_review'):
            raise ValueError()
        for name in ('test.html', 'test.pdf'):
            if hashlib.sha256((directory/name).read_bytes()).hexdigest() != manifest['artifacts'][name]:
                raise ValueError()
        from pypdf import PdfReader
        try:
            if not paths[1].stat().st_size or len(PdfReader(str(paths[1])).pages) < 1:
                raise ValueError()
        except Exception:
            raise ValueError() from None
    except (OSError, ValueError, KeyError, TypeError):
        raise ValidationError('Published artifact set is incomplete or has changed.') from None
    return {**manifest, 'pdf_path': str(paths[1]),
            'html_path': str(paths[0]), 'manifest_path': str(paths[2]),
            'next_step': 'Render and visually inspect every PDF page before delivering its link. Export is not learner presentation or grading.'}
