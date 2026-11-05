import tempfile
import unittest
import zipfile
from pathlib import Path

import fitz
from bs4 import BeautifulSoup

from core.converter import _sanitize_markdown
from core.html_healer import (
    _extract_footnotes_from_soup,
    _stitch_broken_paragraphs,
    heal_html,
    is_toc_table,
    process_epub_html,
    transform_toc_kindle_safe,
)
from core.pdf_handler import (
    extract_cover_and_content,
    extract_pdf_metadata,
    is_born_digital_pdf,
)


class TestLumePipeline(unittest.TestCase):
    def test_rotated_pdf_cover_extraction_no_cropbox_error(self):
        """
        Regression test for 'ValueError: CropBox not in MediaBox':
        A portrait page (612x792) with /Rotate 90 has visual dimensions 792x612 (w > h * 1.05).
        Verifies that extract_cover_and_content clips the cover cleanly without mutating CropBox.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "rotated.pdf"
            doc = fitz.open()
            page = doc.new_page(width=612, height=792)
            page.insert_text((100, 100), "Rotated Wide Cover Test")
            page.set_rotation(90)
            doc.save(str(pdf_path))
            doc.close()

            cover_out = tmp_path / "cover.jpg"
            content_out = tmp_path / "content.pdf"
            extract_cover_and_content(str(pdf_path), str(cover_out), str(content_out))

            self.assertTrue(cover_out.exists() and cover_out.stat().st_size > 0)
            self.assertTrue(content_out.exists() and content_out.stat().st_size > 0)

    def test_is_born_digital_pdf_and_metadata(self):
        """Verifies detection of native vector text PDFs and embedded metadata extraction."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "digital.pdf"
            doc = fitz.open()
            doc.set_metadata({"title": "The Worker", "author": "Ernst Jünger"})
            page = doc.new_page()
            page.insert_text(
                (50, 50),
                "This is a native digital PDF document containing more than eighty characters of selectable vector text.",
            )
            doc.save(str(pdf_path))
            doc.close()

            self.assertTrue(is_born_digital_pdf(str(pdf_path)))
            meta = extract_pdf_metadata(str(pdf_path))
            self.assertEqual(meta["title"], "The Worker")
            self.assertEqual(meta["author"], "Ernst Jünger")

    def test_sanitize_markdown_sections_and_em_dashes(self):
        """Verifies section heading normalization, missing dot recovery, and Synopsis escaping."""
        raw_md = (
            "1.\nFirst section body.\n\n"
            "52.\nParagraph with corrupted Symbol dash \u23af\uf8e7 and !, here.\n\n"
            "53\nParagraph of section 53 without a period.\n\n"
            "54.\nParagraph of section 54.\n\n"
            "44. Synopsis numbered paragraph that must not become a renumbered list.\n"
        )
        cleaned = _sanitize_markdown(raw_md)
        self.assertIn("### 1.", cleaned)
        self.assertIn("### 52.", cleaned)
        self.assertIn("### 53.", cleaned)
        self.assertIn("### 54.", cleaned)
        self.assertIn("—", cleaned)
        self.assertNotIn("\u23af\uf8e7", cleaned)
        self.assertIn(r"44\. Synopsis numbered paragraph", cleaned)

    def test_html_healer_and_paragraph_stitching(self):
        """Verifies false <sup> removal, ghost hyphenation joining, and cross-page paragraph stitching."""
        raw_html = """
        <html><head></head><body>
          <p>This <sup>is</sup> an example of Nation-State and sci- entific modernity.</p>
          <p>329</p>
          <p>Every single 32</p>
          <p><sup>1</sup> Footnote that originally sat at the bottom of page 32.</p>
          <p>element belongs to the organic construction of the whole.</p>
        </body></html>
        """
        soup = BeautifulSoup(raw_html, "html.parser")
        heal_html(soup)
        g_notes = {}
        _extract_footnotes_from_soup("ch001.xhtml", soup, g_notes)
        _stitch_broken_paragraphs(soup)

        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
        self.assertEqual(len(paragraphs), 2)
        self.assertEqual("This is an example of Nation-State and scientific modernity.", paragraphs[0])
        self.assertEqual("Every single element belongs to the organic construction of the whole.", paragraphs[1])
        self.assertIn("1", g_notes)
        self.assertEqual(g_notes["1"]["text"], "Footnote that originally sat at the bottom of page 32.")

    def test_toc_table_detection_and_transformation(self):
        """Verifies detection and Kindle-safe transformation of Table of Contents HTML tables."""
        toc_html = """
        <html><body>
          <table>
            <tr><td>I. The Third Estate</td><td>15</td></tr>
            <tr><td>II. The Elemental Powers</td><td>42</td></tr>
            <tr><td>III. Work as a Way of Life</td><td>88</td></tr>
            <tr><td>IV. Organic Construction</td><td>134</td></tr>
          </table>
        </body></html>
        """
        soup = BeautifulSoup(toc_html, "html.parser")
        table = soup.find("table")
        self.assertTrue(is_toc_table(table))
        nav_div = transform_toc_kindle_safe(table, soup)
        entries = nav_div.find_all("p", class_="toc-entry")
        self.assertEqual(len(entries), 4)
        self.assertIn("I. The Third Estate", entries[0].get_text())
        self.assertIn("15", entries[0].get_text())

    def test_epub_packaging_and_bidirectional_footnotes(self):
        """
        Verifies end-to-end EPUB healing and W3C EPUB 3.3 OCF compliance:
        - 'mimetype' must be the first file in the ZIP archive and stored with ZIP_STORED.
        - Merged footnotes, glued footnotes ('53Idem'), and inline-tag references ('</em>90,') must link 100%.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            base_epub = tmp_path / "temp.epub"
            final_epub = tmp_path / "final.epub"

            chapter_xhtml = """<?xml version="1.0" encoding="UTF-8"?>
            <html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
            <head><title>Test</title></head>
            <body>
              <p>Text with quotation «important»52 and another at sentence end»53.</p>
              <p>Italic expression <em>sansculottism</em>90, followed by <em>“Imperium”</em> 101. And ellipsis…103,</p>
              <p><sup>52</sup> First note (pp.34-35). 53Idem, p.366. <sup>90</sup> Note on <em>sansculottism</em>.</p>
              <p><sup>101</sup> Note on Kant. <sup>103</sup> Neapolitan proverb.</p>
            </body>
            </html>
            """

            with zipfile.ZipFile(base_epub, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("EPUB/text/ch001.xhtml", chapter_xhtml)
                z.writestr("mimetype", "application/epub+zip")

            process_epub_html(str(base_epub), str(final_epub), "")

            with zipfile.ZipFile(final_epub, "r") as z:
                infolist = z.infolist()
                self.assertEqual(infolist[0].filename, "mimetype")
                self.assertEqual(infolist[0].compress_type, zipfile.ZIP_STORED)
                self.assertEqual(z.read("mimetype"), b"application/epub+zip")

                healed_html = z.read("EPUB/text/ch001.xhtml").decode("utf-8")
                soup = BeautifulSoup(healed_html, "html.parser")

                fn_items = [li["id"] for li in soup.find_all("li", id=True)]
                noterefs = [a.get_text(strip=True) for a in soup.find_all("a", attrs={"epub:type": "noteref"})]

                self.assertEqual(fn_items, ["fn-52", "fn-53", "fn-90", "fn-101", "fn-103"])
                self.assertEqual(noterefs, ["52", "53", "90", "101", "103"])


if __name__ == "__main__":
    unittest.main()
