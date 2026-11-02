import sys
import os
import re
import shutil
import tempfile
import subprocess
import pypandoc
import fitz
from pathlib import Path

from core.pdf_handler import extract_cover_and_content, is_born_digital_pdf
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


def get_marker_path():
    exe_name = "marker_single.exe" if os.name == "nt" else "marker_single"
    # 1. Pasta Scripts do mesmo interpretador Python que está rodando este script
    venv_scripts = Path(sys.executable).parent
    candidate = venv_scripts / exe_name
    if candidate.exists():
        return str(candidate)

    # 2. Ambientes virtuais locais do projeto (caso o script tenha sido iniciado pelo Python global)
    here = Path(__file__).resolve()
    for parent in [here.parents[1], here.parents[2]]:
        for venv_dir in ["venv", ".venv"]:
            cand = parent / venv_dir / ("Scripts" if os.name == "nt" else "bin") / exe_name
            if cand.exists():
                return str(cand)

    # 3. PATH do sistema
    path = shutil.which("marker_single")
    if path:
        return path

    return "marker_single"


MARKER_EXE = get_marker_path()


def get_marker_python():
    """Retorna o executável Python do ambiente onde o Marker está instalado."""
    marker_path = Path(MARKER_EXE)
    if marker_path.exists():
        py_name = "python.exe" if os.name == "nt" else "python"
        cand = marker_path.parent / py_name
        if cand.exists():
            return str(cand)
    return sys.executable


# ─────────────────────────────────────────────────────────────────────────────
# UTILS
# ─────────────────────────────────────────────────────────────────────────────

def _log(log_path: str, msg: str):
    with open(log_path, 'a', encoding='utf-8') as f:
        f.write(msg + '\n')
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8', errors='replace'))


def _find_generated_md(work_dir: str) -> str | None:
    work = Path(work_dir)
    stem = "content"
    candidates = [work / stem / f"{stem}.md", work / f"{stem}.md"]
    for c in candidates:
        if c.exists():
            return str(c)
    all_files = [p for p in work.rglob("*.md") if '_meta' not in p.name and p.is_file()]
    if all_files:
        all_files.sort(key=lambda p: len(p.parts))
        return str(all_files[0])
    return None


def _sanitize_name(text: str, fallback: str = "Book") -> str:
    name = re.sub(r'[^\w\s\-]', '', text or '').strip()
    return name.replace(' ', '_') or fallback


