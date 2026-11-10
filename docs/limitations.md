# Known Limitations & Edge Cases

Lume is designed for complex academic and historical PDFs, but document restoration involves trade-offs between deterministic rules, heuristic DOM reconstruction, and neural OCR behavior. This document separates **observed pipeline limitations** (verified directly in Lume's codebase and test corpus) from **broader domain challenges** in optical character recognition.

---

## 1. Observed Pipeline & Architectural Limitations

### 1.1. Absence of Raster Image Preprocessing (Deskew / Dewarp / Shadow Removal)
- **Current Behavior**: `core/pdf_handler.py` performs geometric spine cropping on wide two-page covers and binary `ToUnicode` CMap stream repair, but does **not** apply raster image filters (such as OpenCV deskewing, adaptive binarization, or gutter shadow removal) to scanned body pages before passing them to Marker/Surya.
- **Impact**: Heavily skewed scans or dark inner-margin book-gutter shadows rely entirely on Surya's internal layout and recognition robustness.

### 1.2. OCR Character Confusions in Footnote Markers (`l`/`1`/`I`, `O`/`0`)
- **Observed Case**: In scanned or OCR-processed pages, numeric footnote calls in the body text are occasionally recognized with letter substitutions (e.g., `1l`, `1I`, `1O`, `1º` instead of `11` or `10`).
- **Current Mitigation & Limit**: `core/html_healer.py` (`heal_ocr_errors`) repairs two- or three-character alphanumeric tokens matching `(\d{1,2})([lIOº°])\b` **only when** the healed candidate number already exists in the extracted footnote dictionary (`g_notes`). Single-digit footnote markers misread as a standalone letter (e.g., footnote `1` misread as `l` attached to a word) cannot be safely disambiguated from ordinary spelling without introducing false positives.

### 1.3. Heuristic Boundaries in Footnote Extraction & Paragraph Stitching
- **Footnote Extraction**: `_extract_footnotes_from_soup()` supports four common academic patterns (`<sup>N</sup>` at paragraph start, merged inline notes, multi-paragraph continuations while a body sentence is incomplete, and `[N]` / `(N)` prefixes). Books that use symbolic footnote markers (`*`, `†`, `‡`) or restart footnote numbering `1..N` on every page within the same chapter can cause key collisions in `g_notes` (which indexes notes per chapter/run by numeric key).
- **Cross-Page Paragraph Stitching**: `_stitch_broken_paragraphs()` stitches adjacent `<p>` nodes when the first paragraph lacks terminal punctuation (`.`, `!`, `?`, `:`, `;`, `…`, `»`, `”`, `"`, `)`, `]`) and the next paragraph begins with a lowercase letter (or follows a dangling article/preposition). If a sentence splits across a page boundary immediately after an abbreviation ending in a period (e.g., `cf.` or `p.`), the stitcher treats the period as terminal punctuation and leaves the paragraph split (`paragraphs_skipped_not_split`).

### 1.4. Progressive Provenance Fallback & Repeated Text Ambiguity
- **Current Behavior**: When Marker's `JSONRenderer` block tree (`provenance_blocks.json`) matches a snippet, `ProvenanceResolver` reports `match_method = "marker_block_id"`. When falling back to PyMuPDF page text (`match_method = "page_text_match"`) or when a short snippet appears identically on multiple pages (e.g., repeated headers, refrains, or short citations), `ProvenanceResolver` marks the sample with `ambiguous = True`.
- **Limit**: Heavily OCR-corrected paragraphs whose normalized 72-character prefix/suffix no longer matches the raw PDF text layer resolve as `match_method = "unresolved"`.

### 1.5. External Process Timeouts & Hardware Requirements
- **Current Behavior**: Calibre (`ebook-convert`) is guarded by a 600-second timeout (`timeout=600`), whereas the chunked Marker subprocess and Pandoc compilation run without a fixed timeout so large books on CPU-only machines are not prematurely terminated.
- **Limit**: On systems without an NVIDIA CUDA GPU or Apple Silicon MPS, full neural OCR via Marker/Surya on a 300+ page scanned book is CPU-bound and significantly slower than `disable_ocr` vector extraction.

---

## 2. Domain-Level OCR & Typography Challenges

The following challenges are inherent to historical and philological PDF sources and should be considered when evaluating output quality on new corpora:

1. **Polytonic Greek, Hebrew, and Mixed-Script Philology**:
   - Bilingual editions or classical commentaries mixing Latin script with polytonic Greek or Hebrew footnotes can suffer higher character error rates (CER) during OCR if `disable_ocr` cannot be used (i.e., scanned image-only pages).
2. **Multi-Column & Marginalia Layouts**:
   - Complex critical editions with parallel columns, side-margin line numbers, or interleaved apparatus criticus blocks may have marginalia merged into body paragraphs by upstream layout analysis.
3. **Complex Non-TOC Tables**:
   - `is_toc_table()` specifically targets Table of Contents tables (where `>= 35%` of rows end with Roman or Arabic page numbers) to convert them into Kindle-safe float paragraphs. Data or statistical tables in the body text are left as standard HTML `<table>` elements.

---

## 3. Planned Mitigations (Roadmap)

- **Chapter-Scoped / Page-Scoped Footnote Namespace**: Key footnotes by `(chapter_file, local_cycle, note_number)` to support books that restart footnote numbering `[1]` on every page.
- **Optional Raster Pre-Processing Stage**: Add an opt-in OpenCV/Pillow stage for deskewing and gutter shadow suppression on degraded historical scans prior to Marker execution.
- **Headless CLI Entry Point**: Expose a command-line interface (`python -m core.cli`) alongside the Tkinter GUI for batch corpus processing and automated regression benchmarking.
