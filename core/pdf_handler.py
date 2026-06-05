import fitz 
 
def extract_cover_and_content(pdf_path, cover_out, content_out, start_page=1, log_path=""): 
    def log(msg): 
        with open(log_path, 'a', encoding='utf-8') as f: f.write(msg + '\n') 
 
    log("🛡️ Extracting Cover and Protecting Content (DNA Preservation Mode)...") 
    doc = fitz.open(pdf_path) 
     
    if doc.page_count < start_page: 
        raise Exception(f"The PDF only has {doc.page_count} pages, cannot start at page {start_page}.") 
         
    cover_page = doc[start_page - 1] 
    w, h = cover_page.rect.width, cover_page.rect.height 
     
    if w > h * 1.05:  
        log(f"-> Wide cover detected. Cropping spine...") 
        cover_page.set_cropbox(fitz.Rect(w * 0.52, 0, w, h)) 
     
    pix = cover_page.get_pixmap(matrix=fitz.Matrix(4, 4)) 
    pix.save(cover_out) 
    log(f"-> Cover saved at: {cover_out}") 
     
    if start_page > 1: 
        pages_to_delete = list(range(start_page - 1)) 
        doc.delete_pages(pages_to_delete) 
         
    doc.save(content_out) 
    doc.close() 
     
    log("-> Content PDF successfully generated (Original structure maintained).")