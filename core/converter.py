 core/converter.py
import os 
import re 
import shutil 
import subprocess 
import pypandoc 
from pathlib import Path 
 
from core.pdf_handler import extract_cover_and_content 
from core.html_healer import process_epub_html 
 
# ───────────────────────────────────────────────────────────────────────────── 
# SYSTEM SETTINGS 
# ───────────────────────────────────────────────────────────────────────────── 
def get_calibre_path():
    path = shutil.which("ebook-convert")
    if path:
        return path
    
    common_paths = [
        r"C:\Program Files\Calibre2\ebook-convert.exe",
        r"C:\Program Files (x86)\Calibre2\ebook-convert.exe",
        "/usr/bin/ebook-convert",
        "/usr/local/bin/ebook-convert",
        "/Applications/calibre.app/Contents/MacOS/ebook-convert"
    ]
    for p in common_paths:
        if os.path.exists(p):
            return p
    return "ebook-convert"

CALIBRE_EXE = get_calibre_path()
 
# ───────────────────────────────────────────────────────────────────────────── 
# UTILS 
# ───────────────────────────────────────────────────────────────────────────── 
 
def _log(log_path: str, msg: str): 
    with open(log_path, 'a', encoding='utf-8') as f: 
        f.write(msg + '\n') 
    print(msg) 
 
def _find_generated_md(work_dir: str) -> str | None: 
    work = Path(work_dir) 
    stem = "content" 
    candidates = [work / stem / f"{stem}.md", work / f"{stem}.md"] 
    for c in candidates: 
        if c.exists(): return str(c) 
    all_files = [p for p in work.rglob("*.md") if '_meta' not in p.name and p.is_file()] 
    if all_files: 
        all_files.sort(key=lambda p: len(p.parts)) 
        return str(all_files[0]) 
    return None 
 
def _sanitize_name(text: str, fallback: str = "Book") -> str: 
    name = re.sub(r'[^\w\s\-]', '', text or '').strip() 
    return name.replace(' ', '_') or fallback 
 
# ───────────────────────────────────────────────────────────────────────────── 
# MAIN FUNCTION 
# ───────────────────────────────────────────────────────────────────────────── 
 
def process_book(pdf_in: str, out_dir: str, title: str, author: str, 
                 formats: list, start_page: int = 1): 
     
    if not title or not title.strip(): 
        title = os.path.splitext(os.path.basename(pdf_in))[0] 
     
    if not author or not author.strip(): 
        author = "Unknown" 
 
    pdf_in = os.path.abspath(pdf_in) 
    out_dir = os.path.abspath(out_dir) 
    work_dir = os.path.join(out_dir, "workdir") 
    marker_in_dir = os.path.join(work_dir, "marker_input") 
    log_path = os.path.join(out_dir, "process_log.txt") 
 
    if os.path.exists(work_dir): shutil.rmtree(work_dir) 
    os.makedirs(marker_in_dir, exist_ok=True) 
    os.makedirs(out_dir, exist_ok=True) 
 
    if os.path.exists(log_path): os.remove(log_path) 
    log = lambda msg: _log(log_path, msg) 
 
    # 1. Extraction 
    content_pdf = os.path.join(marker_in_dir, "content.pdf") 
    cover_jpg = os.path.join(work_dir, "cover.jpg") 
    extract_cover_and_content(pdf_in, cover_jpg, content_pdf, start_page, log_path) 
 
    # 2. OCR (GPU) 
    env = os.environ.copy() 
    env["TORCH_DEVICE"] = "cuda" 
    log("🔍 Running OCR via Marker (GPU)...") 
     
    res_marker = subprocess.run(["marker", marker_in_dir, "--output_dir", work_dir],  
                                capture_output=True, text=True, env=env) 
     
    if res_marker.returncode != 0: 
        raise Exception(f"Marker failed:\n{res_marker.stderr[:800]}") 
 
    # 3. MD File Localization 
    md_path = _find_generated_md(work_dir) 
    if not md_path: 
        raise Exception("Marker finished, but did not generate a Markdown file. Check if the PDF is not just blank images or if it has DRM protection.") 
 
    # 4. Sanitization and Pandoc 
    with open(md_path, 'r', encoding='utf-8') as f: md_text = f.read() 
    md_text = re.sub(r'\s(id|name)=["\'][^"\']+["\']', '', md_text) 
    with open(md_path, 'w', encoding='utf-8') as f: f.write(md_text) 
 
    log("📦 Generating base EPUB with Pandoc...") 
    temp_epub = os.path.join(os.path.dirname(md_path), "temp.epub") 
     
    try: 
        pandoc_exe = pypandoc.get_pandoc_path() 
    except: 
        pandoc_exe = "pandoc" 
 
    pandoc_cmd = [pandoc_exe, md_path, "-o", temp_epub] 
    if os.path.exists(cover_jpg): 
        pandoc_cmd += ["--epub-cover-image", cover_jpg] 
     
    pandoc_cmd += ["-M", f"title={title}", "-M", f"author={author}"] 
     
    subprocess.run(pandoc_cmd, check=True, capture_output=True, text=True) 
 
    # 5. HTML Healing 
    base_name = _sanitize_name(title) 
    epub_final = os.path.join(out_dir, f"{base_name}.epub") 
    process_epub_html(temp_epub, epub_final, log_path) 
 
    # 6. Conversions (Robust Calibre) 
    calibre_path = CALIBRE_EXE 
 
    for fmt in formats: 
        if fmt in ["AZW3", "PDF"]: 
            out_file = os.path.join(out_dir, f"{base_name}.{fmt.lower()}") 
            log(f"📱 Converting to {fmt}...") 
            try: 
                subprocess.run([calibre_path, epub_final, out_file], check=True, capture_output=True, text=True) 
                log(f"✅ Generated: {out_file}") 
            except Exception as e: 
                log(f"⚠ Conversion error {fmt}: {str(e)}") 
 
    log("🎉 Restoration complete!")