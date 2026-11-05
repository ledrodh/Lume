# Lume

**Lume** is a document restoration and e-book conversion pipeline designed to transform complex academic PDFs, philosophical treatises, and scanned books into clean, navigable e-books (**EPUB 3**, **Kindle AZW3**, and **reflowable PDF**).

Unlike basic PDF-to-EPUB converters that dump raw OCR text with broken lines, unlinked footnotes, and corrupted font encodings, Lume combines layout-aware extraction (**Marker / Surya**) with a custom **Triple-Pass HTML Healing Engine** that repairs broken paragraphs across page boundaries, repairs malformed `ToUnicode` CMaps, reconstructs Tables of Contents, and links footnotes bidirectionally.

---

## 🚀 Key Capabilities

* **🛡️ DNA Preservation & CMap Sanitization**: Extracts the cover and content stream while preserving embedded CID font dictionaries and repairing malformed `ToUnicode` CMap streams (such as Mac OS X Quartz `Symbol` font em-dashes `<21>< 23af f8e7 >` that standard parsers misread as `!`).
* **📄 Native Digital vs. Scanned PDF Detection**: Automatically detects whether a PDF contains a clean vector text layer (`is_born_digital_pdf`) to bypass optical OCR (`--disable_ocr`), preserving 100% of the original typography at ~3× higher speed while falling back to full neural OCR on scanned pages.
* **🧠 Memory-Safe Chunked GPU Execution**: Processes large books (300+ pages) in 50-page batches while reusing loaded GPU models in VRAM and flushing intermediate tensors (`gc.collect()` + `torch.cuda.empty_cache()`), preventing NumPy/Surya `_ArrayMemoryError` crashes. Automatically detects `CUDA`, `MPS`, or `CPU` at runtime.
* **🖼️ Rotation-Safe Cover Recovery**: Extracts, upscales (4×), and crops spine regions from wide two-page spreads using visual coordinate clipping (`page.rect`), avoiding `CropBox not in MediaBox` failures on rotated (`90°`/`270°`) or offset-origin PDFs.
* **✨ Triple-Pass HTML Healing Engine**:
  * **Paragraph Stitching**: Rejoins sentences split across page breaks and across removed bottom-of-page footnote blocks, stripping leaked running page numbers.
  * **Footnote Extraction & Bidirectional Linking**: Extracts single-line, merged multi-note (`<sup>1</sup> ... <sup>2</sup> ...`), cross-page, and multi-paragraph footnotes, linking body references (`noteref` ↔ `↩`) across words, inline tags (`</em>`), guillemets (`»`), curly quotes (`”`), and ellipses (`…`).
  * **Kindle-Safe TOC & CSS**: Converts rigid HTML tables of contents into float-based entries compatible with Amazon Kindle (`AZW3`) and packages the output strictly according to the **W3C EPUB 3.3 OCF** specification (`mimetype` stored first with `ZIP_STORED`).
* **🏷️ Metadata Resolution with Fallback**: Reads embedded PDF `title` and `author` metadata when left blank in the UI, falling back to a sanitized filename and `"Unknown"` if the PDF has no embedded metadata.

---

## 🏗️ Pipeline Architecture

```text
Source PDF
   │
   ▼
[1. PDF Handler (PyMuPDF)]
   ├── Rotation-safe cover extraction & spine cropping (cover.jpg)
   ├── Malformed ToUnicode CMap repair (Symbol em-dash recovery)
   └── Native vector text detection (is_born_digital_pdf)
   │
   ▼
[2. Chunked Layout & OCR Engine (Marker 1.x / Surya)]
   ├── Automatic device selection (CUDA / MPS / CPU)
   └── Memory-safe 50-page batch conversion -> Raw Markdown
   │
   ▼
[3. Markdown Sanitizer & Pandoc]
   ├── Section header normalization & missing section recovery
   ├── Numbered paragraph escaping (prevents false <ol> renumbering)
   └── Base EPUB compilation with embedded cover & metadata
   │
   ▼
[4. Triple-Pass HTML Healer (BeautifulSoup4)]
   ├── Pass 1: False <sup> unwrapping, footnote extraction & cross-page paragraph stitching
   ├── Pass 2: Kindle-safe TOC transformation & context-aware footnote reference linking
   └── Pass 3: Bidirectional footnote reinjection & W3C EPUB 3.3 OCF packaging (ZIP_STORED mimetype)
   │
   ▼
[5. Multi-Format Export (Calibre CLI)]
   └── Final outputs: .epub, .azw3 (Kindle), and reflowable .pdf
```

