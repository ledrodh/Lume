from __future__ import annotations

import json
import platform
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.1.0"


class PageClassification(str, Enum):
    EXTRACTABLE_TEXT = "extractable_text"
    IMAGE_ONLY = "image_only"
    MIXED = "mixed"
    EMPTY_OR_UNKNOWN = "empty_or_unknown"


@dataclass
class PageDiagnostics:
    page_number: int
    width: float
    height: float
    rotation: int
    classification: str
    char_count: int
    image_occurrences: int
    distinct_images: int
    image_area_ratio: float
    footnote_candidates: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DocumentDiagnostics:
    file_path: str
    file_name: str
    total_pages: int
    embedded_title: str = ""
    embedded_author: str = ""
    first_page_width: float = 0.0
    first_page_height: float = 0.0
    wide_first_page_candidate: bool = False
    extractable_text_pages: int = 0
    image_only_pages: int = 0
    mixed_pages: int = 0
    empty_or_unknown_pages: int = 0
    total_image_occurrences: int = 0
    total_distinct_images: int = 0
    estimated_footnote_candidates: int = 0
    cmap_scan_completed: bool = False
    cmap_issues_detected: int = 0
    cmap_repair_candidates: list[int] = field(default_factory=list)
    recommended_ocr_mode: str = "full_ocr"
    classification_confidence: float = 0.0
    is_complete: bool = False
    pages: list[PageDiagnostics] = field(default_factory=list)

    def to_dict(self, include_pages: bool = True, include_file_path: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if not include_pages:
            data.pop("pages", None)
        if not include_file_path:
            data.pop("file_path", None)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocumentDiagnostics:
        raw_pages = data.get("pages", [])
        pages = [
            p if isinstance(p, PageDiagnostics) else PageDiagnostics(**p)
            for p in raw_pages
        ]
        filtered = {k: v for k, v in data.items() if k != "pages"}
        if "file_path" not in filtered:
            filtered["file_path"] = filtered.get("file_name", "")
        return cls(**filtered, pages=pages)


@dataclass
class TransformationSample:
    sample_id: str
    category: str
    source_pages: list[int]
    original_excerpt: str
    restored_excerpt: str
    description: str
    block_ids: list[str] = field(default_factory=list)
    match_method: str = "unresolved"  # "marker_block_id" | "page_text_match" | "unresolved"
    ambiguous: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TransformationEntry:
    operation: str
    category: str  # "operational" | "structural"
    status: str  # "success" | "skipped" | "failed"
    inspected_count: int = 0
    transformed_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    source_pages: list[int] = field(default_factory=list)
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationIssue:
    severity: str  # "error" | "warning" | "info"
    code: str
    location: str
    message: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ValidationSummary:
    is_valid: bool
    validator_name: str = "Lume Internal OCF/EPUB Validator"
    checked_files: int = 0
    checked_links: int = 0
    broken_links: int = 0
    mimetype_ok: bool = False
    container_xml_ok: bool = False
    opf_manifest_ok: bool = False
    xhtml_well_formed_ok: bool = False
    issues: list[ValidationIssue] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class HealingStats:
    """Collects operational and structural telemetry during the HTML Triple-Pass."""
    footnotes_extracted: int = 0
    footnotes_linked: int = 0
    footnotes_unlinked: int = 0
    paragraphs_stitched: int = 0
    paragraphs_inspected: int = 0
    leaked_pages_removed: int = 0
    false_sups_unwrapped: int = 0
    em_dashes_normalized: int = 0
    toc_tables_inspected: int = 0
    toc_entries_rebuilt: int = 0
    samples: list[TransformationSample] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class RestorationReport:
    schema_version: str = SCHEMA_VERSION
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_utc: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    input_metadata: dict[str, Any] = field(default_factory=dict)
    environment: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)
    operational_metrics: dict[str, int] = field(default_factory=dict)
    structural_metrics: dict[str, int] = field(default_factory=dict)
    transformations: list[TransformationEntry] = field(default_factory=list)
    samples: list[TransformationSample] = field(default_factory=list)
    validation: dict[str, Any] = field(default_factory=dict)
    export_results: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    def save(self, path: str | Path):
        Path(path).write_text(self.to_json(indent=2), encoding="utf-8")

    @classmethod
    def from_json(cls, raw_json: str) -> RestorationReport:
        data = json.loads(raw_json)
        transformations = [
            TransformationEntry(**t) for t in data.get("transformations", [])
        ]
        samples = [
            TransformationSample(**s) for s in data.get("samples", [])
        ]
        filtered = {
            k: v
            for k, v in data.items()
            if k not in {"transformations", "samples"}
        }
        return cls(**filtered, transformations=transformations, samples=samples)


def collect_runtime_environment(compute_device: str = "cpu") -> dict[str, Any]:
    """Collects version metadata for Lume's execution environment."""
    env_info: dict[str, Any] = {
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "compute_device": compute_device,
    }
    for pkg in ("PyMuPDF", "beautifulsoup4", "pypandoc", "marker-pdf"):
        try:
            import importlib.metadata
            env_info[pkg] = importlib.metadata.version(pkg)
        except Exception:
            env_info[pkg] = "unknown"
    return env_info
