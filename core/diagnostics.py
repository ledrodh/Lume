from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

import fitz

from core.models import DocumentDiagnostics, PageClassification, PageDiagnostics

_CMAP_CORRUPTION_RE = re.compile(rb"<\s*(?:23af\s*f8e7|f8e7)\s*>", re.IGNORECASE)
_FOOTNOTE_LINE_RE = re.compile(r"^\s*(?:[\[\(]?\d{1,3}[\]\)\.]?)\s*[A-ZÀ-Ý«“\"']")


def extract_pdf_metadata_from_doc(doc: fitz.Document, pdf_path: str) -> dict[str, str]:
    """Extracts embedded title and author metadata from an open fitz.Document."""
    meta = {"title": "", "author": ""}
    try:
        raw_meta = doc.metadata or {}
        raw_title = (raw_meta.get("title") or "").strip()
        raw_author = (raw_meta.get("author") or "").strip()
        stem = os.path.splitext(os.path.basename(pdf_path))[0].lower()

        if raw_title and raw_title.lower() not in {"untitled", "unknown", "document", stem}:
            if not raw_title.lower().endswith((".pdf", ".doc", ".docx", ".indd")):
                meta["title"] = raw_title

        if raw_author and raw_author.lower() not in {"unknown", "user", "admin", "administrator"}:
            meta["author"] = raw_author
    except Exception:
        pass
    return meta


def detect_cmap_issues_readonly(doc: fitz.Document) -> list[int]:
    """
    Strictly read-only inspection of PDF xref streams for malformed ToUnicode CMaps.
    Returns a list of xref IDs that are candidates for repair during processing.
    """
    candidates: list[int] = []
    for xref in range(1, doc.xref_length()):
        try:
            if not doc.xref_is_stream(xref):
                continue
            raw = doc.xref_stream(xref)
            if not raw or (b"begincmap" not in raw and b"beginbfchar" not in raw):
                continue
            if _CMAP_CORRUPTION_RE.search(raw):
                candidates.append(xref)
        except Exception:
            continue
    return candidates


def determine_ocr_strategy(ext_cnt: int, img_cnt: int, mix_cnt: int) -> tuple[str, float]:
    """
    Single source of truth for OCR strategy selection across Diagnostics and Converter.
    Accounts for extractable_text, image_only, AND mixed (hybrid) pages:
    - Recommends 'disable_ocr' only when >= 85% of non-empty pages are pure extractable_text
      AND the combined share of image_only + mixed (hybrid) pages is <= 15%.
    - Otherwise recommends 'full_ocr'.
    """
    non_empty = max(1, ext_cnt + img_cnt + mix_cnt)
    ext_ratio = ext_cnt / non_empty
    non_pure_text_ratio = (img_cnt + mix_cnt) / non_empty

    if ext_ratio >= 0.85 and non_pure_text_ratio <= 0.15:
        confidence = round(min(1.0, 0.70 + 0.30 * ext_ratio), 2)
        return "disable_ocr", confidence

    confidence = round(min(1.0, 0.65 + 0.35 * non_pure_text_ratio), 2)
    return "full_ocr", confidence


