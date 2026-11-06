from __future__ import annotations

import html
import json
import os
import re
from pathlib import Path

import fitz

from core.models import (
    DocumentDiagnostics,
    HealingStats,
    RestorationReport,
    TransformationEntry,
    ValidationSummary,
    collect_runtime_environment,
)


class ProvenanceResolver:
    """
    Maps text fragments to their originating PDF page numbers and Marker block IDs.
    Uses Marker's structured JSON block output when available and falls back to
    a lightweight PyMuPDF page text index.
    """

    def __init__(self, pdf_path: str | Path | None = None, blocks_json_path: str | Path | None = None):
        self.page_norms: list[tuple[int, str]] = []
        self.block_records: list[tuple[int, str, str]] = []  # (page_num, block_id, norm_text)

        if blocks_json_path and Path(blocks_json_path).exists():
            try:
                raw_blocks = json.loads(Path(blocks_json_path).read_text(encoding="utf-8"))
                for b in raw_blocks:
                    pnum = int(b.get("page_number", 0))
                    bid = str(b.get("block_id", ""))
                    norm = self._normalize(str(b.get("text", "")))
                    if pnum > 0 and len(norm) >= 12:
                        self.block_records.append((pnum, bid, norm))
            except Exception:
                pass

        if pdf_path and Path(pdf_path).exists():
            try:
                doc = fitz.open(str(pdf_path))
                for idx, page in enumerate(doc):
                    norm = self._normalize(page.get_text("text") or "")
                    if norm:
                        self.page_norms.append((idx + 1, norm))
                doc.close()
            except Exception:
                pass

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\W+", "", text).lower()

    def resolve(self, *snippets: str) -> tuple[list[int], list[str], str, bool]:
        """
        Returns (sorted_source_pages, block_ids, match_method, ambiguous) for one or more text snippets.
        - match_method: "marker_block_id" | "page_text_match" | "unresolved"
        - ambiguous: True when a single snippet matches multiple distinct pages.
        """
        pages: set[int] = set()
        block_ids: list[str] = []
        matched_via_blocks = False
        matched_via_pages = False
        ambiguous = False

        for snip in snippets:
            if not snip:
                continue
            norm = self._normalize(snip)
            if len(norm) < 10:
                continue
            probes = [norm[:72], norm[-72:]] if len(norm) > 80 else [norm]

            snip_block_pages: set[int] = set()
            for probe in probes:
                if len(probe) < 10:
                    continue
                for pnum, bid, bnorm in self.block_records:
                    if probe in bnorm:
                        snip_block_pages.add(pnum)
                        if bid and bid not in block_ids:
                            block_ids.append(bid)

            if snip_block_pages:
                matched_via_blocks = True
                if len(snip_block_pages) > 1:
                    ambiguous = True
                pages.update(snip_block_pages)
                continue

            snip_page_hits: set[int] = set()
            for probe in probes:
                if len(probe) < 10:
                    continue
                for pnum, pnorm in self.page_norms:
                    if probe in pnorm:
                        snip_page_hits.add(pnum)

            if snip_page_hits:
                matched_via_pages = True
                if len(snip_page_hits) > 1:
                    ambiguous = True
                pages.update(snip_page_hits)

        if matched_via_blocks:
            match_method = "marker_block_id"
        elif matched_via_pages:
            match_method = "page_text_match"
        else:
            match_method = "unresolved"

        return sorted(pages), block_ids[:4], match_method, ambiguous


