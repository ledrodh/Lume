import os
import re
import tempfile
import zipfile
from pathlib import Path
from bs4 import BeautifulSoup, Tag, NavigableString


def heal_html(soup: BeautifulSoup):
    """Applies Kindle-safe CSS, unwraps false superscripts, removes leaked page numbers, and fixes hyphenation."""
    style_tag = soup.new_tag('style', type='text/css')
    style_tag.string = """
    img { max-width: 100%; height: auto; margin: 1.5em auto; display: block; }
    p { text-align: justify; line-height: 1.5; margin: 0.35em 0; }
    h1, h2, h3, h4 { text-align: center; margin: 1.4em 0 0.7em 0; page-break-after: avoid; }
    .toc-entry { text-align: left; margin: 0.8em 0; overflow: hidden; }
    .toc-title { font-weight: bold; }
    .toc-page { float: right; font-weight: bold; }
    """
    if soup.head:
        soup.head.append(style_tag)

    # 1. Remove tags <sup> falsas geradas pelo Marker em palavras/letras comuns (ex.: <sup>é</sup>, <sup>o</sup>, <sup>a</sup>)
    for sup in list(soup.find_all('sup')):
        txt = sup.get_text(strip=True)
        if not txt:
            sup.decompose()
            continue
        # Mantém apenas números de nota (ex: 1, (1), [1]) ou ordinais curtos legítimos
        if not re.match(r'^[\(\[]?\d{1,3}[\)\]]?$', txt) and txt not in ('º', 'ª'):
            prev_sib = sup.previous_sibling
            next_sib = sup.next_sibling
            need_space_before = prev_sib is not None and not str(prev_sib).endswith((' ', '\n', '(', '[', '«', '“', '"'))
            need_space_after = next_sib is not None and not str(next_sib).startswith((' ', '\n', '.', ',', ';', ':', '!', '?', ')', ']', '»', '”', '"'))
            replacement = (f" {txt}" if need_space_before else txt) + (" " if need_space_after else "")
            sup.replace_with(NavigableString(replacement))

    # 2. Remove parágrafos que são apenas números de página isolados vazados do cabeçalho/rodapé (ex.: <p>329</p>)
    for p in list(soup.find_all('p')):
        txt = p.get_text(strip=True)
        if re.match(r'^\d{1,4}$', txt):
            p.decompose()

    # 3. Limpa caracteres PUA da fonte Symbol (⎯\uf8e7 -> —) e hifenizações fantasmas de quebra de linha
    for node in list(soup.find_all(string=True)):
        if node.parent and node.parent.name in ['script', 'style']:
            continue
        orig = str(node)
        text = orig.replace('\xa0', ' ').replace('\t', ' ')
        text = text.replace('\u23af\uf8e7', '—').replace('\uf8e7', '—').replace('\u23af', '—')
        # Só junta palavras hifenizadas quando a segunda parte começa com letra minúscula, preservando "Estado-Nação"
        text = re.sub(r'([A-Za-zÀ-ÿ]{2,})-\s+([a-zà-ÿ]{2,})', r'\1\2', text)
        if text != orig:
            node.replace_with(NavigableString(text))


def is_toc_table(table: Tag) -> bool:
    rows = table.find_all('tr')
    if len(rows) < 4:
        return False
    PAGE_REGEX = re.compile(r'(.*?)([IVXLCDMivxlcdmuU]+|\d{1,4})\s*$', re.IGNORECASE)
    hits = sum(
        1 for r in rows
        if r.find_all(['td', 'th']) and PAGE_REGEX.search(r.find_all(['td', 'th'])[-1].get_text(strip=True))
    )
    return (hits / len(rows)) >= 0.35


def transform_toc_kindle_safe(table: Tag, soup: BeautifulSoup) -> Tag:
    """Replaces tables with <p> with float, the only method Kindle respects 100%."""
    rows = table.find_all('tr')
    entries = []
    PAGE_REGEX = re.compile(r'^(.*?)(?<!\s)([IVXLCDMivxlcdmuU]+|\d{1,4})\s*$', re.IGNORECASE)

    for row in rows:
        cells = row.find_all(['td', 'th'])
        if not cells:
            continue
        m = PAGE_REGEX.search(cells[-1].get_text(strip=True))
        if m:
            remainder, page = m.group(1).strip(), m.group(2).replace('l', '1').replace('O', '0')
            title = (' '.join(c.get_text(separator=' ', strip=True) for c in cells[:-1]) + " " + remainder).strip()
            level = 'sub' if re.match(r'^[IVXLCDM]+\.\s', title, re.IGNORECASE) else 'chapter'
            entries.append({'title': title, 'page': page, 'level': level})

    nav_div = soup.new_tag('div', attrs={'style': 'margin: 2em 0;'})
    for e in entries:
        p = soup.new_tag('p', attrs={'class': 'toc-entry'})
        if e['level'] == 'sub':
            p['style'] = 'padding-left: 1.5em; font-weight: normal;'

        span_title = soup.new_tag('span', attrs={'class': 'toc-title'})
        if e['level'] == 'sub':
            span_title['style'] = 'font-weight: normal;'
        span_title.string = e['title']

        span_page = soup.new_tag('span', attrs={'class': 'toc-page'})
        span_page.string = e['page']

        p.extend([span_title, span_page])
        nav_div.append(p)
    return nav_div