---

## 📊 Measured Benchmark (334-Page Academic Book)

Evaluated on the Portuguese academic edition of Ernst Jünger's *O Trabalhador — Domínio e Figura* (334 pages, dense philosophical text with 123 footnotes, 80 numbered sections, translator's introduction, and corrupted Quartz `Symbol` font CMaps):

| Metric | Baseline (Raw Marker + Pandoc) | Lume Restored Output |
| --- | --- | --- |
| **334-Page Full Run Stability** | Crashed (`_ArrayMemoryError` in RAM) | **100% Completed** (50-page GPU chunks) |
| **Footnotes Extracted** | 0 / 123 (0.0%) | **123 / 123 (100.0%)** |
| **Bidirectional Footnote Links (`noteref` ↔ `↩`)** | 0 / 123 (0.0%) | **123 / 123 (100.0%)** |
| **Numbered Book Sections Preserved (`1.`–`80.`)** | Broken into empty `<ol>` lists | **80 / 80 (100.0%)** |
| **Corrupted `Symbol` Font Em-Dashes (`—`)** | 97 extracted as `!` or `⎯\uf8e7` | **328 / 328 clean `—` (0 corrupted chars)** |
| **Leaked Page Numbers / False `<sup>` Tags** | 300+ artifacts in body text | **0 remaining** |
| **W3C EPUB 3.3 OCF Container Check** | Invalid (`mimetype` deflated/unordered) | **Valid (`mimetype` first, `ZIP_STORED`)** |

---

## 🛠️ Technology Stack

| Category | Tool | Role in Pipeline |
| --- | --- | --- |
| **Layout & OCR** | [Marker](https://github.com/VikParuchuri/marker) | Deep-learning PDF layout analysis and Markdown extraction (`CUDA` / `MPS` / `CPU`). |
| **EPUB Compiler** | [Pandoc](https://pandoc.org/) | Base EPUB 3 generation and metadata injection. |
| **E-book Conversion** | [Calibre](https://calibre-ebook.com/) | `ebook-convert` CLI for Kindle (`AZW3`) and reflowable `PDF` generation. |
| **PDF Manipulation** | [PyMuPDF (fitz)](https://pymupdf.readthedocs.io/) | Cover rendering, `ToUnicode` CMap stream repair, and text-layer inspection. |
| **DOM & HTML Healing** | [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) | Structural DOM manipulation, paragraph stitching, and footnote linking. |
| **Desktop GUI** | [Tkinter](https://docs.python.org/3/library/tkinter.html) | Thread-safe native desktop interface. |

---

## 📋 Prerequisites

1. **Python 3.10+**
2. **Pandoc**: Required for base EPUB compilation ([Download](https://pandoc.org/installing.html)).
3. **Calibre**: Required if exporting to **AZW3** or **PDF** ([Download](https://calibre-ebook.com/download)).
4. **NVIDIA GPU with CUDA** *(Optional, Recommended)*: Lume automatically uses `CUDA` when available and falls back to `MPS` or `CPU` when running without a dedicated GPU.

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
2. *(Optional)* Enter the **Book Title** and **Author**. If left empty, Lume inspects the PDF's embedded metadata and falls back to the sanitized filename.
3. Choose one or more **Output Formats** (`EPUB`, `Kindle (AZW3)`, `PDF`).
4. Click **START RESTORATION**. Output files and `process_log.txt` are written to the `Restored_Output` folder next to the source PDF.

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
├── main.py              # Application entry point & native theme initialization
├── requirements.txt     # Pinned dependency specifications
├── ui/
│   └── main_window.py   # Thread-safe Tkinter GUI & conversion status reporting
├── core/
│   ├── converter.py     # Pipeline orchestration, device detection & Markdown sanitizer
│   ├── pdf_handler.py   # Rotation-safe cover extraction, CMap repair & PDF inspection
│   └── html_healer.py   # Triple-Pass HTML healer, footnote linker & OCF EPUB packager
└── tests/
    └── test_lume.py     # Automated unit and integration test suite
```
