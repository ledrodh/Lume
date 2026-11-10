# Lume User Guide

This guide covers environment setup across GPU and CPU platforms, running the desktop application, interpreting the pre-flight diagnostics dashboard, and inspecting the generated e-books and audit reports.

---

## 1. Prerequisites

1. **Python 3.10, 3.11, or 3.12**
2. **Pandoc**: Required to compile sanitized Markdown into base EPUB 3 archives ([Download Pandoc](https://pandoc.org/installing.html)).
3. **Calibre** *(Optional)*: Required only if exporting to **Kindle (`AZW3`)** or **reflowable `PDF`** via `ebook-convert` ([Download Calibre](https://calibre-ebook.com/download)).

---

## 2. Installation by Hardware Environment

Clone the repository and create a virtual environment:

```bash
git clone https://github.com/ledrodh/Lume.git
cd Lume
python -m venv venv
```

Activate the virtual environment:

- **Windows (PowerShell)**:
  ```powershell
  .\venv\Scripts\activate
  ```
- **Linux / macOS**:
  ```bash
  source venv/bin/activate
  ```

### Step 2.1 — Install PyTorch for Your Compute Device

Lume automatically detects `cuda`, `mps`, or `cpu` at runtime (`_detect_compute_device`), or you can force a specific device via the `LUME_DEVICE` environment variable (`cuda`, `mps`, or `cpu`). Install the PyTorch build matching your hardware before installing `requirements.txt`:

- **Option A — NVIDIA GPU (CUDA 12.1, Recommended for Scanned PDFs)**:
  ```bash
  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121
  ```
- **Option B — Apple Silicon (macOS M1/M2/M3/M4 with MPS) or Linux/Windows CPU-Only**:
  ```bash
  pip install torch torchvision torchaudio
  ```

### Step 2.2 — Install Lume Dependencies

```bash
pip install -r requirements.txt
```

---

## 3. Running Lume

Launch the desktop interface:

```bash
python main.py
```

### Step-by-Step Workflow

1. **Select a Source PDF**:
   - Click **Browse...** and choose your `.pdf` file.
   - Lume immediately runs a fast read-only preview (`< 100ms`) and launches a background page-by-page scan.
2. **Review the Pre-Flight Diagnostics Dashboard**:
   - **Pages & Cover**: Displays total page count, first-page dimensions in points, and whether the first page is a wide two-page spread candidate (`width > height * 1.05`) that will have its spine cropped automatically.
   - **Page Classification**: Breaks down the document into `Text` (`extractable_text`), `Scanned` (`image_only`), `Hybrid` (`mixed`), and `Empty` (`empty_or_unknown`).
   - **Images (Distinct / Total)**: Shows unique image `xref` objects versus total placement occurrences across pages.
   - **Footnote Candidates**: Heuristic estimate of bottom-of-page footnote lines detected in the text layer.
   - **Font / CMap Health**: Shows `Scanning xref streams...` until the background scan finishes, then reports either `Clean (0 corrupted CMap streams)` or the exact number of malformed `ToUnicode` CMap streams scheduled for repair.
   - **Recommended Strategy**:
     - `Direct Vector Extraction (--disable_ocr)` when `>= 85%` of non-empty pages are pure selectable text and `<= 15%` are scanned/hybrid.
     - `Full Neural Layout & OCR (Marker/Surya)` when scanned or hybrid pages exceed 15%.
3. **Confirm or Edit Book Metadata**:
   - Lume auto-populates **Book Title** and **Author** from embedded PDF metadata when available. Any manual edits you type into these fields are preserved even if the background scan completes afterward.
4. **Choose Output Formats & Start Restoration**:
   - Select one or more formats (`EPUB`, `Kindle (AZW3)`, `PDF (Text-based)`) and click **START RESTORATION**.
5. **Inspect the Visual Comparison Report**:
   - When conversion finishes, click **🔍 View Restoration Report** to open `comparison_report.html` in your default browser.

---

## 4. Understanding `Restored_Output/` Artifacts

Next to your source PDF, Lume creates a `Restored_Output/` directory containing:

| File / Folder | Purpose |
| --- | --- |
| `<Book_Title>.epub` | W3C EPUB 3.3 OCF-compliant e-book with healed paragraphs, Kindle-safe TOC, and bidirectional footnotes. |
| `<Book_Title>.azw3` | *(If requested)* Kindle e-book generated via Calibre `ebook-convert`. |
| `<Book_Title>.pdf` | *(If requested)* Reflowable text-based PDF generated via Calibre. |
| `restoration_report.json` | Versioned (`v1.1.0`) machine-readable audit report with pre-flight diagnostics, operational/structural metrics, transformation counts, provenance samples, and OCF validation results. |
| `comparison_report.html` | Offline, XSS-safe visual comparison report displaying KPI cards and side-by-side transformation samples (`Pre-Healing Extracted Text` vs. `Restored EPUB Structure`). |
| `comparison_assets/` | Controlled-resolution JPEG thumbnails (`page_NNN.jpg`) of source PDF pages referenced by transformation samples. |
| `process_log.txt` | Detailed execution log of cover clipping, CMap repair, 50-page Marker chunks, HTML healing, and validation. |

---

## 5. Running Tests & Linting

To execute the automated unit and structural validation suite locally:

```bash
python -m unittest discover -s tests -v
# or with pytest and coverage:
python -m pytest --cov=core -v
```

To run the Ruff linter:

```bash
ruff check core ui tests main.py
```