_TERMINAL_PUNCT = ('.', '!', '?', ':', ';', '…', '»', '”', '"', ')', ']')


def _ends_sentence(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    # Remove números de nota colados no fim (ex.: »6 .)
    t = re.sub(r'\s*\d{1,3}\s*\.?$', lambda m: '.' if m.group(0).strip().endswith('.') else '', t).strip()
    return t.endswith(_TERMINAL_PUNCT)


def _clean_fn_html(html_fragment: str) -> tuple[str, str]:
    """Retorna (html_limpo, plain_text_limpo) preservando <em>/<i>/<strong> nas notas de rodapé."""
    frag = BeautifulSoup(html_fragment, 'html.parser')
    plain = re.sub(r'\s+', ' ', frag.get_text()).strip()
    html_str = re.sub(r'\s+', ' ', str(frag)).strip()
    return html_str, plain


def _extract_footnotes_from_soup(fname: str, soup: BeautifulSoup, g_notes: dict):
    """
    Extrai notas de rodapé em múltiplos formatos:
    1) Parágrafos iniciados por <sup>N</sup> (incluindo múltiplas notas <sup>N</sup> no mesmo <p>)
    2) Continuação de nota anterior seguida de <sup>N</sup> no meio do <p> (ex.: "retrospectivamente. <sup>66</sup> ...")
    3) Parágrafos adicionais de uma mesma nota multi-parágrafo quando o corpo principal foi interrompido no meio da frase
    4) Formato clássico sem <sup>: "[1] Texto...", "(1) Texto..."
    """
    paragraphs = list(soup.find_all('p'))
    last_fn_num = None
    body_waiting_continuation = False

    i = 0
    while i < len(paragraphs):
        p = paragraphs[i]
        if not p.parent:
            i += 1
            continue

        raw_html = p.decode_contents().strip()
        plain_txt = p.get_text().strip()

        # Caso 1: O parágrafo começa com <sup>N</sup> (ou <sup>(N)</sup>)
        m_sup_start = re.match(r'^\s*<sup>\s*[\(\[]?(\d{1,3})[\)\]]?\s*</sup>\s*(.+)$', raw_html, flags=re.DOTALL)
        if m_sup_start:
            # Normaliza notas internas coladas sem <sup> (ex.: "). 53Idem, p.366")
            raw_html_norm = re.sub(r'(?<=[\.\)\;]\s)(\d{1,3})(?=[A-ZÀ-Ý])', r'<sup>\1</sup> ', raw_html)
            parts = re.split(r'<sup>\s*[\(\[]?(\d{1,3})[\)\]]?\s*</sup>', raw_html_norm)
            for idx in range(1, len(parts), 2):
                fnum = parts[idx]
                fhtml, ftext = _clean_fn_html(parts[idx + 1])
                if ftext:
                    g_notes[fnum] = {'text': ftext, 'html': fhtml, 'file': fname, 'refs': []}
                    last_fn_num = fnum
            p.decompose()
            i += 1
            continue

        # Caso 2: A nota anterior terminou sem pontuação final e este <p> tem o resto da nota + <sup>N</sup>
        # Ex.: "retrospectivamente. <sup>66</sup> <em>N. do T.</em>: ..."
        if last_fn_num and last_fn_num in g_notes and not _ends_sentence(g_notes[last_fn_num]['text']):
            if re.search(r'<sup>\s*[\(\[]?\d{1,3}[\)\]]?\s*</sup>', raw_html):
                parts = re.split(r'<sup>\s*[\(\[]?(\d{1,3})[\)\]]?\s*</sup>', raw_html)
                prefix_html, prefix_txt = _clean_fn_html(parts[0])
                if prefix_txt:
                    g_notes[last_fn_num]['text'] = (g_notes[last_fn_num]['text'] + ' ' + prefix_txt).strip()
                    g_notes[last_fn_num]['html'] = (g_notes[last_fn_num]['html'] + ' ' + prefix_html).strip()
                for idx in range(1, len(parts), 2):
                    fnum = parts[idx]
                    fhtml, ftext = _clean_fn_html(parts[idx + 1])
                    if ftext:
                        g_notes[fnum] = {'text': ftext, 'html': fhtml, 'file': fname, 'refs': []}
                        last_fn_num = fnum
                p.decompose()
                i += 1
                continue

        # Caso 3: Nota de rodapé multi-parágrafo (ex.: Nota 123 em O Trabalhador)
        if (
            last_fn_num
            and body_waiting_continuation
            and plain_txt
            and plain_txt[0].isupper()
            and i + 1 < len(paragraphs)
        ):
            next_txt = paragraphs[i + 1].get_text().strip()
            if next_txt and next_txt[0].islower():
                extra_html, extra_txt = _clean_fn_html(raw_html)
                g_notes[last_fn_num]['text'] += " " + extra_txt
                g_notes[last_fn_num]['html'] += " " + extra_html
                p.decompose()
                i += 1
                continue

        # Caso 4: Formato clássico sem <sup>: "[1] Texto" ou "(1) Texto"
        m_classic = re.match(r'^[\[\(](\d{1,3})[\]\)]\s+(.+)', plain_txt, flags=re.DOTALL)
        if m_classic:
            fnum = m_classic.group(1)
            ftext = re.sub(r'\s+', ' ', m_classic.group(2)).strip()
            g_notes[fnum] = {'text': ftext, 'html': ftext, 'file': fname, 'refs': []}
            last_fn_num = fnum
            p.decompose()
            i += 1
            continue

        # Se chegamos aqui, é um parágrafo normal do corpo do texto
        last_fn_num = None
        body_waiting_continuation = not _ends_sentence(plain_txt)
        i += 1


def _stitch_broken_paragraphs(soup: BeautifulSoup):
    """
    Reconstitui parágrafos do corpo que foram partidos ao meio por quebras de página
    (e por notas de rodapé que estavam no rodapé da página entre as duas metades).
    Também remove números de página vazados no fim da linha antes da quebra (ex.: 'Cada um e cada 32').
    """
    paragraphs = [p for p in soup.find_all('p') if p.parent and 'toc-entry' not in (p.get('class') or [])]
    i = 0
    while i < len(paragraphs) - 1:
        p1 = paragraphs[i]
        p2 = paragraphs[i + 1]

        # Só junta se p1 e p2 estiverem na mesma seção/pai e forem irmãos consecutivos (sem h1/h2/h3/blockquote entre eles)
        if p1.parent != p2.parent:
            i += 1
            continue
        intervening = False
        sib = p1.next_sibling
        while sib is not None and sib != p2:
            if isinstance(sib, Tag):
                intervening = True
                break
            sib = sib.next_sibling
        if intervening:
            i += 1
            continue

        t1 = p1.get_text().strip()
        t2 = p2.get_text().strip()
        if not t1 or not t2:
            i += 1
            continue

        # Verifica se p1 termina com número de página vazado (ex.: "Cada um e cada 32" + "coisa está na ordem feudal")
        if re.search(r'\s+\d{1,3}$', t1) and t2[0].islower():
            text_nodes = [n for n in p1.find_all(string=True) if str(n).strip()]
            if text_nodes:
                last_node = text_nodes[-1]
                cleaned = re.sub(r'\s+\d{1,3}\s*$', '', str(last_node))
                last_node.replace_with(NavigableString(cleaned))
                t1 = p1.get_text().strip()

        # Condição de costura: p1 não termina frase e p2 começa com letra minúscula (ou p1 termina em artigo/preposição solta)
        p1_incomplete = not _ends_sentence(t1)
        p1_ends_dangling_article = bool(re.search(r'(?:^|\s|\.\s+)([OA]|Os|As|Um|Uma|De|Da|Do|Em|Na|No|Por|Para|Que|Se)$', t1))
        p2_continues = t2[0].islower() or p1_ends_dangling_article

        if p1_incomplete and p2_continues:
            p1.append(NavigableString(" "))
            for child in list(p2.contents):
                p1.append(child.extract())
            p2.decompose()
            paragraphs.pop(i + 1)
        else:
            i += 1


def process_epub_html(epub_in, epub_out, log_path):
    """Triple-Pass: Reconstructs the EPUB applying heals to HTML, Paragraphs, TOC, and Footnotes."""
    def log(msg):
        if log_path:
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(msg + '\n')

    log("⚙️ Starting Triple-Pass on HTML (Paragraphs, TOC, and Footnotes)...")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(epub_in, 'r') as z:
            z.extractall(tmp)

        xhtmls = sorted(list((Path(tmp) / 'EPUB' / 'text').glob('*.xhtml')))
        soups = {x.name: BeautifulSoup(x.read_text(encoding='utf-8'), 'html.parser') for x in xhtmls}

        for s in soups.values():
            heal_html(s)

        # --- PHASE 1: Global Footnote Memory & Paragraph Stitching ---
        g_notes = {}
        for fname, s in soups.items():
            _extract_footnotes_from_soup(fname, s, g_notes)
            _stitch_broken_paragraphs(s)

        toc_state = {'found': False, 'finished': False}
        ocr_map = {'l': '1', 'I': '1', 'O': '0', 'º': '0', '°': '0'}

        def heal_ocr_errors(match):
            base, error = match.group(1), match.group(2)
            if not base:
                start_idx = match.start(2)
                if start_idx > 0 and match.string[start_idx - 1].isalpha():
                    return match.group(0)
            candidate = base + ocr_map.get(error, '')
            if candidate in g_notes:
                return candidate
            return match.group(0)

        # --- PHASE 2: Link Hunting and TOC ---
        # Captura números de nota colados após palavra, reticências (…), fecha-aspas (», ”, ") ou fecha-parênteses,
        # mesmo quando seguidos de ponto final no fim da frase (ex.: «...demais»11. No ano...).
        regex_note = re.compile(
            r'([A-Za-zÀ-ÿ»”"’\'\)\]…])(\s*)(\d{1,3})(?![A-Za-z0-9À-ÿº°])'
        )

        for fname, s in soups.items():
            for table in s.find_all('table'):
                if is_toc_table(table) and not toc_state['finished']:
                    toc_state['found'] = True
                    table.replace_with(transform_toc_kindle_safe(table, s))
                elif toc_state['found']:
                    toc_state['finished'] = True

            for sup in s.find_all('sup'):
                raw_num = sup.get_text(strip=True).strip('()[]')
                if raw_num in g_notes and not sup.find_parent('a'):
                    ref_id = f"ref-{raw_num}-{len(g_notes[raw_num]['refs']) + 1}"
                    g_notes[raw_num]['refs'].append({'file': fname, 'id': ref_id})
                    href = f"{g_notes[raw_num]['file']}#fn-{raw_num}" if g_notes[raw_num]['file'] != fname else f"#fn-{raw_num}"
                    a = s.new_tag('a', attrs={
                        'id': ref_id,
                        'href': href,
                        'epub:type': 'noteref',
                        'style': 'text-decoration: none; color: #d35400; font-weight: bold;'
                    })
                    sup.wrap(a)

            for p in s.find_all('p'):
                for node in list(p.find_all(string=True)):
                    if node.parent.name in ['sup', 'a']:
                        continue
                    text_fixed = re.sub(r'(\d{1,2})([lIOº°])\b', heal_ocr_errors, str(node))

                    # Verifica se o número de nota está no início deste nó logo após uma tag inline (ex.: <em>sansculottism</em>90,)
                    leading_m = None
                    if (
                        node.previous_sibling is not None
                        and getattr(node.previous_sibling, 'name', None) in ('em', 'i', 'strong', 'b', 'span')
                        and node.previous_sibling.get_text()
                        and re.search(r'[A-Za-zÀ-ÿ»”"’\'\)\]…]$', node.previous_sibling.get_text())
                    ):
                        m0 = re.match(r'^(\d{1,3})(?![A-Za-z0-9À-ÿº°])', text_fixed)
                        if m0 and m0.group(1) in g_notes and int(m0.group(1)) < 500:
                            leading_m = m0

                    matches = list(regex_note.finditer(text_fixed))
                    if leading_m or matches:
                        new_content = []
                        last_pos = 0
                        changed = False
                        if leading_m:
                            num = leading_m.group(1)
                            changed = True
                            ref_id = f"ref-{num}-{len(g_notes[num]['refs']) + 1}"
                            g_notes[num]['refs'].append({'file': fname, 'id': ref_id})
                            href = f"{g_notes[num]['file']}#fn-{num}" if g_notes[num]['file'] != fname else f"#fn-{num}"
                            a = s.new_tag('a', attrs={
                                'id': ref_id,
                                'href': href,
                                'epub:type': 'noteref',
                                'style': 'text-decoration: none; color: #d35400; font-weight: bold; vertical-align: super; font-size: 0.75em;'
                            })
                            a.string = num
                            new_content.append(a)
                            last_pos = leading_m.end()

                        for m in matches:
                            if m.start() < last_pos:
                                continue
                            prev, space, num = m.group(1), m.group(2), m.group(3)
                            # Se houver espaço antes do número, só aceita após fecha-aspas/parênteses E se não for item numerado ("6. ")
                            if space:
                                if prev not in ('»', '”', '"', ')', ']', '…'):
                                    continue
                                after = text_fixed[m.end():]
                                if after.startswith('.') and prev not in ('»', '”', '"'):
                                    continue
                            if num in g_notes and int(num) < 500:
                                changed = True
                                new_content.append(NavigableString(text_fixed[last_pos:m.start()] + prev))
                                ref_id = f"ref-{num}-{len(g_notes[num]['refs']) + 1}"
                                g_notes[num]['refs'].append({'file': fname, 'id': ref_id})
                                href = f"{g_notes[num]['file']}#fn-{num}" if g_notes[num]['file'] != fname else f"#fn-{num}"
                                a = s.new_tag('a', attrs={
                                    'id': ref_id,
                                    'href': href,
                                    'epub:type': 'noteref',
                                    'style': 'text-decoration: none; color: #d35400; font-weight: bold; vertical-align: super; font-size: 0.75em;'
                                })
                                a.string = num
                                new_content.append(a)
                                last_pos = m.end()
                        if changed:
                            new_content.append(NavigableString(text_fixed[last_pos:]))
                            parent = node.parent
                            idx = list(parent.contents).index(node)
                            node.extract()
                            for item in reversed(new_content):
                                parent.insert(idx, item)
                        elif text_fixed != str(node):
                            node.replace_with(NavigableString(text_fixed))
                    elif text_fixed != str(node):
                        node.replace_with(NavigableString(text_fixed))

                # Limpa espaços espúrios antes de pontuação após links de nota (ex.: </a> , -> </a>,)
                for a_tag in p.find_all('a', attrs={'epub:type': 'noteref'}):
                    nxt = a_tag.next_sibling
                    if isinstance(nxt, NavigableString):
                        cleaned_nxt = re.sub(r'^\s+([\.,;:\!\?])', r'\1', str(nxt))
                        if cleaned_nxt != str(nxt):
                            nxt.replace_with(NavigableString(cleaned_nxt))

        # --- PHASE 3: Footnote Reinjection ---
        for fname, s in soups.items():
            file_notes = {k: v for k, v in g_notes.items() if v['file'] == fname}
            if file_notes:
                sec = s.new_tag('section', attrs={
                    'epub:type': 'footnotes',
                    'style': 'margin-top: 3em; border-top: 1px solid #ccc; font-size: 0.9em;'
                })
                ol = s.new_tag('ol', attrs={'style': 'padding-left: 1.5em; list-style-type: none;'})
                for n in sorted(file_notes.keys(), key=int):
                    li = s.new_tag('li', attrs={'id': f'fn-{n}', 'style': 'margin-bottom: 0.6em;'})
                    p_n = s.new_tag('p', attrs={'style': 'text-indent: 0;'})
                    b_num = s.new_tag('strong')
                    b_num.string = f"[{n}] "
                    p_n.append(b_num)
                    fn_frag = BeautifulSoup(file_notes[n].get('html', file_notes[n]['text']), 'html.parser')
                    for child in list(fn_frag.contents):
                        p_n.append(child.extract())
                    p_n.append(NavigableString(" "))
                    refs = file_notes[n]['refs']
                    alphabet = "abcdefghijklmnopqrstuvwxyz"
                    for i, ref in enumerate(refs):
                        href_back = f"{ref['file']}#{ref['id']}" if ref['file'] != fname else f"#{ref['id']}"
                        bk = s.new_tag('a', attrs={
                            'href': href_back,
                            'style': 'text-decoration: none; color: #3498db; font-weight: bold; margin-right: 5px;'
                        })
                        bk.string = f"↩{alphabet[i % 26]}" if len(refs) > 1 else "↩"
                        p_n.append(bk)
                    li.append(p_n)
                    ol.append(li)
                sec.append(ol)
                s.body.append(sec)
            (Path(tmp) / 'EPUB' / 'text' / fname).write_text(str(s), encoding='utf-8')

        # --- Final Packaging ---
        with zipfile.ZipFile(epub_out, 'w', zipfile.ZIP_DEFLATED) as zo:
            for f in Path(tmp).rglob('*'):
                if f.is_file():
                    zo.write(f, str(f.relative_to(tmp)))
        log(f"✅ HTML modifications completed ({len(g_notes)} footnotes linked) and EPUB closed.")
