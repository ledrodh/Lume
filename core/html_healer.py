import os 
import re 
import tempfile 
import zipfile 
from pathlib import Path 
from bs4 import BeautifulSoup, Tag, NavigableString 
 
def heal_html(soup): 
    """ Applies Kindle-safe CSS and removes ghost hyphenation """ 
    style_tag = soup.new_tag('style', type='text/css') 
    style_tag.string = """ 
    img { max-width: 95%; max-height: 45vh; margin: 1.5em auto; display: block; object-fit: contain; } 
    p { text-align: justify; } 
    .toc-entry { text-align: left; margin: 0.8em 0; overflow: hidden; } 
    .toc-title { font-weight: bold; } 
    .toc-page { float: right; font-weight: bold; } 
    """ 
    if soup.head: soup.head.append(style_tag) 
 
    for node in soup.find_all(string=True): 
        if node.parent.name in ['script', 'style']: continue 
        text = re.sub(r'(\w+)-\s+(\w+)', r'\1\2', str(node).replace('\xa0', ' ').replace('\t', ' ')) 
        if text != str(node): node.replace_with(NavigableString(text)) 
 
def is_toc_table(table: Tag) -> bool: 
    rows = table.find_all('tr') 
    if len(rows) < 4: return False 
    PAGE_REGEX = re.compile(r'(.*?)([IVXLCDMivxlcdmuU]+|\d{1,4})\s*$', re.IGNORECASE) 
    hits = sum(1 for r in rows if r.find_all(['td', 'th']) and PAGE_REGEX.search(r.find_all(['td', 'th'])[-1].get_text(strip=True))) 
    return (hits / len(rows)) >= 0.35 
 
def transform_toc_kindle_safe(table: Tag, soup: BeautifulSoup) -> Tag: 
    """ Replaces tables with <p> with float, the only method Kindle respects 100% """ 
    rows = table.find_all('tr') 
    entries = [] 
    PAGE_REGEX = re.compile(r'^(.*?)(?<!\s)([IVXLCDMivxlcdmuU]+|\d{1,4})\s*$', re.IGNORECASE) 
 
    for row in rows: 
        cells = row.find_all(['td', 'th']) 
        if not cells: continue 
        m = PAGE_REGEX.search(cells[-1].get_text(strip=True)) 
        if m: 
            remainder, page = m.group(1).strip(), m.group(2).replace('l','1').replace('O','0') 
            title = (' '.join(c.get_text(separator=' ', strip=True) for c in cells[:-1]) + " " + remainder).strip() 
            level = 'sub' if re.match(r'^[IVXLCDM]+\.\s', title, re.IGNORECASE) else 'chapter' 
            entries.append({'title': title, 'page': page, 'level': level}) 
 
    nav_div = soup.new_tag('div', attrs={'style': 'margin: 2em 0;'}) 
    for e in entries: 
        p = soup.new_tag('p', attrs={'class': 'toc-entry'}) 
        if e['level'] == 'sub': p['style'] = 'padding-left: 1.5em; font-weight: normal;' 
         
        span_title = soup.new_tag('span', attrs={'class': 'toc-title'}) 
        if e['level'] == 'sub': span_title['style'] = 'font-weight: normal;' 
        span_title.string = e['title'] 
         
        span_page = soup.new_tag('span', attrs={'class': 'toc-page'}) 
        span_page.string = e['page'] 
         
        p.extend([span_title, span_page]) 
        nav_div.append(p) 
    return nav_div 
 
