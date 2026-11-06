# Lume

**Lume** is a document restoration, provenance auditing, and e-book validation platform designed to transform complex academic PDFs, philosophical treatises, and historical scans into clean, navigable e-books (**EPUB 3**, **Kindle AZW3**, and **reflowable PDF**).

Unlike generic PDF-to-EPUB converters that dump raw OCR text with broken lines, unlinked footnotes, and unverified archive structures, Lume is built around four observable engineering pillars:

1. **🔍 Pre-Flight Document Diagnostics**: Two-stage non-blocking inspection (`quick_diagnostics` + background `full_diagnostics`) that classifies every page into `extractable_text`, `image_only`, `mixed` (hybrid/OCR-overlay), or `empty_or_unknown`, measures distinct vs. repeated image occurrences, estimates footnote density, and performs strictly read-only detection of malformed `ToUnicode` CMap streams before conversion begins.
2. **✨ Structural Transformation & Triple-Pass HTML Healing**: Combines memory-safe 50-page chunked GPU/CPU extraction (**Marker 1.x / Surya**) with a custom DOM healing engine that repairs broken paragraphs across page boundaries, unwraps false superscripts, rebuilds Kindle-safe Tables of Contents, and links footnotes bidirectionally (`noteref` ↔ `↩`).
3. **📊 Provenance Tracking & Visual Comparator**: Indexes Marker's JSON block tree (`/page/N/Text/M`) alongside PyMuPDF page text to map restored EPUB paragraphs and footnotes back to their exact source PDF pages. Automatically generates a versioned `restoration_report.json` (`schema_version = "1.0.0"`) and an offline, XSS-safe side-by-side visual comparison report (`comparison_report.html`).
4. **🛡️ Dual-Layer EPUB 3.3 Validation**: Verifies every generated archive locally via `core/epub_validator.py` (checking `ZIP_STORED` `mimetype` positioning, `META-INF/container.xml`, OPF manifest/spine integrity, XML well-formedness, and generic resolution of all internal `href`/`src` links and `#fragment` anchors) and validates full specification compliance in CI via **W3C EPUBCheck 5.4.0**.

---

## 🏗️ Pipeline Architecture

```text
Source PDF
   │
   ├──► [Stage 0: Two-Stage Pre-Flight Diagnostics (core/diagnostics.py)]
   │       ├── Quick Preview (< 100ms): Page count, cover aspect ratio, metadata & sampled classification
   │       └── Full Background Scan: Per-page 4-state classification, image area ratio & read-only CMap scan
   │
   ▼
[Stage 1: PDF Handler (core/pdf_handler.py)]
   ├── Rotation-safe cover extraction & wide-spread spine cropping (cover.jpg)
   └── Malformed ToUnicode CMap stream repair (Symbol font em-dash recovery)
   │
   ▼
[Stage 2: Chunked Layout, OCR & Provenance Engine (core/converter.py)]
   ├── Automatic compute device detection (CUDA / MPS / CPU)
   ├── Memory-safe 50-page batch execution -> Raw Markdown + Images
   └── Single-pass Marker JSONRenderer block extraction -> provenance_blocks.json
   │
   ▼
[Stage 3: Markdown Sanitizer & Pandoc]
   ├── Section header normalization & missing/footer-dropped section recovery
   ├── Numbered paragraph escaping (prevents false <ol> renumbering)
   └── Base EPUB 3 compilation with embedded cover & resolved metadata
   │
   ▼
[Stage 4: Triple-Pass HTML Healer (core/html_healer.py)]
   ├── Pass 1: False <sup> unwrapping, footnote extraction & cross-page paragraph stitching
   ├── Pass 2: Kindle-safe TOC transformation & context-aware footnote reference linking
   └── Pass 3: Bidirectional footnote reinjection & W3C EPUB 3.3 OCF packaging (ZIP_STORED mimetype)
   │
   ▼
[Stage 5: Validation, Telemetry & Multi-Format Export]
   ├── Internal OCF, XML & generic link/anchor validation (core/epub_validator.py)
   ├── Calibre CLI export (.epub, .azw3, reflowable .pdf)
   └── Versioned restoration_report.json & side-by-side comparison_report.html (core/reporting.py)
```

---

## 📊 Measured Benchmark (334-Page Academic Reference Book)

Evaluated on the Portuguese academic edition of Ernst Jünger's *O Trabalhador — Domínio e Figura* (334 pages, dense philosophical treatise containing 123 footnotes, 80 numbered book sections, translator's introduction, and corrupted Quartz `Symbol` font CMaps):

| Metric | Category | Baseline (Raw Marker + Pandoc) | Lume Restored Output |
| --- | --- | --- | --- |
| **334-Page Full Run Stability** | Operational | Crashed (`_ArrayMemoryError` in RAM) | **100% Completed** (50-page GPU chunks) |
| **Corrupted `ToUnicode` CMap Streams Repaired** | Operational | 0 (97 em-dashes extracted as `!`) | **1 stream repaired / 328 clean `—` dashes** |
| **Leaked Page Numbers & False `<sup>` Removed** | Operational | 300+ artifacts left in body text | **100% removed (0 remaining)** |
| **Footnotes Extracted** | Structural | 0 / 123 | **123 / 123** |
| **Bidirectional Footnote Links (`noteref` ↔ `↩`)** | Structural | 0 / 123 | **123 / 123** |
| **Numbered Book Sections Preserved (`1.`–`80.`)** | Structural | Broken into empty `<ol>` lists | **80 / 80** |
| **Footnote Precision / Recall (Verified Ground Truth)** | Quality | 0.0% / 0.0% | **100.0% Precision / 100.0% Recall** |
| **W3C EPUB 3.3 OCF & Internal Link Integrity** | Validation | Invalid (`mimetype` deflated) | **0 errors, 0 broken links** |