def classify_page(page: fitz.Page, page_number: int) -> PageDiagnostics:
    """
    Classifies a single PDF page into one of four categories:
    - extractable_text: Predominantly selectable text with negligible image area
    - image_only: Predominantly image/scan with little or no extractable text
    - mixed: Significant presence of both selectable text and images (or OCR overlay on scan)
    - empty_or_unknown: Blank page or insufficient content to classify
    """
    rect = page.rect
    width = float(rect.width)
    height = float(rect.height)
    page_area = max(1.0, width * height)
    rotation = int(page.rotation or 0)

    blocks = page.get_text("blocks") or []
    char_count = 0
    footnote_candidates = 0
    bottom_threshold = rect.y0 + height * 0.68

    for b in blocks:
        if len(b) >= 7 and b[6] == 0:  # text block
            txt_blk = str(b[4]).replace("\ufffd", "").strip()
            char_count += len(txt_blk)
            if float(b[1]) >= bottom_threshold and txt_blk:
                for line in txt_blk.splitlines():
                    line_str = line.strip()
                    if len(line_str) > 4 and _FOOTNOTE_LINE_RE.match(line_str):
                        footnote_candidates += 1

    images = page.get_images(full=False)
    distinct_xrefs = {img[0] for img in images if img}
    distinct_images = len(distinct_xrefs)

    img_infos = page.get_image_info() or []
    image_occurrences = max(len(images), len(img_infos))

    covered_area = 0.0
    for info in img_infos:
        bbox = info.get("bbox")
        if bbox and len(bbox) == 4:
            intersect = fitz.Rect(bbox) & rect
            if not intersect.is_empty:
                covered_area += float(intersect.width * intersect.height)
    image_area_ratio = round(min(1.0, covered_area / page_area), 4)

    if char_count < 20 and image_occurrences == 0:
        classification = PageClassification.EMPTY_OR_UNKNOWN.value
    elif char_count < 40 and (image_occurrences > 0 or image_area_ratio >= 0.10):
        classification = PageClassification.IMAGE_ONLY.value
    elif char_count >= 40 and (image_area_ratio >= 0.15 or (image_occurrences > 0 and image_area_ratio >= 0.05)):
        classification = PageClassification.MIXED.value
    elif char_count >= 20:
        classification = PageClassification.EXTRACTABLE_TEXT.value
    else:
        classification = PageClassification.EMPTY_OR_UNKNOWN.value

    return PageDiagnostics(
        page_number=page_number,
        width=round(width, 2),
        height=round(height, 2),
        rotation=rotation,
        classification=classification,
        char_count=char_count,
        image_occurrences=image_occurrences,
        distinct_images=distinct_images,
        image_area_ratio=image_area_ratio,
        footnote_candidates=footnote_candidates,
    )


def _summarize_diagnostics(
    pdf_path: str,
    total_pages: int,
    meta: dict[str, str],
    first_w: float,
    first_h: float,
    page_diags: list[PageDiagnostics],
    distinct_global_xrefs: set[int],
    cmap_candidates: list[int],
    cmap_scan_completed: bool,
    is_complete: bool,
) -> DocumentDiagnostics:
    n_sampled = max(1, len(page_diags))
    scale = (total_pages / n_sampled) if not is_complete and total_pages > 0 else 1.0

    ext_cnt = sum(1 for p in page_diags if p.classification == PageClassification.EXTRACTABLE_TEXT.value)
    img_cnt = sum(1 for p in page_diags if p.classification == PageClassification.IMAGE_ONLY.value)
    mix_cnt = sum(1 for p in page_diags if p.classification == PageClassification.MIXED.value)
    emp_cnt = sum(1 for p in page_diags if p.classification == PageClassification.EMPTY_OR_UNKNOWN.value)

    recommended_mode, confidence = determine_ocr_strategy(ext_cnt, img_cnt, mix_cnt)
    if not is_complete:
        confidence = round(confidence * 0.85, 2)

    return DocumentDiagnostics(
        file_path=os.path.abspath(pdf_path),
        file_name=os.path.basename(pdf_path),
        total_pages=total_pages,
        embedded_title=meta.get("title", ""),
        embedded_author=meta.get("author", ""),
        first_page_width=round(first_w, 2),
        first_page_height=round(first_h, 2),
        wide_first_page_candidate=bool(first_w > first_h * 1.05),
        extractable_text_pages=int(round(ext_cnt * scale)) if not is_complete else ext_cnt,
        image_only_pages=int(round(img_cnt * scale)) if not is_complete else img_cnt,
        mixed_pages=int(round(mix_cnt * scale)) if not is_complete else mix_cnt,
        empty_or_unknown_pages=int(round(emp_cnt * scale)) if not is_complete else emp_cnt,
        total_image_occurrences=sum(p.image_occurrences for p in page_diags),
        total_distinct_images=len(distinct_global_xrefs),
        estimated_footnote_candidates=int(round(sum(p.footnote_candidates for p in page_diags) * scale)),
        cmap_scan_completed=cmap_scan_completed,
        cmap_issues_detected=len(cmap_candidates),
        cmap_repair_candidates=cmap_candidates,
        recommended_ocr_mode=recommended_mode,
        classification_confidence=confidence,
        is_complete=is_complete,
        pages=page_diags if is_complete else [],
    )


