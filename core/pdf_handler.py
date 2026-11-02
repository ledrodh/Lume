import re
import fitz


def _sanitize_pdf_cmaps(doc, log):
    """
    Corrige streams ToUnicode CMap malformados (ex.: PDFs gerados no Mac OS X Quartz PDFContext
    que mapeiam travessões Symbol como '<21>< 23af f8e7 >' com espaços internos e caracteres PUA,
    fazendo com que o pypdfium2/Marker extraia '!' em vez de '—').
    """
    fixed_count = 0
    for xref in range(1, doc.xref_length()):
        try:
            if not doc.xref_is_stream(xref):
                continue
            raw = doc.xref_stream(xref)
            if not raw or (b"begincmap" not in raw and b"beginbfchar" not in raw):
                continue
            new_raw = re.sub(rb"<\s*23af\s*f8e7\s*>", b"<2014>", raw, flags=re.IGNORECASE)
            new_raw = re.sub(rb"<\s*f8e7\s*>", b"<2014>", new_raw, flags=re.IGNORECASE)
            if new_raw != raw:
                doc.update_stream(xref, new_raw)
                fixed_count += 1
        except Exception:
            continue
    if fixed_count:
        log(f"-> Sanitized {fixed_count} corrupted ToUnicode CMap stream(s) (fixed Symbol em-dashes).")


def is_born_digital_pdf(pdf_path: str) -> bool:
    """
    Detecta se o PDF é nativamente digital (texto vetorial selecionável e sem scans de página inteira).
    Quando verdadeiro, o Marker pode usar --disable_ocr para preservar 100% da camada de texto original
    sem introduzir erros de OCR óptico.
    """
    try:
        doc = fitz.open(pdf_path)
        total = len(doc)
        if total == 0:
            doc.close()
            return False
        step = max(1, total // 25)
        sampled = [doc[i] for i in range(0, total, step)]
        text_pages = 0
        image_pages = 0
        for p in sampled:
            txt = p.get_text("text").strip()
            if len(txt) >= 80 and "\ufffd" not in txt:
                text_pages += 1
            if len(p.get_images()) > 0:
                image_pages += 1
        doc.close()
        n = len(sampled)
        return (text_pages / n) >= 0.80 and (image_pages / n) <= 0.15
    except Exception:
        return False


def extract_cover_and_content(pdf_path, cover_out, content_out, start_page=1, log_path=""):
    def log(msg):
        if log_path:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(msg + '\n')

    log("🛡️ Extracting Cover and Protecting Content (DNA Preservation Mode)...")
    doc = fitz.open(pdf_path)

    if doc.page_count < start_page:
        doc.close()
        raise Exception(f"The PDF only has {doc.page_count} pages, cannot start at page {start_page}.")

    # Renderiza a capa usando 'clip' diretamente no espaço de coordenadas visual (page.rect),
    # evitando cover_page.set_cropbox(), que falha com "CropBox not in MediaBox" em páginas
    # rotacionadas (90°/270°) ou com MediaBox deslocada, além de não alterar o documento original.
    cover_page = doc[start_page - 1]
    r = cover_page.rect
    w, h = r.width, r.height

    clip_rect = None
    if w > h * 1.05:
        log("-> Wide cover detected. Cropping spine...")
        clip_rect = fitz.Rect(r.x0 + w * 0.52, r.y0, r.x1, r.y1)

    pix = cover_page.get_pixmap(matrix=fitz.Matrix(4, 4), clip=clip_rect)
    pix.save(cover_out)
    log(f"-> Cover saved at: {cover_out}")

    if start_page > 1:
        doc.delete_pages(list(range(start_page - 1)))

    _sanitize_pdf_cmaps(doc, log)

    doc.save(content_out)
    doc.close()

    log("-> Content PDF successfully generated (Original structure maintained).")