def _sanitize_markdown(md_text: str, pdf_path: str | None = None) -> str:
    """
    Prepara o Markdown gerado pelo Marker antes da compilação com Pandoc:
    - Remove atributos id/name inválidos
    - Corrige tags <sup>&</sup>lt;sup>N</sup> corrompidas pelo OCR
    - Normaliza travessões corrompidos pela fonte Symbol ('⎯\uf8e7' ou ' ! ')
    - Converte números de seção isolados ('\n\n2.\n\n') em subtítulos '### 2.' (evitando listas vazias <ol><li></li></ol>)
    - Recupera números de seção isolados sem ponto ('\n\n53\n\n') ou suprimidos no rodapé de página ('67.')
    - Escapa números seguidos de ponto no início de parágrafo ('44. Texto' -> '44\\. Texto') para o Pandoc não destruir a numeração
    """
    md_text = re.sub(r'\s(id|name)=["\'][^"\']+["\']', '', md_text)
    md_text = re.sub(r'<sup>\s*&(?:amp;)?\s*</sup>\s*lt;sup>\s*(\d+)\s*</sup>', r'<sup>\1</sup>', md_text)
    md_text = md_text.replace('\u23af\uf8e7', '—').replace('\uf8e7', '—').replace('\u23af', '—')
    # Caso o pypdfium2 tenha extraído travessão Symbol como ' ! ' entre palavras/vírgulas
    md_text = re.sub(r'(?<=\s)!(?=\s|[,\.;:])', '—', md_text)
    md_text = re.sub(r'(?m)^!\s+', '— ', md_text)
    # Números de seção isolados em sua própria linha (ex.: "1.", "2.", ..., "80.") -> subtítulo H3 centralizado
    md_text = re.sub(r'(?m)^(\d{1,3})\.\s*$', r'### \1.', md_text)

    # Verifica se há números de seção sequenciais faltando (ex.: impressos sem ponto "53" ou no fim de página "67.")
    # Itera de trás para frente para não deslocar os índices de match ao modificar md_text
    sec_matches = list(re.finditer(r'(?m)^###\s+(\d{1,3})\.\s*$', md_text))
    if len(sec_matches) >= 2:
        for idx in range(len(sec_matches) - 2, -1, -1):
            curr_num = int(sec_matches[idx].group(1))
            next_num = int(sec_matches[idx + 1].group(1))
            if next_num == curr_num + 2:
                missing_num = curr_num + 1
                span_start = sec_matches[idx].end()
                span_end = sec_matches[idx + 1].start()
                segment = md_text[span_start:span_end]
                # Caso 1: O número da seção está isolado numa linha sem ponto final (ex.: "\n\n53\n\n")
                seg_fixed, count = re.subn(
                    rf'(?m)^[ \t]*{missing_num}[ \t]*$',
                    f'### {missing_num}.',
                    segment,
                    count=1
                )
                if count > 0:
                    md_text = md_text[:span_start] + seg_fixed + md_text[span_end:]
                elif pdf_path and os.path.exists(pdf_path):
                    # Caso 2: O número da seção ("67.") ficava na última linha da página do PDF e foi filtrado como rodapé
                    try:
                        import fitz
                        doc = fitz.open(pdf_path)
                        for page in doc:
                            lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
                            if len(lines) >= 2 and re.match(rf'^{missing_num}\.?$', lines[-1]):
                                anchor = lines[-2][-35:].strip()
                                if anchor and anchor in segment:
                                    pos = segment.find(anchor) + len(anchor)
                                    seg_fixed = segment[:pos] + f"\n\n### {missing_num}.\n\n" + segment[pos:]
                                    md_text = md_text[:span_start] + seg_fixed + md_text[span_end:]
                                    break
                        doc.close()
                    except Exception:
                        pass

    # Garante linha em branco antes e depois de cada subtítulo ### N. para o Pandoc
    md_text = re.sub(r'\n*(### \d{1,3}\.)\n*', r'\n\n\1\n\n', md_text)
    # Evita que o Pandoc transforme parágrafos numerados (ex.: na Sinopse "44. Chamamos técnica...") em listas <ol> renumeradas
    md_text = re.sub(r'(?m)^(\d{1,3})\.\s+(?=\S)', r'\1\. ', md_text)
    return md_text


