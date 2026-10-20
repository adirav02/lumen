"""Read OOXML without flattening fractions/indices or inventing Word page numbers."""

from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

from ..errors import ValidationError

W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
M = '{http://schemas.openxmlformats.org/officeDocument/2006/math}'


def _text(node):
    if node is None:
        return ''
    local = node.tag.rsplit('}', 1)[-1]
    if local.endswith('Pr') or node.tag in (W+'del', W+'instrText'):
        return ''
    if node.tag in (W+'t', M+'t'):
        return node.text or ''
    if node.tag == W+'tab':
        return '\t'
    if node.tag in (W+'br', W+'cr'):
        return '\n'
    if node.tag == W+'tc':
        return '\n'.join(_text(child) for child in node if child.tag in (W+'p', W+'tbl'))
    if node.tag == M+'f':
        return '(' + _text(node.find(M+'num')) + ')/(' + _text(node.find(M+'den')) + ')'
    if node.tag in (M+'sSub', M+'sSup', M+'sSubSup'):
        base = '(' + _text(node.find(M+'e')) + ')'
        sub, sup = node.find(M+'sub'), node.find(M+'sup')
        return base + ('_{'+_text(sub)+'}' if sub is not None else '') + ('^{'+_text(sup)+'}' if sup is not None else '')
    if node.tag == M+'rad':
        return 'root(' + _text(node.find(M+'deg')) + ';' + _text(node.find(M+'e')) + ')'
    if node.tag == M+'nary':
        char = node.find(M+'naryPr/'+M+'chr')
        operator = char.get(M+'val', '∫') if char is not None else '∫'
        return operator + '_{'+_text(node.find(M+'sub'))+'}^{'+_text(node.find(M+'sup'))+'}(' + _text(node.find(M+'e')) + ')'
    if node.tag == M+'d':
        props = node.find(M+'dPr')
        begin, end = '(', ')'
        if props is not None:
            b, e = props.find(M+'begChr'), props.find(M+'endChr')
            begin = b.get(M+'val', '(') if b is not None else '('
            end = e.get(M+'val', ')') if e is not None else ')'
        return begin + ';'.join(_text(e) for e in node.findall(M+'e')) + end
    if node.tag == M+'m':
        return '[' + '; '.join(', '.join(_text(e) for e in row.findall(M+'e')) for row in node.findall(M+'mr')) + ']'
    if node.tag in (M+'limLow', M+'limUpp'):
        return _text(node.find(M+'e')) + ('_{' if local == 'limLow' else '^{') + _text(node.find(M+'lim')) + '}'
    if node.tag == M+'eqArr':
        return '\n'.join(_text(e) for e in node.findall(M+'e'))
    return ''.join(_text(child) for child in node)


class DOCXExtractor:
    """Text + original math XML per block; layout and every equation need review."""

    def extract(self, file_path: Path):
        from .extractors import ExtractedSection
        try:
            return self._extract(file_path)
        except (BadZipFile, ET.ParseError) as exc:
            return [ExtractedSection(0, 'Unreadable DOCX', '', quality_flag='unsupported',
                notes=f'DOCX archive/XML could not be read ({type(exc).__name__}); retain original for repair and review.')]

    def _extract(self, file_path: Path):
        from .extractors import ExtractedSection
        with ZipFile(file_path) as archive:
            if sum(info.file_size for info in archive.infolist()) > 100 * 1024 * 1024:
                raise ValidationError('DOCX uncompressed content exceeds the 100 MiB extraction limit.')
            if 'word/document.xml' not in archive.namelist():
                raise ValidationError('DOCX is missing word/document.xml.')
            names = ['word/document.xml'] + sorted(name for name in archive.namelist() if
                name.startswith(('word/header', 'word/footer')) and name.endswith('.xml'))
            sections = []
            for name in names:
                data = archive.read(name)
                if len(data) > 20 * 1024 * 1024:
                    raise ValidationError('DOCX XML part exceeds the 20 MiB extraction limit.')
                root = ET.fromstring(data)
                container = root.find(W+'body') if name == 'word/document.xml' else root
                if container is None:
                    raise ValidationError('DOCX document has no body.')
                paragraph = 0
                for index, block in enumerate(container):
                    if block.tag not in (W+'p', W+'tbl'):
                        continue
                    if block.tag == W+'p':
                        paragraph += 1
                        text = _text(block)
                        label = f'Paragraph {paragraph}'
                    else:
                        text = '\n'.join('\t'.join(_text(cell) for cell in row.findall(W+'tc')) for row in block.findall(W+'tr'))
                        label = f'Table at block {index + 1}'
                    maths = block.findall('.//'+M+'oMath')
                    images = bool(block.findall('.//'+W+'drawing') or block.findall('.//'+W+'pict'))
                    highlighted = bool(block.findall('.//'+W+'highlight') or block.findall('.//'+W+'shd'))
                    quality = 'has_images' if images else 'uncertain_math' if maths else 'clean' if text.strip() else 'empty'
                    notes = []
                    if maths:
                        notes.append('OMML equations retained as XML with a linear search representation; visual/formula verification required.')
                    if images:
                        notes.append('Embedded drawings/images require visual inspection.')
                    if highlighted:
                        notes.append('Source contains highlighting/shading that may reveal an answer; remove correctness cues from student presentations.')
                    sections.append(ExtractedSection(len(sections), label, text, quality_flag=quality,
                        notes=' '.join(notes), metadata={'document_part': name, 'block_index': index,
                        'paragraph_index': paragraph - 1 if block.tag == W+'p' else None,
                        'math_xml': [ET.tostring(m, encoding='unicode') for m in maths],
                        'has_images': images, 'page_index_available': False,
                        'has_highlight_or_shading': highlighted,
                        'rtl': block.find('.//'+W+'bidi') is not None}))
            return sections or [ExtractedSection(0, 'Document', '', quality_flag='empty', notes='No text blocks in DOCX.')]
