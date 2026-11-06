from __future__ import annotations

import hashlib
import json
import tempfile
import tkinter as tk
import unittest
import zipfile
from pathlib import Path

import fitz
from bs4 import BeautifulSoup

from core.converter import _sanitize_markdown
from core.diagnostics import determine_ocr_strategy, full_diagnostics, quick_diagnostics
from core.epub_validator import validate_epub_structure
from core.html_healer import (
    _extract_footnotes_from_soup,
    _stitch_broken_paragraphs,
    heal_html,
    is_toc_table,
    process_epub_html,
    transform_toc_kindle_safe,
)
from core.models import (
    DocumentDiagnostics,
    HealingStats,
    RestorationReport,
    TransformationEntry,
    TransformationSample,
    ValidationSummary,
)
from core.pdf_handler import (
    extract_cover_and_content,
    extract_pdf_metadata,
    is_born_digital_pdf,
)
from core.reporting import (
    ProvenanceResolver,
    build_restoration_report,
    generate_comparison_report,
)
from ui.main_window import LumeApp


class TestLumePipeline(unittest.TestCase):
    def test_phase0_contracts_and_json_roundtrip(self):
        """Verifies lossless JSON serialization and deserialization of RestorationReport."""
        report = RestorationReport(
            input_metadata={"resolved_title": "The Worker", "resolved_author": "Ernst Jünger"},
            operational_metrics={"paragraphs_stitched": 14},
            structural_metrics={"footnotes_linked_bidirectional": 123},
            transformations=[
                TransformationEntry(
                    operation="cross_page_paragraph_stitching",
                    category="operational",
                    status="success",
                    inspected_count=134,
                    transformed_count=14,
                    skipped_count=120,
                    source_pages=[24, 25],
                )
            ],
            samples=[
                TransformationSample(
                    sample_id="stitch-1",
                    category="paragraph_stitching",
                    source_pages=[24, 25],
                    block_ids=["/page/23/Text/4", "/page/24/Text/1"],
                    original_excerpt="Broken part 1 || Broken part 2",
                    restored_excerpt="Broken part 1 Broken part 2",
                    description="Sample stitch",
                )
            ],
        )
        raw_json = report.to_json()
        restored = RestorationReport.from_json(raw_json)
        self.assertEqual(restored.schema_version, report.schema_version)
        self.assertEqual(restored.run_id, report.run_id)
        self.assertEqual(len(restored.transformations), 1)
        self.assertEqual(restored.transformations[0].source_pages, [24, 25])
        self.assertEqual(len(restored.samples), 1)
        self.assertEqual(restored.samples[0].block_ids, ["/page/23/Text/4", "/page/24/Text/1"])

    def test_phase1_epub_validator_accepts_valid_and_rejects_invalid(self):
        """
        Verifies that validate_epub_structure:
        1) Rejects EPUBs with deflated or misplaced mimetype.
        2) Rejects EPUBs with broken internal fragment anchors (#fn-999) or missing files.
        3) Approves valid W3C EPUB 3.3 OCF archives with valid container.xml, OPF, and links.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)

            # 1. Invalid EPUB: mimetype compressed with ZIP_DEFLATED and broken anchor #fn-999
            bad_epub = tmp_path / "bad.epub"
            with zipfile.ZipFile(bad_epub, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("mimetype", "application/epub+zip", compress_type=zipfile.ZIP_DEFLATED)
                zf.writestr(
                    "EPUB/text/ch001.xhtml",
                    '<?xml version="1.0" encoding="utf-8"?>'
                    '<html xmlns="http://www.w3.org/1999/xhtml"><head><title>Bad</title></head>'
                    '<body><p><a href="#fn-999">Broken Ref</a></p></body></html>',
                )
            bad_summary = validate_epub_structure(bad_epub)
            self.assertFalse(bad_summary.is_valid)
            self.assertFalse(bad_summary.mimetype_ok)
            self.assertEqual(bad_summary.broken_links, 1)
            codes = {i.code for i in bad_summary.issues}
            self.assertIn("PKG-007", codes)
            self.assertIn("RSC-006", codes)

            # 2. Valid OCF EPUB healed by process_epub_html
            raw_epub = tmp_path / "raw.epub"
            good_epub = tmp_path / "good.epub"
            container_xml = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
                '<rootfiles><rootfile full-path="EPUB/content.opf" '
                'media-type="application/oebps-package+xml"/></rootfiles></container>'
            )
            content_opf = (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
                '<manifest><item id="ch1" href="text/ch001.xhtml" media-type="application/xhtml+xml"/></manifest>'
                '<spine><itemref idref="ch1"/></spine></package>'
            )
            chapter_xhtml = """<?xml version="1.0" encoding="UTF-8"?>
            <html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
            <head><title>Valid</title></head>
            <body>
              <p>Text with quotation «important»52 and another at sentence end»53.</p>
              <p>Italic expression <em>sansculottism</em>90, followed by <em>“Imperium”</em> 101. And ellipsis…103,</p>
              <p><sup>52</sup> First note (pp.34-35). 53Idem, p.366. <sup>90</sup> Note on <em>sansculottism</em>.</p>
              <p><sup>101</sup> Note on Kant. <sup>103</sup> Neapolitan proverb.</p>
            </body>
            </html>
            """
            with zipfile.ZipFile(raw_epub, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr("META-INF/container.xml", container_xml)
                zf.writestr("EPUB/content.opf", content_opf)
                zf.writestr("EPUB/text/ch001.xhtml", chapter_xhtml)
                zf.writestr("mimetype", "application/epub+zip")

            stats = process_epub_html(str(raw_epub), str(good_epub), "")
            self.assertEqual(stats.footnotes_extracted, 5)
            self.assertEqual(stats.footnotes_linked, 5)

            good_summary = validate_epub_structure(good_epub)
            self.assertTrue(good_summary.is_valid, f"Unexpected issues: {good_summary.issues}")
            self.assertTrue(good_summary.mimetype_ok)
            self.assertTrue(good_summary.container_xml_ok)
            self.assertTrue(good_summary.opf_manifest_ok)
            self.assertTrue(good_summary.xhtml_well_formed_ok)
            self.assertEqual(good_summary.broken_links, 0)
            self.assertEqual(good_summary.checked_links, 10)  # 5 forward noterefs + 5 backlinks

    def test_phase2_diagnostics_classifications_and_readonly_guarantee(self):
        """
        Verifies 4-state page classification (extractable_text, image_only, mixed, empty_or_unknown),
        distinct vs. repeated image counting, and strict read-only file integrity.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "multi_type.pdf"

            # Create a small sample PNG image in memory using fitz Pixmap
            pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 200, 200), False)
            pix.clear_with(200)
            img_bytes = pix.tobytes("png")

            doc = fitz.open()
            doc.set_metadata({"title": "Diagnostic Test Book", "author": "Test Author"})

            # Page 1: Extractable text only + footnote at bottom
            p1 = doc.new_page(width=600, height=800)
            p1.insert_text(
                (50, 100),
                "This page contains selectable digital vector text exceeding forty characters easily.",
            )
            p1.insert_text((50, 720), "1 First footnote candidate at the bottom of page one.")

            # Page 2: Image-only (scan simulation)
            p2 = doc.new_page(width=600, height=800)
            p2.insert_image(fitz.Rect(20, 20, 580, 780), stream=img_bytes)

            # Page 3: Mixed / Hybrid (selectable text + large embedded figure)
            p3 = doc.new_page(width=600, height=800)
            p3.insert_text(
                (50, 80),
                "This hybrid academic page contains both selectable vector text and a large figure.",
            )
            p3.insert_image(fitz.Rect(50, 150, 550, 550), stream=img_bytes)

            # Page 4: Empty page
            doc.new_page(width=600, height=800)

            doc.save(str(pdf_path))
            doc.close()

            sha_before = hashlib.sha256(pdf_path.read_bytes()).hexdigest()

            q_diag = quick_diagnostics(pdf_path)
            f_diag = full_diagnostics(pdf_path)

            sha_after = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
            self.assertEqual(sha_before, sha_after, "Diagnostics must never mutate the PDF file.")

            self.assertIsNotNone(f_diag)
            self.assertEqual(f_diag.total_pages, 4)
            self.assertEqual(f_diag.extractable_text_pages, 1)
            self.assertEqual(f_diag.image_only_pages, 1)
            self.assertEqual(f_diag.mixed_pages, 1)
            self.assertEqual(f_diag.empty_or_unknown_pages, 1)
            self.assertGreaterEqual(f_diag.estimated_footnote_candidates, 1)
            self.assertEqual(q_diag.embedded_title, "Diagnostic Test Book")
            self.assertFalse(is_born_digital_pdf(str(pdf_path)))
            meta = extract_pdf_metadata(str(pdf_path))
            self.assertEqual(meta["title"], "Diagnostic Test Book")

            toc_soup = BeautifulSoup(
                "<table><tr><td>I. Intro</td><td>1</td></tr><tr><td>II. Part 1</td><td>10</td></tr>"
                "<tr><td>III. Part 2</td><td>20</td></tr><tr><td>IV. End</td><td>30</td></tr></table>",
                "html.parser",
            )
            toc_table = toc_soup.find("table")
            self.assertTrue(is_toc_table(toc_table))
            self.assertEqual(len(transform_toc_kindle_safe(toc_table, toc_soup).find_all("p")), 4)

    def test_phase3_ui_concurrency_and_manual_metadata_protection(self):
        """
        Verifies that LumeApp:
        1) Never overwrites Title/Author manually entered by the user when loading a PDF.
        2) Updates auto-filled Title/Author when switching files if the user did not edit them.
        3) Ignores stale background diagnostic callbacks from previous file selections.
        """
        try:
            root = tk.Tk()
            root.withdraw()
        except tk.TclError:
            self.skipTest("Tkinter display unavailable in headless environment")
            return

        try:
            app = LumeApp(root)

            # Simulate file 1 auto-filling metadata
            app._diag_request_id = 1
            diag1 = DocumentDiagnostics(
                file_path="/tmp/book1.pdf",
                file_name="book1.pdf",
                total_pages=100,
                embedded_title="Auto Title 1",
                embedded_author="Auto Author 1",
                is_complete=True,
            )
            app._render_diagnostics(diag1, req_id=1)
            self.assertEqual(app.title_var.get(), "Auto Title 1")
            self.assertEqual(app.author_var.get(), "Auto Author 1")

            # Simulate user manually overriding the Title, but leaving Author untouched
            app.title_var.set("User Custom Title")

            # Simulate switching to file 2 (request_id = 2)
            app._diag_request_id = 2
            diag2 = DocumentDiagnostics(
                file_path="/tmp/book2.pdf",
                file_name="book2.pdf",
                total_pages=250,
                embedded_title="Auto Title 2",
                embedded_author="Auto Author 2",
                is_complete=True,
            )
            app._render_diagnostics(diag2, req_id=2)
            # Manual title must be preserved; auto-author must update to file 2
            self.assertEqual(app.title_var.get(), "User Custom Title")
            self.assertEqual(app.author_var.get(), "Auto Author 2")

            # Simulate stale callback arriving late from file 1 (req_id = 1)
            app._render_diagnostics(diag1, req_id=1)
            self.assertEqual(app.current_diagnostics.file_name, "book2.pdf")
            self.assertIn("250 pages", app.diag_pages_var.get())
        finally:
            root.destroy()

    def test_phase4_and_5_provenance_and_xss_safe_comparator_html(self):
        """
        Verifies that ProvenanceResolver links samples to their source PDF pages & Marker block IDs,
        and that generate_comparison_report escapes untrusted script tags.
        """
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pdf_path = tmp_path / "prov.pdf"
            blocks_json = tmp_path / "provenance_blocks.json"

            doc = fitz.open()
            p1 = doc.new_page()
            p1.insert_text((50, 100), "Every single element belongs to the organic construction.")
            doc.save(str(pdf_path))
            doc.close()

            blocks_json.write_text(
                json.dumps(
                    [
                        {
                            "page_number": 1,
                            "block_id": "/page/0/Text/3",
                            "block_type": "Text",
                            "text": "Every single element belongs to the organic construction.",
                        }
                    ]
                ),
                encoding="utf-8",
            )

            resolver = ProvenanceResolver(pdf_path, blocks_json)
            pages, block_ids, match_method, ambiguous = resolver.resolve(
                "Every single element belongs to the organic construction."
            )
            self.assertEqual(pages, [1])
            self.assertEqual(block_ids, ["/page/0/Text/3"])
            self.assertEqual(match_method, "marker_block_id")
            self.assertFalse(ambiguous)

            # Verify XSS escaping in comparison report
            diag = quick_diagnostics(pdf_path)
            healing = HealingStats(
                paragraphs_inspected=10,
                paragraphs_stitched=1,
                samples=[
                    TransformationSample(
                        sample_id="xss-test",
                        category="paragraph_stitching",
                        source_pages=[1],
                        block_ids=["/page/0/Text/3"],
                        original_excerpt="<script>alert('xss_before')</script>",
                        restored_excerpt="<img src=x onerror=alert('xss_after')>",
                        description="Test XSS escaping",
                    )
                ],
            )
            report = build_restoration_report(
                pdf_path=str(pdf_path),
                title="<script>alert('title')</script>",
                author="Ernst Jünger",
                compute_device="cpu",
                diagnostics=diag,
                extraction_stats={"cmap_issues_repaired": 1, "wide_cover_cropped": False},
                healing_stats=healing,
                validation=ValidationSummary(is_valid=True, checked_files=5, checked_links=8),
                export_results={"generated_files": ["book.epub"], "failed_formats": {}},
            )
            html_out = Path(generate_comparison_report(report, pdf_path, tmp_path))
            self.assertTrue(html_out.exists())
            html_content = html_out.read_text(encoding="utf-8")

            self.assertNotIn("<script>alert", html_content)
            self.assertNotIn("<img src=x onerror", html_content)
            self.assertIn("&lt;script&gt;alert", html_content)
            self.assertTrue((tmp_path / "comparison_assets" / "page_001.jpg").exists())

    def test_rotated_pdf_cover_extraction_no_cropbox_error(self):
        """
        Regression test for 'ValueError: CropBox not in MediaBox':
        A portrait page (612x792) with /Rotate 90 has visual dimensions 792x612 (w > h * 1.05).
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
            stats = extract_cover_and_content(str(pdf_path), str(cover_out), str(content_out))

            self.assertTrue(cover_out.exists() and cover_out.stat().st_size > 0)
            self.assertTrue(content_out.exists() and content_out.stat().st_size > 0)
            self.assertTrue(stats["wide_cover_cropped"])

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
        stats = HealingStats()
        heal_html(soup, stats)
        g_notes = {}
        _extract_footnotes_from_soup("ch001.xhtml", soup, g_notes, stats)
        _stitch_broken_paragraphs(soup, stats)

        paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
        self.assertEqual(len(paragraphs), 2)
        self.assertEqual("This is an example of Nation-State and scientific modernity.", paragraphs[0])
        self.assertEqual("Every single element belongs to the organic construction of the whole.", paragraphs[1])
        self.assertEqual(stats.false_sups_unwrapped, 1)
        self.assertEqual(stats.leaked_pages_removed, 2)
        self.assertEqual(stats.paragraphs_stitched, 1)

    def test_edge_cases_short_pdf_cmap_hybrid_ocr_ambiguity_and_privacy(self):
        """
        Covers architectural review edge cases:
        1) Short PDF (<= 12 pages) keeps cmap_scan_completed=False in quick_diagnostics and completes in full_diagnostics.
        2) Hybrid document (80% extractable_text + 20% mixed) recommends 'full_ocr' instead of 'disable_ocr'.
        3) ProvenanceResolver detects repeated text across multiple pages (ambiguous=True) and falls back cleanly on bad JSON.
        4) build_restoration_report omits absolute local file paths by default for privacy.
        """
        # 1) Hybrid 80/20 OCR strategy test
        mode_hybrid, conf_hybrid = determine_ocr_strategy(ext_cnt=8, img_cnt=0, mix_cnt=2)
        self.assertEqual(mode_hybrid, "full_ocr")
        self.assertGreater(conf_hybrid, 0.5)

        mode_digital, conf_digital = determine_ocr_strategy(ext_cnt=9, img_cnt=0, mix_cnt=1)
        self.assertEqual(mode_digital, "disable_ocr")
        self.assertAlmostEqual(conf_digital, 0.97)

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            short_pdf = tmp_path / "short_repeated.pdf"

            doc = fitz.open()
            for page_idx in range(3):
                pg = doc.new_page(width=600, height=800)
                pg.insert_text(
                    (50, 100),
                    "Recurring philosophical refrain that appears identically across multiple pages of the treatise.",
                )
                pg.insert_text((50, 200), f"Unique paragraph on page {page_idx + 1} with sufficient length.")
            doc.save(str(short_pdf))
            doc.close()

            # 2) Short PDF (3 pages <= 12): quick_diagnostics must NOT mark cmap_scan_completed or is_complete
            q_diag = quick_diagnostics(short_pdf)
            self.assertFalse(q_diag.cmap_scan_completed)
            self.assertFalse(q_diag.is_complete)

            f_diag = full_diagnostics(short_pdf)
            self.assertIsNotNone(f_diag)
            self.assertTrue(f_diag.cmap_scan_completed)
            self.assertTrue(f_diag.is_complete)

            # 3) Corrupted blocks JSON fallback + repeated text ambiguity detection
            bad_json = tmp_path / "corrupted_blocks.json"
            bad_json.write_text("{not valid json", encoding="utf-8")
            resolver = ProvenanceResolver(short_pdf, bad_json)

            pages_rep, blk_rep, method_rep, ambig_rep = resolver.resolve(
                "Recurring philosophical refrain that appears identically across multiple pages of the treatise."
            )
            self.assertEqual(pages_rep, [1, 2, 3])
            self.assertEqual(blk_rep, [])
            self.assertEqual(method_rep, "page_text_match")
            self.assertTrue(ambig_rep)

            pages_uniq, _, method_uniq, ambig_uniq = resolver.resolve(
                "Unique paragraph on page 2 with sufficient length."
            )
            self.assertEqual(pages_uniq, [2])
            self.assertEqual(method_uniq, "page_text_match")
            self.assertFalse(ambig_uniq)

            # 4) Privacy by default in build_restoration_report
            report = build_restoration_report(
                pdf_path=str(short_pdf),
                title="Privacy Test",
                author="Author",
                compute_device="cpu",
                diagnostics=f_diag,
                extraction_stats={},
                healing_stats=HealingStats(paragraphs_inspected=5, paragraphs_stitched=1),
                validation=ValidationSummary(is_valid=True),
                export_results={},
            )
            report_dict = json.loads(report.to_json())
            self.assertEqual(report_dict["input_metadata"].get("source_file"), "short_repeated.pdf")
            self.assertNotIn("source_pdf", report_dict["input_metadata"])
            self.assertNotIn("file_path", report_dict["diagnostics"])


if __name__ == "__main__":
    unittest.main()
