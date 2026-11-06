# Lume Benchmark & Provenance Methodology

This document describes the evaluation methodology behind the benchmark table in [`README.md`](../README.md), how operational, structural, and quality metrics are defined, and how Lume's progressive provenance engine resolves source pages and block IDs.

---

## 1. Reference Corpus & Ground Truth

The primary reference benchmark was conducted on a 334-page academic philosophical treatise (*O Trabalhador — Domínio e Figura*, Portuguese edition of Ernst Jünger's *Der Arbeiter*), characterized by:

- **Total Pages**: 334 pages (`content.pdf` after front-cover extraction: 333 pages).
- **Typography & Encoding**: Created via macOS Quartz PDFContext with an embedded `Symbol` font containing a malformed `ToUnicode` CMap stream where glyph `<01>` (em-dash `—`) was mapped to `<23AF><F8E7>` or extracted as `!` by `pypdfium2`.
- **Structural Elements**:
  - **80 numbered book sections** (`1.` through `80.`), several printed without trailing periods (`53`) or positioned at the bottom margin of a page (`67.`).
  - **123 scholarly footnotes** spanning translator notes, cross-references, and multi-paragraph annotations.
  - **Numbered synopsis paragraphs** at the end of the volume that must preserve their exact numbering rather than being renumbered by Markdown-to-HTML `<ol>` parsers.

### Ground-Truth Verification Protocol

1. **Footnote Ground Truth (`123` notes)**:
   - Every footnote in the source PDF was manually cataloged (`[1]` through `[123]`).
   - **Extracted Recall**: Number of distinct footnotes extracted into `<section epub:type="footnotes">` divided by `123`.
   - **Bidirectional Link Precision & Recall**: Every `<a epub:type="noteref">` in the EPUB body was verified against the original PDF page to confirm that:
     - No body numbers (years, page numbers, or section headers) were falsely converted into footnote links (**Precision = 100.0%**).
     - Every genuine footnote marker in the text received a valid forward link (`#fn-N`) and backlink (`#ref-N-M`) (**Recall = 100.0%**).
2. **Section Integrity (`80` sections)**:
   - Verified by querying all `<h3>` headings in the generated XHTML spine and confirming exact sequential coverage from `### 1.` to `### 80.`.
3. **W3C EPUB 3.3 OCF & Link Conformance**:
   - Verified both by `core/epub_validator.py` (`validate_epub_structure`) and by **W3C EPUBCheck 5.4.0** in CI.

---

## 2. Metric Taxonomy (`restoration_report.json` v1.1.0)

Lume separates metrics into three distinct levels in `restoration_report.json` so operational counts are never conflated with ground-truth quality:

1. **`operational_metrics`**:
   - Deterministic counters recorded during execution (`pages_processed`, `cmap_streams_repaired`, `paragraphs_inspected`, `paragraphs_stitched`, `paragraphs_skipped_not_split`, `false_sups_unwrapped`, `leaked_page_numbers_removed`, `em_dashes_normalized`).
2. **`structural_metrics`**:
   - Counts of structural DOM/EPUB entities (`footnotes_extracted`, `footnotes_linked_bidirectional`, `footnotes_unlinked`, `toc_entries_rebuilt`, `epub_checked_files`, `epub_checked_internal_links`, `epub_broken_links`).
3. **`transformations`**:
   - Per-stage audit entries recording `inspected_count`, `transformed_count`, `skipped_count`, and `failed_count`.

---

## 3. Progressive Provenance Resolution (`ProvenanceResolver`)

Because Pandoc compiles Markdown into reflowable XHTML chapters without preserving PDF page coordinates, Lume uses a progressive provenance resolver (`core/reporting.py`) to link `TransformationSample` entries back to the source PDF:

1. **Tier 1 — Marker Block Tree (`match_method = "marker_block_id"`)**:
   - During chunked extraction, Lume invokes Marker's `JSONRenderer` on the already-built `Document` object in memory (`provenance_blocks.json`), indexing each leaf block's `/page/N/BlockType/M` identifier and normalized text.
   - When a healed paragraph or footnote matches a recorded block, Lume records both the 1-based `source_pages` and the exact `block_ids`.
2. **Tier 2 — PyMuPDF Page Text Fallback (`match_method = "page_text_match"`)**:
   - When Marker JSON blocks are unavailable (e.g., offline HTML healing tests or custom Markdown inputs), `ProvenanceResolver` falls back to normalized 72-character boundary probes against the PyMuPDF per-page text index.
3. **Tier 3 — Unresolved (`match_method = "unresolved"`)**:
   - If a snippet is shorter than the minimum probe threshold or heavily transformed by OCR, Lume explicitly reports `match_method = "unresolved"` rather than guessing a page number.
4. **Ambiguity Detection (`ambiguous = True`)**:
   - If a single text probe matches multiple distinct pages (for example, a recurring refrain or repeated header/citation), `ProvenanceResolver` sets `ambiguous = True` on the `TransformationSample` and displays an `[Ambiguous Match]` badge in `comparison_report.html`.
