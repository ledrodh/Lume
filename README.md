# Lume

**Lume** is a high-performance book digitizer designed to transform old, scanned PDF documents into modern, satisfying, and high-quality e-books. It specifically targets the restoration of classical literature, historical documents, and complex academic texts, ensuring they are perfectly readable on contemporary devices like the Amazon Kindle.

---

## 🚀 Features

* **🛡️ DNA Preservation Mode**: Intelligently extracts content while maintaining the original document's font dictionaries (CID) and structural metadata to prevent OCR failure on complex academic PDFs.
* **🖼️ Smart Cover Recovery**: Automatically extracts, upscales, and crops covers, intelligently detecting and removing spines from wide two-page scans.
* **✨ HTML Healing Engine**:
* Injects Kindle-optimized CSS for perfect justification and image scaling.
* Exorcises "ghost hyphenation" and dirty HTML tags caused by OCR interpretation.
* Reconstructs complex tables and traditional Table of Contents into flexible, Kindle-safe layouts.


* **🔗 Intelligent Footnotes**: Automatically detects, sanitizes, and reinjects footnotes with bidirectional navigation links (↩) for seamless reading.
* **📱 Multi-Format Export**: One-click generation of **EPUB**, **AZW3 (Kindle)**, and clean **Text-based PDF**.
* **🤖 Auto-Metadata Retrieval**: Automatically assigns clean filenames and titles if metadata is omitted.
* **🖥️ Native GUI**: A clean, OS-aware graphical interface built with Tkinter for frictionless operation.

---

## 🛠️ Technologies & Tools

Lume leverages a powerful stack of industry-standard tools to achieve professional-grade results:

| Category | Tool | Description |
| --- | --- | --- |
| **OCR Engine** | [Marker](https://github.com/vikashelina/marker) | High-speed, deep-learning based PDF to Markdown conversion (CUDA accelerated). |
| **Conversion** | [Pandoc](https://pandoc.org/) | The "universal document converter" for base EPUB generation and metadata injection. |
| **E-book Management** | [Calibre](https://calibre-ebook.com/) | Robust engine for reliable AZW3 and final text-based PDF formatting. |
| **PDF Processing** | [PyMuPDF (Fitz)](https://pymupdf.readthedocs.io/) | Fast and reliable PDF parsing, page isolation, and cover extraction. |
| **HTML Cleaning** | [BeautifulSoup4](https://www.crummy.com/software/BeautifulSoup/) | Precision manipulation of document structure, DOM trees, and CSS styling. |
| **UI Framework** | [Tkinter](https://docs.python.org/3/library/tkinter.html) | Simple and native cross-platform graphical interface. |

---

## 📋 Prerequisites

Ensure you have the following installed on your system before running Lume:

1. **Python 3.10+**
2. **NVIDIA GPU & CUDA Toolkit**: Highly recommended for the Marker OCR engine to process books in minutes rather than hours.
3. **Calibre**: Necessary for AZW3 and PDF output. ([Download](https://calibre-ebook.com/download))
4. **Pandoc**: Necessary for initial EPUB assembly. ([Download](https://pandoc.org/installing.html))

---

## ⚙️ Installation

1. **Clone the repository:**

```bash
git clone https://github.com/YOUR_USERNAME/lume.git
cd lume

```

2. **Create a virtual environment (Recommended):**

```bash
python -m venv venv
venv\Scripts\activate  # On Windows
# source venv/bin/activate  # On Linux/Mac

```

3. **Install PyTorch with CUDA support:**
*(Ensure you install the correct PyTorch version for your specific CUDA environment. Below is an example for CUDA 12.1)*

```bash
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu121

```

4. **Install Lume's dependencies:**

```bash
pip install marker-pdf pymupdf beautifulsoup4 pypandoc

```

---

## 📖 How to Use

1. **Launch the application:**

```bash
python main.py

```

2. **Browse** and select your source PDF file.
3. *(Optional)* Enter the **Book Title** and **Author**. If omitted, Lume will automatically use the sanitized filename.
4. Select your desired **Output Formats** (EPUB, AZW3, PDF).
5. Click **START RESTORATION**.
6. Track the background processing logs in the terminal or wait for the success prompt. Find your polished e-books in the `Restored_Output` folder located next to your original PDF.

---

## 📂 Project Architecture

```text
Lume/
├── main.py              # Application entry point & Theme initialization
├── ui/
│   └── main_window.py   # Tkinter GUI logic, threading, and user input validation
└── core/
    ├── converter.py     # Main orchestration logic, CLI routing, and path bulletproofing
    ├── pdf_handler.py   # Cover extraction and DNA-preserving content splitting
    └── html_healer.py   # HTML/CSS optimization, TOC reconstruction, and Footnote fixing

```