def build_restoration_report(
    pdf_path: str,
    title: str,
    author: str,
    compute_device: str,
    diagnostics: DocumentDiagnostics,
    extraction_stats: dict,
    healing_stats: HealingStats,
    validation: ValidationSummary,
    export_results: dict,
    include_full_paths: bool = False,
) -> RestorationReport:
    """Assembles the versioned RestorationReport from each stage's structured output."""
    cmaps_repaired = int(extraction_stats.get("cmap_issues_repaired", 0))
    wide_cropped = bool(extraction_stats.get("wide_cover_cropped", False))
    skipped_paras = max(0, healing_stats.paragraphs_inspected - healing_stats.paragraphs_stitched)

    operational_metrics = {
        "pages_processed": diagnostics.total_pages,
        "cmap_streams_repaired": cmaps_repaired,
        "wide_cover_spine_cropped": 1 if wide_cropped else 0,
        "paragraphs_inspected": healing_stats.paragraphs_inspected,
        "paragraphs_stitched": healing_stats.paragraphs_stitched,
        "paragraphs_skipped_not_split": skipped_paras,
        "false_sups_unwrapped": healing_stats.false_sups_unwrapped,
        "leaked_page_numbers_removed": healing_stats.leaked_pages_removed,
        "em_dashes_normalized": healing_stats.em_dashes_normalized,
    }

    structural_metrics = {
        "footnotes_extracted": healing_stats.footnotes_extracted,
        "footnotes_linked_bidirectional": healing_stats.footnotes_linked,
        "footnotes_unlinked": healing_stats.footnotes_unlinked,
        "toc_entries_rebuilt": healing_stats.toc_entries_rebuilt,
        "epub_checked_files": validation.checked_files,
        "epub_checked_internal_links": validation.checked_links,
        "epub_broken_links": validation.broken_links,
    }

    transformations = [
        TransformationEntry(
            operation="cover_extraction_and_spine_crop",
            category="operational",
            status="success" if wide_cropped else "skipped",
            inspected_count=1 if diagnostics.total_pages > 0 else 0,
            transformed_count=1 if wide_cropped else 0,
            skipped_count=0 if wide_cropped else (1 if diagnostics.total_pages > 0 else 0),
            source_pages=[1] if diagnostics.total_pages > 0 else [],
            details="Cropped wide two-page spread cover using visual coordinate clipping."
            if wide_cropped
            else "Standard portrait cover extracted at 4x resolution.",
        ),
        TransformationEntry(
            operation="tounicode_cmap_sanitization",
            category="operational",
            status="success" if cmaps_repaired > 0 else "skipped",
            inspected_count=max(diagnostics.cmap_issues_detected, cmaps_repaired),
            transformed_count=cmaps_repaired,
            skipped_count=max(0, diagnostics.cmap_issues_detected - cmaps_repaired),
            details=f"Repaired {cmaps_repaired} malformed ToUnicode CMap stream(s).",
        ),
        TransformationEntry(
            operation="cross_page_paragraph_stitching",
            category="operational",
            status="success" if healing_stats.paragraphs_stitched > 0 else "skipped",
            inspected_count=healing_stats.paragraphs_inspected,
            transformed_count=healing_stats.paragraphs_stitched,
            skipped_count=skipped_paras,
            details=(
                f"Inspected {healing_stats.paragraphs_inspected} paragraph(s); "
                f"stitched {healing_stats.paragraphs_stitched} split paragraph(s) across page breaks."
            ),
        ),
        TransformationEntry(
            operation="bidirectional_footnote_linking",
            category="structural",
            status="success" if healing_stats.footnotes_linked > 0 else "skipped",
            inspected_count=healing_stats.footnotes_extracted,
            transformed_count=healing_stats.footnotes_linked,
            skipped_count=healing_stats.footnotes_unlinked,
            details=(
                f"Extracted {healing_stats.footnotes_extracted} footnote(s) and linked "
                f"{healing_stats.footnotes_linked} body reference(s)."
            ),
        ),
        TransformationEntry(
            operation="toc_kindle_safe_reconstruction",
            category="structural",
            status="success" if healing_stats.toc_entries_rebuilt > 0 else "skipped",
            inspected_count=healing_stats.toc_tables_inspected,
            transformed_count=healing_stats.toc_entries_rebuilt,
            skipped_count=max(0, healing_stats.toc_tables_inspected - (1 if healing_stats.toc_entries_rebuilt else 0)),
            details=f"Rebuilt {healing_stats.toc_entries_rebuilt} Kindle-safe Table of Contents entry(ies).",
        ),
    ]

    input_metadata = {
        "source_file": os.path.basename(pdf_path),
        "resolved_title": title,
        "resolved_author": author,
    }
    if include_full_paths:
        input_metadata["source_pdf"] = os.path.abspath(pdf_path)

    return RestorationReport(
        input_metadata=input_metadata,
        environment=collect_runtime_environment(compute_device),
        diagnostics=diagnostics.to_dict(include_pages=False, include_file_path=include_full_paths),
        operational_metrics=operational_metrics,
        structural_metrics=structural_metrics,
        transformations=transformations,
        samples=healing_stats.samples[:8],
        validation=validation.to_dict(),
        export_results=export_results,
    )


