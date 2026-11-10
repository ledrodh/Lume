# Lume Architecture

Lume is organized around a modular Python architecture separating **document diagnostics**, **PDF stream sanitization**, **chunked neural layout/OCR extraction**, **DOM healing**, **OCF validation**, and **audit reporting** from the desktop user interface.

---

## 1. Module Responsibilities

```text
Lume/
├── main.py                  # Entry point & native OS theme selection
├── ui/
│   └── main_window.py       # Thread-safe Tkinter GUI & asynchronous diagnostics dashboard
├── core/
│   ├── models.py            # Versioned dataclasses (RestorationReport v1.1.0, DocumentDiagnostics, HealingStats)
│   ├── diagnostics.py       # Read-only 2-stage PDF inspector, 4-state page classifier & OCR strategy selector
│   ├── pdf_handler.py       # Rotation-safe cover clipping & ToUnicode CMap stream sanitization
│   ├── converter.py         # Pipeline orchestrator, device detection & 50-page chunked Marker runner
│   ├── html_healer.py       # Triple-Pass HTML DOM healer, paragraph stitcher & OCF EPUB packager
│   ├── epub_validator.py    # Local W3C EPUB 3.3 OCF, OPF, XML & internal link/anchor validator
│   └── reporting.py         # Progressive provenance resolver, JSON report builder & XSS-safe HTML comparator
└── tests/
    └── test_lume.py         # Unit, concurrency, privacy, and OCF structural validation test suite
```

### Design Principles
- **Flat Core Hierarchy**: Responsibilities are separated by pipeline stage inside `core/` without premature subpackage nesting.
- **Explicit Data Contracts (`core/models.py`)**: All inter-stage communication uses typed dataclasses (`DocumentDiagnostics`, `HealingStats`, `ValidationSummary`, `TransformationEntry`, `TransformationSample`, and `RestorationReport` with `SCHEMA_VERSION = "1.1.0"`).
- **Single Source of Truth for OCR Strategy**: `determine_ocr_strategy()` in `core/diagnostics.py` governs both the pre-flight UI recommendation and the execution mode in `core/converter.py`.

---

## 2. UI Concurrency & State Safety (`ui/main_window.py`)

Because full PDF inspection and book conversion are I/O- and CPU/GPU-intensive, `LumeApp` enforces three concurrency rules:

1. **Two-Stage Non-Blocking Diagnostics**:
   - Selecting a PDF immediately executes `quick_diagnostics()` synchronously (`< 100ms`), populating page count, cover dimensions, embedded metadata, and a 12-page sampled classification preview.
   - Because `quick_diagnostics()` skips full `xref` stream scanning (`cmap_scan_completed = False`, `is_complete = False`), a daemon worker thread always follows up with `full_diagnostics()`.
2. **Stale Callback Cancellation (`_diag_request_id`)**:
   - Every file selection increments `self._diag_request_id`.
   - The background `full_diagnostics()` worker checks `cancel_check=lambda: self._diag_request_id != req_id` between pages and marshals UI updates back to the main thread via `self.root.after(0, ...)`. If the user selects another PDF while a scan is in flight, stale results are discarded.
3. **Manual Metadata Preservation**:
   - `_apply_auto_metadata()` tracks `self._last_auto_title` and `self._last_auto_author`. Embedded PDF metadata populates the Title and Author fields only when they are empty or still hold the previous file's auto-filled value, never overwriting text typed manually by the user.

---

## 3. External Process Execution & Memory Management (`core/converter.py`)

Lume coordinates three external tools (**Marker**, **Pandoc**, and **Calibre**) via Python's `subprocess` module. Note that these calls are used for **process separation and memory lifecycle management**, not security sandboxing:

1. **Chunked Marker Execution (`_CHUNKED_MARKER_SCRIPT`)**:
   - Processing a 300–500 page PDF in a single Marker pass can exhaust system RAM (`numpy._core._exceptions._ArrayMemoryError`) or GPU VRAM.
   - Lume invokes the target Python environment in a subprocess that loads the Surya/Marker model dictionary once and iterates in **50-page chunks** (`page_range`), calling `gc.collect()` and `torch.cuda.empty_cache()` after each batch.
   - Within the same pass, `JSONRenderer` extracts block-level provenance (`provenance_blocks.json`) from the in-memory `Document` object without running OCR a second time.
2. **Pandoc Compilation**:
   - Invoked synchronously via `subprocess.run(..., check=True)` with explicit UTF-8 encoding and BCP-47 language metadata (`-M lang=pt-BR`) so Linux environments with `LANG=C.UTF-8` never emit malformed `<dc:language>C</dc:language>` tags.
3. **Calibre Export (`ebook-convert`)**:
   - Invoked with a `timeout=600` guard and temporary disk files (`tempfile.TemporaryFile()`) for `stdout`/`stderr` instead of `subprocess.PIPE`. On Windows, `ebook-convert` can spawn detached `QtWebEngineProcess.exe` helper processes that inherit pipe handles and block `communicate()` indefinitely if standard pipes are used.
   - Note: Marker and Pandoc executions do not enforce a fixed wall-clock timeout because CPU-only OCR on large books can legitimately run for extended periods.

---

## 4. Report Security & Privacy by Default (`core/reporting.py`)

1. **XSS Prevention & Offline CSP in `comparison_report.html`**:
   - Text extracted from untrusted PDFs may contain literal `<script>`, `<img>`, or malformed HTML strings. Every dynamic string injected into `comparison_report.html` passes through `html.escape(str(s), quote=True)`.
   - The generated HTML document declares an inline Content Security Policy:
     `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline';"/>`
     This blocks external network requests and script execution while allowing local relative thumbnails (`comparison_assets/page_NNN.jpg`).
2. **Path Sanitization in `restoration_report.json`**:
   - By default (`include_full_paths=False`), `build_restoration_report()` omits local filesystem directories (`C:\Users\...` or `/home/...`) across all sections of the JSON report:
     - `input_metadata` stores only `"source_file": os.path.basename(pdf_path)`.
     - `diagnostics.to_dict(include_file_path=False)` omits `"file_path"`.
     - `export_results["generated_files"]` is sanitized to basename-only entries (`["Book.epub", "Book.azw3"]`).

---

## 5. Continuous Integration Scope (`.github/workflows/ci.yml`)

The GitHub Actions pipeline is intentionally split into two fast, deterministic jobs that do **not** require downloading multi-gigabyte PyTorch/Marker weights on CI runners:

1. **`lint-and-unit-tests` (Python 3.10, 3.11, 3.12)**:
   - Runs `ruff check core ui tests main.py` (`E` and `F` rule sets).
   - Runs `python -m pytest --cov=core` covering page classification, read-only PDF guarantees, UI concurrency, provenance resolution, XSS escaping, privacy sanitization, and OCF validation.
2. **`epubcheck-validation` (W3C EPUBCheck 5.4.0)**:
   - Compiles a **synthetic test Markdown document** (containing section headers, inline formatting, and footnotes) via Pandoc, heals and repackages it with `process_epub_html()`, verifies it with `validate_epub_structure()`, and validates full specification compliance using the official **W3C EPUBCheck 5.4.0** CLI.
   - This proves that Lume's HTML Healer and OCF packager produce standards-compliant EPUB 3 archives, while keeping CI execution under ~1 minute.
