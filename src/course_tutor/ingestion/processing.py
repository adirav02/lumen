"""Explicit, versioned identities for completed whole-ingestion results.

Bump the applicable token whenever extractor, unit builder or catalog output
behavior changes. Unknown implementations/dependencies must never be cache hits.
"""

from dataclasses import dataclass
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform

from .extractors import (
    TextExtractor, PDFExtractor, PPTXExtractor, VisualOnlyExtractor,
    UnsupportedExtractor, get_extractor,
)
from .docx import DOCXExtractor

EXTRACTOR_VERSIONS = {
    TextExtractor: "2", PDFExtractor: "1", PPTXExtractor: "1",
    DOCXExtractor: "1", VisualOnlyExtractor: "1", UnsupportedExtractor: "1",
}
UNIT_BUILDER_VERSION = "1"
CATALOG_VERSION = "4"


def canonical_json(value):
    """Canonical strict JSON; lists retain their semantic order."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def snapshot_configuration(role="reference", catalog_questions=True,
                           structured_units=None, topic_slugs=None, resolved_topics=None):
    """Detach all caller data and record unresolved as well as resolved slugs.

    Topic order/duplicates have no semantic effect on topic links. Structured unit
    ordering and every supplied field (including IDs) remain significant.
    """
    slugs = sorted(set(topic_slugs or []))
    mapping = resolved_topics or {}
    return json.loads(canonical_json({
        "role": role,
        "catalog_questions": catalog_questions,
        "structured_units": structured_units or [],
        "topic_slugs": slugs,
        "resolved_topics": {slug: mapping.get(slug) for slug in slugs},
    }))


@dataclass(frozen=True)
class ProcessingIdentity:
    descriptor_json: str
    fingerprint: str
    reuse_eligible: bool

    @property
    def descriptor(self):
        return json.loads(self.descriptor_json)


def processing_identity(file_path, configuration, extractor=None):
    """Describe processing without extraction; probe output-affecting availability."""
    path = Path(file_path)
    if extractor is None:
        extractor = get_extractor(path)
    cls = type(extractor)
    version = EXTRACTOR_VERSIONS.get(cls)
    eligible = bool(version and UNIT_BUILDER_VERSION and CATALOG_VERSION)
    dependencies = {}
    packages = {PDFExtractor: ("pypdf", "Pillow"), PPTXExtractor: ("python-pptx", "lxml")}.get(cls, ())
    for package in packages:
        try:
            package_version = metadata.version(package)
        except (metadata.PackageNotFoundError, ValueError):
            package_version = None
        if not package_version or not package_version.strip() or package_version.lower() == "unknown":
            package_version = None
            eligible = False
        dependencies[package] = package_version
    dependency_availability = {}
    if cls is PDFExtractor:
        # pypdf's inline-image conversion imports Pillow at runtime. Distribution
        # metadata can remain installed while that import fails; such extraction
        # can silently lose image limitations and must never become reusable.
        try:
            from PIL import Image  # noqa: F401
        except (ImportError, OSError):
            dependency_availability["Pillow"] = False
            eligible = False
        else:
            dependency_availability["Pillow"] = True
    descriptor = {
        "schema_version": 1,
        "extractor": {"id": f"{cls.__module__}.{cls.__qualname__}", "version": version},
        "runtime": {"implementation": platform.python_implementation(), "python": platform.python_version()},
        "dependencies": dependencies,
        "dependency_availability": dependency_availability,
        "suffix": path.suffix.lower(),
        "unit_builder_version": UNIT_BUILDER_VERSION,
        "catalog_version": CATALOG_VERSION,
        "configuration": configuration,
    }
    encoded = canonical_json(descriptor)
    return ProcessingIdentity(encoded, hashlib.sha256(encoded.encode("utf-8")).hexdigest(), eligible)