def generate_comparison_report(
    report: RestorationReport,
    pdf_path: str | Path,
    out_dir: str | Path,
) -> str:
    """
    Generates a safe, offline-capable HTML comparison & audit report in out_dir.
    - Renders controlled-resolution JPEG thumbnails of referenced source pages into comparison_assets/.
    - Strictly HTML-escapes all document text to prevent XSS/script injection from untrusted PDFs.
    """
    out_dir_path = Path(out_dir)
    assets_dir = out_dir_path / "comparison_assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    report_html_path = out_dir_path / "comparison_report.html"

    # Collect up to 8 unique source pages referenced by samples and render thumbnails
    needed_pages: set[int] = set()
    for sample in report.samples:
        for p in sample.source_pages[:2]:
            if p > 0 and len(needed_pages) < 8:
                needed_pages.add(p)

    rendered_thumbs: dict[int, str] = {}
    if pdf_path and Path(pdf_path).exists() and needed_pages:
        try:
            doc = fitz.open(str(pdf_path))
            for pnum in sorted(needed_pages):
                if 1 <= pnum <= len(doc):
                    page = doc[pnum - 1]
                    scale = min(1.2, 480.0 / max(1.0, float(page.rect.width)))
                    pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale))
                    rel_img = f"comparison_assets/page_{pnum:03d}.jpg"
                    pix.save(str(out_dir_path / rel_img))
                    rendered_thumbs[pnum] = rel_img
            doc.close()
        except Exception:
            pass

    def esc(s: object) -> str:
        return html.escape(str(s), quote=True)

    title = esc(report.input_metadata.get("resolved_title", "Restored Book"))
    author = esc(report.input_metadata.get("resolved_author", "Unknown"))
    run_id = esc(report.run_id)
    schema_ver = esc(report.schema_version)
    device = esc(report.environment.get("compute_device", "cpu")).upper()

    val = report.validation
    is_valid = bool(val.get("is_valid", False))
    val_badge_cls = "badge-ok" if is_valid else "badge-err"
    val_badge_txt = "PASSED (W3C EPUB 3.3 OCF)" if is_valid else "ISSUES DETECTED"

    diag = report.diagnostics
    op_m = report.operational_metrics
    st_m = report.structural_metrics

    sample_cards_html: list[str] = []
    for idx, s in enumerate(report.samples, 1):
        pages_str = ", ".join(f"Page {p}" for p in s.source_pages) if s.source_pages else "Document Body"
        blocks_str = ", ".join(s.block_ids) if s.block_ids else s.match_method
        ambig_badge = ' <span style="color: var(--warn); font-weight: 700;">[Ambiguous Match]</span>' if s.ambiguous else ""
        thumbs_html = ""
        for p in s.source_pages[:2]:
            if p in rendered_thumbs:
                thumbs_html += (
                    f'<div class="thumb-wrap">'
                    f'<img src="{esc(rendered_thumbs[p])}" alt="Original PDF Page — Page {p}" loading="lazy"/>'
                    f'<span>Original PDF Page — Page {p}</span>'
                    f"</div>"
                )

        sample_cards_html.append(
            f"""
            <div class="sample-card">
              <div class="sample-header">
                <span class="sample-tag">#{idx} · {esc(s.category.replace('_', ' ').upper())}</span>
                <span class="sample-prov">📍 Provenance: <strong>{esc(pages_str)}</strong> ({esc(blocks_str)} · {esc(s.match_method)}){ambig_badge}</span>
              </div>
              <p class="sample-desc">{esc(s.description)}</p>
              <div class="compare-grid">
                <div class="compare-col col-before">
                  <h4>Pre-Healing Extracted Text</h4>
                  {thumbs_html}
                  <pre class="excerpt">{esc(s.original_excerpt)}</pre>
                </div>
                <div class="compare-col col-after">
                  <h4>Restored EPUB Structure (After Healing)</h4>
                  <pre class="excerpt">{esc(s.restored_excerpt)}</pre>
                </div>
              </div>
            </div>
            """
        )

    samples_section = (
        "\n".join(sample_cards_html)
        if sample_cards_html
        else '<p class="empty-msg">No structural transformations were required for this document.</p>'
    )

    html_doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline';"/>
  <title>Lume Restoration &amp; Provenance Report — {title}</title>
  <style>
    :root {{
      --bg: #0f172a; --card: #1e293b; --border: #334155;
      --text: #f8fafc; --muted: #94a3b8; --accent: #38bdf8;
      --ok: #22c55e; --warn: #f59e0b; --err: #ef4444;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg); color: var(--text); margin: 0; padding: 32px 20px; line-height: 1.5;
    }}
    .container {{ max-width: 1180px; margin: 0 auto; }}
    header {{
      background: var(--card); border: 1px solid var(--border); border-radius: 12px;
      padding: 24px; margin-bottom: 24px; display: flex; justify-content: space-between;
      align-items: flex-start; flex-wrap: wrap; gap: 16px;
    }}
    h1 {{ margin: 0 0 6px 0; font-size: 1.5rem; }}
    h2 {{ font-size: 1.2rem; margin: 28px 0 12px 0; color: var(--accent); }}
    .meta-sub {{ color: var(--muted); font-size: 0.9rem; margin: 2px 0; }}
    .badge {{
      display: inline-block; padding: 6px 12px; border-radius: 999px;
      font-weight: 700; font-size: 0.8rem; letter-spacing: 0.03em;
    }}
    .badge-ok {{ background: rgba(34, 197, 94, 0.18); color: var(--ok); border: 1px solid var(--ok); }}
    .badge-err {{ background: rgba(239, 68, 68, 0.18); color: var(--err); border: 1px solid var(--err); }}
    .kpi-grid {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); gap: 16px;
    }}
    .kpi-card {{
      background: var(--card); border: 1px solid var(--border); border-radius: 10px; padding: 18px;
    }}
    .kpi-card h3 {{ margin: 0 0 10px 0; font-size: 0.85rem; text-transform: uppercase; color: var(--muted); }}
    .metric-row {{ display: flex; justify-content: space-between; padding: 5px 0; border-bottom: 1px solid rgba(255,255,255,0.06); font-size: 0.92rem; }}
    .metric-row:last-child {{ border-bottom: none; }}
    .sample-card {{
      background: var(--card); border: 1px solid var(--border); border-radius: 12px;
      padding: 20px; margin-bottom: 20px;
    }}
    .sample-header {{
      display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 8px;
      margin-bottom: 8px;
    }}
    .sample-tag {{
      background: rgba(56, 189, 248, 0.15); color: var(--accent);
      padding: 4px 10px; border-radius: 6px; font-weight: 700; font-size: 0.8rem;
    }}
    .sample-prov {{ color: var(--muted); font-size: 0.85rem; }}
    .sample-desc {{ margin: 4px 0 14px 0; color: #cbd5e1; font-size: 0.92rem; }}
    .compare-grid {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(340px, 1fr)); gap: 16px;
    }}
    .compare-col {{
      background: rgba(15, 23, 42, 0.65); border: 1px solid var(--border); border-radius: 8px; padding: 14px;
    }}
    .compare-col h4 {{ margin: 0 0 10px 0; font-size: 0.85rem; color: var(--muted); text-transform: uppercase; }}
    .col-before {{ border-left: 3px solid var(--warn); }}
    .col-after {{ border-left: 3px solid var(--ok); }}
    .thumb-wrap {{ margin-bottom: 10px; text-align: center; }}
    .thumb-wrap img {{ max-width: 100%; max-height: 260px; border-radius: 6px; border: 1px solid var(--border); }}
    .thumb-wrap span {{ display: block; font-size: 0.75rem; color: var(--muted); margin-top: 4px; }}
    pre.excerpt {{
      white-space: pre-wrap; word-wrap: break-word; font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
      font-size: 0.85rem; margin: 0; color: var(--text);
    }}
    .empty-msg {{ color: var(--muted); font-style: italic; }}
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div>
        <h1>Lume — Document Restoration &amp; Provenance Report</h1>
        <p class="meta-sub"><strong>Title:</strong> {title} &nbsp;|&nbsp; <strong>Author:</strong> {author}</p>
        <p class="meta-sub"><strong>Run ID:</strong> {run_id} &nbsp;|&nbsp; <strong>Schema:</strong> v{schema_ver} &nbsp;|&nbsp; <strong>Device:</strong> {device}</p>
      </div>
      <div>
        <span class="badge {val_badge_cls}">{val_badge_txt}</span>
      </div>
    </header>

    <div class="kpi-grid">
      <div class="kpi-card">
        <h3>1. Pre-Flight Diagnostics</h3>
        <div class="metric-row"><span>Total Pages</span><strong>{esc(diag.get("total_pages", 0))}</strong></div>
        <div class="metric-row"><span>Extractable Text Pages</span><strong>{esc(diag.get("extractable_text_pages", 0))}</strong></div>
        <div class="metric-row"><span>Image-Only / Scanned Pages</span><strong>{esc(diag.get("image_only_pages", 0))}</strong></div>
        <div class="metric-row"><span>Hybrid (Mixed) Pages</span><strong>{esc(diag.get("mixed_pages", 0))}</strong></div>
        <div class="metric-row"><span>Distinct / Total Images</span><strong>{esc(diag.get("total_distinct_images", 0))} / {esc(diag.get("total_image_occurrences", 0))}</strong></div>
        <div class="metric-row"><span>OCR Strategy</span><strong>{esc(diag.get("recommended_ocr_mode", "full_ocr"))}</strong></div>
      </div>

      <div class="kpi-card">
        <h3>2. Operational Telemetry</h3>
        <div class="metric-row"><span>Paragraphs Inspected</span><strong>{esc(op_m.get("paragraphs_inspected", 0))}</strong></div>
        <div class="metric-row"><span>Paragraphs Stitched</span><strong>{esc(op_m.get("paragraphs_stitched", 0))}</strong></div>
        <div class="metric-row"><span>ToUnicode CMaps Repaired</span><strong>{esc(op_m.get("cmap_streams_repaired", 0))}</strong></div>
        <div class="metric-row"><span>False &lt;sup&gt; Tags Unwrapped</span><strong>{esc(op_m.get("false_sups_unwrapped", 0))}</strong></div>
        <div class="metric-row"><span>Leaked Page Numbers Removed</span><strong>{esc(op_m.get("leaked_page_numbers_removed", 0))}</strong></div>
        <div class="metric-row"><span>Em-Dashes Normalized</span><strong>{esc(op_m.get("em_dashes_normalized", 0))}</strong></div>
      </div>

      <div class="kpi-card">
        <h3>3. Structural &amp; OCF Validation</h3>
        <div class="metric-row"><span>Footnotes Extracted</span><strong>{esc(st_m.get("footnotes_extracted", 0))}</strong></div>
        <div class="metric-row"><span>Bidirectional Links Created</span><strong>{esc(st_m.get("footnotes_linked_bidirectional", 0))}</strong></div>
        <div class="metric-row"><span>TOC Entries Rebuilt</span><strong>{esc(st_m.get("toc_entries_rebuilt", 0))}</strong></div>
        <div class="metric-row"><span>Archive Files Checked</span><strong>{esc(st_m.get("epub_checked_files", 0))}</strong></div>
        <div class="metric-row"><span>Internal Links Verified</span><strong>{esc(st_m.get("epub_checked_internal_links", 0))}</strong></div>
        <div class="metric-row"><span>Broken Internal Links</span><strong>{esc(st_m.get("epub_broken_links", 0))}</strong></div>
      </div>
    </div>

    <h2>Traceable Transformation Samples (PDF Provenance ↔ Restored EPUB)</h2>
    {samples_section}
  </div>
</body>
</html>
"""
    report_html_path.write_text(html_doc, encoding="utf-8")
    return str(report_html_path)