def quick_diagnostics(pdf_path: str | Path) -> DocumentDiagnostics:
    """
    Stage 1 Fast Pre-Flight Diagnostics (< 100ms on typical books).
    Inspects document metadata, page count, first-page aspect ratio, and up to 12 sampled pages.
    Does not run the full xref CMap stream scan (cmap_scan_completed=False, is_complete=False),
    ensuring full_diagnostics() always runs in the background to complete CMap verification.
    Strictly read-only.
    """
    path_str = str(pdf_path)
    doc = fitz.open(path_str)
    try:
        total = len(doc)
        meta = extract_pdf_metadata_from_doc(doc, path_str)
        if total == 0:
            return DocumentDiagnostics(
                file_path=os.path.abspath(path_str),
                file_name=os.path.basename(path_str),
                total_pages=0,
                cmap_scan_completed=True,
                is_complete=True,
            )

        r0 = doc[0].rect
        first_w, first_h = float(r0.width), float(r0.height)

        step = max(1, total // 12)
        sample_indices = list(range(0, total, step))[:12]
        page_diags: list[PageDiagnostics] = []
        distinct_xrefs: set[int] = set()

        for idx in sample_indices:
            page = doc[idx]
            for img in page.get_images(full=False):
                if img:
                    distinct_xrefs.add(img[0])
            page_diags.append(classify_page(page, idx + 1))

        return _summarize_diagnostics(
            pdf_path=path_str,
            total_pages=total,
            meta=meta,
            first_w=first_w,
            first_h=first_h,
            page_diags=page_diags,
            distinct_global_xrefs=distinct_xrefs,
            cmap_candidates=[],
            cmap_scan_completed=False,
            is_complete=False,
        )
    finally:
        doc.close()


def full_diagnostics(
    pdf_path: str | Path,
    cancel_check: Callable[[], bool] | None = None,
) -> DocumentDiagnostics | None:
    """
    Stage 2 Complete Background Diagnostics.
    Classifies every page, computes distinct vs. repeated image occurrences, estimates footnote
    candidates, and performs a strictly read-only scan for corrupted ToUnicode CMap streams.
    Returns None if canceled via cancel_check().
    """
    path_str = str(pdf_path)
    doc = fitz.open(path_str)
    try:
        total = len(doc)
        meta = extract_pdf_metadata_from_doc(doc, path_str)
        if total == 0:
            return DocumentDiagnostics(
                file_path=os.path.abspath(path_str),
                file_name=os.path.basename(path_str),
                total_pages=0,
                cmap_scan_completed=True,
                is_complete=True,
            )

        r0 = doc[0].rect
        first_w, first_h = float(r0.width), float(r0.height)

        page_diags: list[PageDiagnostics] = []
        distinct_xrefs: set[int] = set()

        for idx in range(total):
            if cancel_check and cancel_check():
                return None
            page = doc[idx]
            for img in page.get_images(full=False):
                if img:
                    distinct_xrefs.add(img[0])
            page_diags.append(classify_page(page, idx + 1))

        if cancel_check and cancel_check():
            return None

        cmap_candidates = detect_cmap_issues_readonly(doc)

        return _summarize_diagnostics(
            pdf_path=path_str,
            total_pages=total,
            meta=meta,
            first_w=first_w,
            first_h=first_h,
            page_diags=page_diags,
            distinct_global_xrefs=distinct_xrefs,
            cmap_candidates=cmap_candidates,
            cmap_scan_completed=True,
            is_complete=True,
        )
    finally:
        doc.close()