_CHUNKED_MARKER_SCRIPT = """
import os
import sys
import gc
import torch
import fitz
from pathlib import Path
from marker.config.parser import ConfigParser
from marker.models import create_model_dict

pdf_path = sys.argv[1]
work_dir = sys.argv[2]
disable_ocr = sys.argv[3] == "1"
log_path = sys.argv[4]
chunk_size = 50

def log(msg):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(msg + "\\n")
    try:
        print(msg, flush=True)
    except Exception:
        pass

doc = fitz.open(pdf_path)
total_pages = len(doc)
doc.close()

out_folder = Path(work_dir) / "content"
out_folder.mkdir(parents=True, exist_ok=True)

models = create_model_dict()
md_chunks = []

for start_idx in range(0, total_pages, chunk_size):
    end_idx = min(start_idx + chunk_size, total_pages)
    page_range_str = f"{start_idx}-{end_idx - 1}"
    log(f"-> Processing pages {start_idx + 1} to {end_idx} of {total_pages}...")

    cli_opts = {
        "output_dir": work_dir,
        "output_format": "markdown",
        "page_range": page_range_str,
        "disable_ocr": disable_ocr,
        "disable_tqdm": True,
    }
    config_parser = ConfigParser(cli_opts)
    converter_cls = config_parser.get_converter_cls()
    converter = converter_cls(
        config=config_parser.generate_config_dict(),
        artifact_dict=models,
        processor_list=config_parser.get_processors(),
        renderer=config_parser.get_renderer(),
        llm_service=config_parser.get_llm_service(),
    )
    rendered = converter(pdf_path)
    md_chunks.append(rendered.markdown.strip())
    if getattr(rendered, "images", None):
        for img_name, img_obj in rendered.images.items():
            img_obj.save(out_folder / img_name)

    del rendered
    del converter
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

final_md = "\\n\\n".join(md_chunks) + "\\n"
(out_folder / "content.md").write_text(final_md, encoding="utf-8")
log(f"-> All {total_pages} pages successfully converted to Markdown.")
"""


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

    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    os.makedirs(marker_in_dir, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    if os.path.exists(log_path):
        os.remove(log_path)
    log = lambda msg: _log(log_path, msg)

    # 1. Extraction
    content_pdf = os.path.join(marker_in_dir, "content.pdf")
    cover_jpg = os.path.join(work_dir, "cover.jpg")
    extract_cover_and_content(pdf_in, cover_jpg, content_pdf, start_page, log_path)

    # 2. OCR / Layout Extraction (GPU, Chunked to avoid ArrayMemoryError on large books)
    env = os.environ.copy()
    env["TORCH_DEVICE"] = "cuda"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"

    # Bloqueio agressivo do vLLM/Docker para todos os submódulos
    env["INFERENCE_BACKEND"] = "torch"
    env["SURYA_INFERENCE_BACKEND"] = "torch"
    env["MARKER_INFERENCE_BACKEND"] = "torch"
    env["LAYOUT_BACKEND"] = "torch"
    env["RECOGNITION_BACKEND"] = "torch"
    env["VLM_BACKEND"] = "torch"

    content_pdf_path = os.path.join(marker_in_dir, "content.pdf")
    disable_ocr_flag = "1" if is_born_digital_pdf(content_pdf_path) else "0"

    if disable_ocr_flag == "1":
        log("📄 Native digital text layer detected -> enabling --disable_ocr for 100% text fidelity and 3x speed.")

    marker_py = get_marker_python()
    log("🔍 Running Marker in memory-safe 50-page chunks (GPU com PyTorch Nativo)...")
    log(f"-> Python/Marker environment resolved at: {marker_py}")

    try:
        res_marker = subprocess.run(
            [marker_py, "-c", _CHUNKED_MARKER_SCRIPT, content_pdf_path, work_dir, disable_ocr_flag, log_path],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env
        )
    except FileNotFoundError as e:
        log(f"CRITICAL: não foi possível localizar/executar o Python do Marker.\nCaminho tentado: {marker_py}\nErro: {e}")
        raise Exception(
            f"O ambiente Python do Marker não foi encontrado.\n"
            f"Caminho tentado: {marker_py}"
        )

    if res_marker.returncode != 0:
        log(f"CRITICAL MARKER ERROR:\n{res_marker.stderr}")
        error_tail = res_marker.stderr.strip()[-1000:]
        raise Exception(f"Marker failed! See process_log.txt.\nEnd of error:\n{error_tail}")

    # 3. MD File Localization
    md_path = _find_generated_md(work_dir)
    if not md_path:
        raise Exception("Marker finished, but did not generate a Markdown file. Check if the PDF is not just blank images or if it has DRM protection.")

    # 4. Sanitization and Pandoc
    with open(md_path, 'r', encoding='utf-8') as f:
        md_text = f.read()
    md_text = _sanitize_markdown(md_text, content_pdf_path)
    with open(md_path, 'w', encoding='utf-8') as f:
        f.write(md_text)

    log("📦 Generating base EPUB with Pandoc...")
    temp_epub = os.path.join(os.path.dirname(md_path), "temp.epub")

    try:
        pandoc_exe = pypandoc.get_pandoc_path()
    except Exception:
        pandoc_exe = "pandoc"

    pandoc_cmd = [pandoc_exe, md_path, "-o", temp_epub]
    if os.path.exists(cover_jpg):
        pandoc_cmd += ["--epub-cover-image", cover_jpg]

    pandoc_cmd += ["-M", f"title={title}", "-M", f"author={author}"]

    subprocess.run(
        pandoc_cmd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=os.path.dirname(md_path)
    )

    # 5. HTML Healing
    base_name = _sanitize_name(title)
    epub_final = os.path.join(out_dir, f"{base_name}.epub")
    process_epub_html(temp_epub, epub_final, log_path)

    # 6. Conversions (Robust Calibre — usa arquivo temporário para stdout/stderr em vez de PIPE
    # para evitar que subprocessos órfãos do QtWebEngine/Chromium bloqueiem o fechamento do pipe no Windows)
    calibre_path = CALIBRE_EXE

    for fmt in formats:
        if fmt in ["AZW3", "PDF"]:
            out_file = os.path.join(out_dir, f"{base_name}.{fmt.lower()}")
            log(f"📱 Converting to {fmt}...")
            try:
                with tempfile.TemporaryFile() as out_f, tempfile.TemporaryFile() as err_f:
                    subprocess.run(
                        [calibre_path, epub_final, out_file],
                        check=True,
                        stdin=subprocess.DEVNULL,
                        stdout=out_f,
                        stderr=err_f,
                        timeout=600
                    )
                log(f"✅ Generated: {out_file}")
            except Exception as e:
                log(f"⚠ Conversion error {fmt}: {str(e)}")

    log("🎉 Restoration complete!")