---

## 🛠️ Technology Stack

| Category | Tool | Role in Pipeline |
| --- | --- | --- |
| **Layout & OCR** | [Marker](https://github.com/VikParuchuri/marker) (`>=1.0.0,<2.0.0`) | Deep-learning PDF layout analysis, Markdown rendering, and JSON block provenance (`CUDA` / `MPS` / `CPU`). |
| **EPUB Compiler** | [Pandoc](https://pandoc.org/) | Base EPUB 3 generation and metadata injection. |
| **E-book Conversion** | [Calibre](https://calibre-ebook.com/) | `ebook-convert` CLI for Kindle (`AZW3`) and reflowable `PDF` generation. |
| **PDF Manipulation** | [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/) | Pre-flight diagnostics, rotation-safe cover clipping, and `ToUnicode` CMap stream repair. |
| **DOM & HTML Healing** | [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) | Triple-Pass DOM healing, cross-page paragraph stitching, and footnote linking. |
| **Validation & CI** | `core/epub_validator.py` + [EPUBCheck 5.4.0](https://github.com/w3c/epubcheck) | Local OCF/XML/link verification and automated W3C conformance checking in GitHub Actions. |
| **Desktop GUI** | [Tkinter](https://docs.python.org/3/library/tkinter.html) | Thread-safe desktop interface with live pre-flight diagnostics and 1-click comparison report viewer. |

---

## 📋 Prerequisites

1. **Python 3.10+**
2. **Pandoc**: Required for base EPUB compilation ([Download](https://pandoc.org/installing.html)).
3. **Calibre**: Required if exporting to **AZW3** or **PDF** ([Download](https://calibre-ebook.com/download)).
4. **NVIDIA GPU with CUDA** *(Optional, Recommended)*: Lume automatically detects `CUDA` when available and falls back to `MPS` or `CPU` on machines without an NVIDIA GPU.

---

## ⚙️ Installation

1. **Clone the repository:**

```bash
git clone https://github.com/ledrodh/Lume.git
cd Lume
```

2. **Create and activate a virtual environment:**

On Windows (PowerShell / CMD):
```powershell
python -m venv venv
.\venv\Scripts\activate
```

On Linux / macOS:
```bash
python3 -m venv venv
source venv/bin/activate
```

3. **Install PyTorch (with CUDA support if using an NVIDIA GPU):**

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
```

4. **Install Lume dependencies:**

```bash
pip install -r requirements.txt
```

---

## 📖 Usage

### Graphical Interface

```bash
python main.py
```

1. Click **Browse...** and select a source PDF file.
2. Review the **Document Pre-Flight Diagnostics** panel: Lume immediately shows a quick preview and completes a background page-by-page scan displaying page classifications (`Text`, `Scanned`, `Hybrid`, `Empty`), distinct image counts, heuristic footnote candidates, CMap health, and the recommended OCR strategy.
3. *(Optional)* Enter or adjust the **Book Title** and **Author**. Lume auto-populates embedded PDF metadata without overwriting values you have typed manually.
4. Select your desired **Output Formats** (`EPUB`, `Kindle (AZW3)`, `PDF`) and click **START RESTORATION**.
5. Once complete, click **🔍 View Restoration Report** to open the side-by-side visual comparison and provenance report (`comparison_report.html`) in your browser.

### Running Automated Tests

```bash
python -m unittest discover -s tests -v
# or with pytest:
pytest -v
```

---

## 📂 Project Structure

```text
Lume/
├── main.py                        # Application entry point & native theme initialization
├── pyproject.toml                 # Pytest and Ruff configuration
├── requirements.txt               # Pinned runtime and test dependencies
├── .github/
│   └── workflows/
│       └── ci.yml                 # GitHub Actions CI (Ruff, Pytest matrix 3.10-3.12, W3C EPUBCheck 5.4.0)
├── ui/
│   └── main_window.py             # Thread-safe Tkinter GUI, async diagnostics dashboard & report launcher
├── core/
│   ├── models.py                  # Versioned dataclasses (RestorationReport, DocumentDiagnostics, HealingStats)
│   ├── diagnostics.py             # Two-stage read-only PDF analyzer & 4-state page classifier
│   ├── pdf_handler.py             # Rotation-safe cover clipping & ToUnicode CMap stream sanitization
│   ├── converter.py               # Pipeline orchestrator, device detection & chunked Marker execution
│   ├── html_healer.py             # Triple-Pass HTML healer, paragraph stitcher & OCF EPUB packager
│   ├── epub_validator.py          # Internal OCF, OPF, XML well-formedness & generic link/anchor validator
│   └── reporting.py               # Marker/PDF provenance resolver & XSS-safe visual HTML comparator
└── tests/
    └── test_lume.py               # Automated unit, concurrency, security & OCF validation test suite
```