def process_epub_html(epub_in, epub_out, log_path): 
    """ Triple-Pass: Reconstructs the EPUB applying heals to HTML, TOC, and Footnotes """ 
    def log(msg): 
        with open(log_path, 'a', encoding='utf-8') as f: f.write(msg + '\n') 
 
    log("⚙️ Starting Triple-Pass on HTML (TOC and Footnotes)...") 
    with tempfile.TemporaryDirectory() as tmp: 
        with zipfile.ZipFile(epub_in, 'r') as z: z.extractall(tmp) 
         
        xhtmls = sorted(list((Path(tmp) / 'EPUB' / 'text').glob('*.xhtml'))) 
        soups = {x.name: BeautifulSoup(x.read_text(encoding='utf-8'), 'html.parser') for x in xhtmls} 
         
        for s in soups.values(): heal_html(s) 
         
        # --- PHASE 1: Global Memory --- 
        g_notes = {} 
        for fname, s in soups.items(): 
            for p in s.find_all('p'): 
                txt = p.get_text().strip() 
                m = re.match(r'^\[?(\d{1,3})\]?[\.\:\)]\s+(.+)', txt) 
                if m: 
                    g_notes[m.group(1)] = {'text': m.group(2), 'file': fname, 'refs': []} 
                    p.decompose() 
 
        toc_state = {'found': False, 'finished': False} 
        ocr_map = {'l': '1', 'I': '1', 'O': '0', 'º': '0', '°': '0'} 
         
        def heal_ocr_errors(match): 
            base, error = match.group(1), match.group(2) 
            if (base + ocr_map.get(error, '')) in g_notes: return base + ocr_map[error] 
            return match.group(0) 
 
        # --- PHASE 2: Link Hunting and TOC --- 
        for fname, s in soups.items(): 
            for table in s.find_all('table'): 
                if is_toc_table(table) and not toc_state['finished']: 
                    toc_state['found'] = True 
                    table.replace_with(transform_toc_kindle_safe(table, s)) 
                elif toc_state['found']: toc_state['finished'] = True 
 
            for sup in s.find_all('sup'): 
                num = sup.get_text(strip=True) 
                if num in g_notes and not sup.find_parent('a'): 
                    ref_id = f"ref-{num}-{len(g_notes[num]['refs']) + 1}" 
                    g_notes[num]['refs'].append({'file': fname, 'id': ref_id}) 
                    href = f"{g_notes[num]['file']}#fn-{num}" if g_notes[num]['file'] != fname else f"#fn-{num}" 
                    a = s.new_tag('a', attrs={'id': ref_id, 'href': href, 'epub:type': 'noteref', 'style': 'text-decoration: none; color: #d35400; font-weight: bold;'}) 
                    sup.wrap(a) 
 
            regex_note = re.compile(r'([A-Za-zÀ-ÿ\.\,\;\:\-\?\]\)])\s*(\d{1,3})(?![A-Za-z0-9À-ÿº°])') 
            for p in s.find_all('p'): 
                for node in list(p.find_all(string=True)): 
                    if node.parent.name in ['sup', 'a']: continue 
                    text_fixed = re.sub(r'(\d{0,2})([lIOº°])\b', heal_ocr_errors, str(node)) 
                    matches = list(regex_note.finditer(text_fixed)) 
                    if matches: 
                        new_content = [] 
                        last_pos = 0 
                        for m in matches: 
                            prev, num = m.group(1), m.group(2) 
                            if num in g_notes and int(num) < 500: 
                                new_content.append(NavigableString(text_fixed[last_pos:m.start()] + prev)) 
                                ref_id = f"ref-{num}-{len(g_notes[num]['refs']) + 1}" 
                                g_notes[num]['refs'].append({'file': fname, 'id': ref_id}) 
                                href = f"{g_notes[num]['file']}#fn-{num}" if g_notes[num]['file'] != fname else f"#fn-{num}" 
                                a = s.new_tag('a', attrs={'id': ref_id, 'href': href, 'epub:type': 'noteref', 'style': 'text-decoration: none; color: #d35400; font-weight: bold; vertical-align: super; font-size: 0.75em;'}) 
                                a.string = num 
                                new_content.append(a) 
                                last_pos = m.end() 
                        new_content.append(NavigableString(text_fixed[last_pos:])) 
                        parent = node.parent 
                        idx = list(parent.contents).index(node) 
                        node.extract() 
                        for item in reversed(new_content): parent.insert(idx, item) 
                    elif text_fixed != str(node): node.replace_with(NavigableString(text_fixed)) 
 
        # --- PHASE 3: Footnote Reinjection --- 
        for fname, s in soups.items(): 
            file_notes = {k: v for k, v in g_notes.items() if v['file'] == fname} 
            if file_notes: 
                sec = s.new_tag('section', attrs={'epub:type': 'footnotes', 'style': 'margin-top: 3em; border-top: 1px solid #ccc; font-size: 0.9em;'}) 
                ol = s.new_tag('ol', attrs={'style': 'padding-left: 1.5em;'}) 
                for n in sorted(file_notes.keys(), key=int): 
                    li = s.new_tag('li', attrs={'id': f'fn-{n}', 'style': 'margin-bottom: 0.6em;'}) 
                    p_n = s.new_tag('p') 
                    p_n.string = file_notes[n]['text'] + " " 
                    refs = file_notes[n]['refs'] 
                    alphabet = "abcdefghijklmnopqrstuvwxyz" 
                    for i, ref in enumerate(refs): 
                        href_back = f"{ref['file']}#{ref['id']}" if ref['file'] != fname else f"#{ref['id']}" 
                        bk = s.new_tag('a', attrs={'href': href_back, 'style': 'text-decoration: none; color: #3498db; font-weight: bold; margin-right: 5px;'}) 
                        bk.string = f"↩{alphabet[i % 26]}" if len(refs) > 1 else "↩" 
                        p_n.append(bk) 
                    li.append(p_n); ol.append(li) 
                sec.append(ol); s.body.append(sec) 
            (Path(tmp) / 'EPUB' / 'text' / fname).write_text(str(s), encoding='utf-8') 
 
        # --- Final Packaging --- 
        with zipfile.ZipFile(epub_out, 'w', zipfile.ZIP_DEFLATED) as zo: 
            for f in Path(tmp).rglob('*'): 
                if f.is_file(): zo.write(f, str(f.relative_to(tmp))) 
        log("✅ HTML modifications completed and EPUB closed.")