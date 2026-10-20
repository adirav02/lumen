"""Filename hints never establish a verified exam date for selection."""
import re
from ..errors import ValidationError


def filename_provenance(filename):
    years = sorted({int(y) for y in re.findall(r'(?<!\d)(?:19|20|21)\d{2}(?!\d)', filename)})
    return {'filename_years': years, 'year_provenance': 'filename', 'year': None} if years else {}


def normalize_metadata(metadata):
    result = dict(metadata)
    origin = result.get('year_provenance')
    if origin is not None and origin not in ('filename', 'unverified', 'verified_exam_date'):
        raise ValidationError('year_provenance must be filename, unverified or verified_exam_date.')
    if origin == 'filename' and result.get('year') is not None:
        result['filename_years'] = sorted(set(result.get('filename_years', [])) | {result['year']})
        result['year'] = None
    if origin == 'verified_exam_date' and (not isinstance(result.get('year_evidence'),str) or not result['year_evidence'].strip()):
        raise ValidationError('Verified exam year requires year_evidence naming the source/date location.')
    return result


def verified_year(metadata):
    year = metadata.get('year')
    if (metadata.get('year_provenance') == 'verified_exam_date'
            and isinstance(metadata.get('year_evidence'),str) and metadata['year_evidence'].strip()
            and type(year) is int and 1900 <= year <= 2200):
        return year
    return None
