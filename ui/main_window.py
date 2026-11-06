from __future__ import annotations

import os
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from core.converter import process_book
from core.diagnostics import full_diagnostics, quick_diagnostics
from core.models import DocumentDiagnostics


class LumeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Lume — Document Restoration & Validation Platform")
        self.root.geometry("600x650")
        self.root.resizable(False, False)

        self.pdf_path = tk.StringVar()
        self.title_var = tk.StringVar()
        self.author_var = tk.StringVar()
        self.var_epub = tk.BooleanVar(value=True)
        self.var_azw3 = tk.BooleanVar(value=True)
        self.var_pdf = tk.BooleanVar(value=False)

        # Diagnostic state & concurrency guards
        self._diag_request_id: int = 0
        self._last_auto_title: str = ""
        self._last_auto_author: str = ""
        self.current_diagnostics: DocumentDiagnostics | None = None
        self.last_comparison_report: str | None = None

        # Diagnostic UI variables
        self.diag_status_var = tk.StringVar(value="No document selected.")
        self.diag_pages_var = tk.StringVar(value="—")
        self.diag_classes_var = tk.StringVar(value="—")
        self.diag_images_var = tk.StringVar(value="—")
        self.diag_notes_var = tk.StringVar(value="—")
        self.diag_cmap_var = tk.StringVar(value="—")
        self.diag_mode_var = tk.StringVar(value="—")

        self.create_widgets()

    def create_widgets(self):
        padding = {"padx": 12, "pady": 4}

        # 1. Source PDF Selection
        frame_file = ttk.LabelFrame(self.root, text="Source PDF")
        frame_file.pack(fill="x", padx=15, pady=(12, 6))

        ttk.Entry(frame_file, textvariable=self.pdf_path, state="readonly").pack(
            side="left", fill="x", expand=True, **padding
        )
        ttk.Button(frame_file, text="Browse...", command=self.browse_file).pack(
            side="right", **padding
        )

        # 2. Pre-Flight Document Diagnostics Dashboard
        frame_diag = ttk.LabelFrame(self.root, text="Document Pre-Flight Diagnostics")
        frame_diag.pack(fill="x", padx=15, pady=6)

        ttk.Label(
            frame_diag,
            textvariable=self.diag_status_var,
            font=("Segoe UI", 9, "italic"),
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(6, 4))

        diag_rows = [
            ("Pages & Cover:", self.diag_pages_var),
            ("Page Classification:", self.diag_classes_var),
            ("Images (Distinct / Total):", self.diag_images_var),
            ("Footnote Candidates:", self.diag_notes_var),
            ("Font / CMap Health:", self.diag_cmap_var),
            ("Recommended Strategy:", self.diag_mode_var),
        ]
        for idx, (label_text, var) in enumerate(diag_rows, start=1):
            ttk.Label(frame_diag, text=label_text, font=("Segoe UI", 9, "bold")).grid(
                row=idx, column=0, sticky="w", padx=12, pady=2
            )
            ttk.Label(frame_diag, textvariable=var, font=("Segoe UI", 9)).grid(
                row=idx, column=1, sticky="w", padx=8, pady=2
            )

        # 3. Book Metadata
        frame_meta = ttk.LabelFrame(self.root, text="Book Metadata (Optional)")
        frame_meta.pack(fill="x", padx=15, pady=6)

        ttk.Label(frame_meta, text="Book Title:").grid(row=0, column=0, sticky="w", **padding)
        ttk.Entry(frame_meta, textvariable=self.title_var, width=46).grid(row=0, column=1, **padding)

        ttk.Label(frame_meta, text="Author:").grid(row=1, column=0, sticky="w", **padding)
        ttk.Entry(frame_meta, textvariable=self.author_var, width=46).grid(row=1, column=1, **padding)

        # 4. Output Formats
        frame_format = ttk.LabelFrame(self.root, text="Output Formats")
        frame_format.pack(fill="x", padx=15, pady=6)

        ttk.Checkbutton(frame_format, text="EPUB", variable=self.var_epub).pack(side="left", **padding)
        ttk.Checkbutton(frame_format, text="Kindle (AZW3)", variable=self.var_azw3).pack(side="left", **padding)
        ttk.Checkbutton(frame_format, text="PDF (Text-based)", variable=self.var_pdf).pack(side="left", **padding)

        # 5. Actions & Comparison Report Launcher
        frame_actions = ttk.Frame(self.root)
        frame_actions.pack(fill="x", padx=15, pady=14)

        self.btn_process = ttk.Button(
            frame_actions, text="START RESTORATION", command=self.start_processing
        )
        self.btn_process.pack(side="left", expand=True, fill="x", padx=(0, 6))

        self.btn_report = ttk.Button(
            frame_actions,
            text="🔍 View Restoration Report",
            command=self.open_comparison_report,
            state="disabled",
        )
        self.btn_report.pack(side="right", expand=True, fill="x", padx=(6, 0))

        self.status_label = ttk.Label(self.root, text="Ready.")
        self.status_label.pack(pady=(2, 8))

    def browse_file(self):
        filename = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")])
        if filename:
            self.select_pdf(filename)

    def _apply_auto_metadata(self, embedded_title: str, embedded_author: str):
        """
        Populates Title and Author from embedded PDF metadata only when the fields
        are empty or still hold the previous file's auto-filled value. Never overwrites
        values manually entered by the user.
        """
        curr_title = self.title_var.get().strip()
        if not curr_title or curr_title == self._last_auto_title:
            self.title_var.set(embedded_title)
            self._last_auto_title = embedded_title

        curr_author = self.author_var.get().strip()
        if not curr_author or curr_author == self._last_auto_author:
            self.author_var.set(embedded_author)
            self._last_auto_author = embedded_author

    def _render_diagnostics(self, diag: DocumentDiagnostics, req_id: int):
        """Updates the diagnostics panel if req_id matches the active selection."""
        if req_id != self._diag_request_id:
            return

        self.current_diagnostics = diag
        self._apply_auto_metadata(diag.embedded_title, diag.embedded_author)

        phase_label = "Complete inspection finished." if diag.is_complete else "Quick preview ready — running full page scan..."
        self.diag_status_var.set(f"{diag.file_name}: {phase_label}")

        cover_note = "Wide spread candidate (spine crop)" if diag.wide_first_page_candidate else "Standard aspect ratio"
        self.diag_pages_var.set(
            f"{diag.total_pages} pages ({int(diag.first_page_width)}×{int(diag.first_page_height)} pt — {cover_note})"
        )
        self.diag_classes_var.set(
            f"Text: {diag.extractable_text_pages} | Scanned: {diag.image_only_pages} | "
            f"Hybrid: {diag.mixed_pages} | Empty: {diag.empty_or_unknown_pages}"
        )
        self.diag_images_var.set(f"{diag.total_distinct_images} distinct ({diag.total_image_occurrences} total occurrences)")
        self.diag_notes_var.set(
            f"~{diag.estimated_footnote_candidates} heuristic candidates"
            + (" (sampled)" if not diag.is_complete else "")
        )

        if not diag.is_complete:
            self.diag_cmap_var.set("Scanning xref streams...")
        elif diag.cmap_issues_detected > 0:
            self.diag_cmap_var.set(f"{diag.cmap_issues_detected} malformed ToUnicode CMap candidate(s) found")
        else:
            self.diag_cmap_var.set("Clean (0 corrupted CMap streams)")

        mode_str = (
            "Direct Vector Extraction (--disable_ocr)"
            if diag.recommended_ocr_mode == "disable_ocr"
            else "Full Neural Layout & OCR (Marker/Surya)"
        )
        conf_pct = int(round(diag.classification_confidence * 100))
        self.diag_mode_var.set(f"{mode_str} [{conf_pct}% confidence]")

    def select_pdf(self, filename: str):
        """Sets the active PDF file and triggers two-stage non-blocking diagnostics."""
        self._diag_request_id += 1
        req_id = self._diag_request_id
        self.pdf_path.set(filename)
        self.current_diagnostics = None

        try:
            quick_diag = quick_diagnostics(filename)
            self._render_diagnostics(quick_diag, req_id)
        except Exception as exc:
            self.diag_status_var.set(f"Could not inspect PDF: {exc}")
            return

        if not quick_diag.is_complete:
            def _bg_worker():
                try:
                    full_diag = full_diagnostics(
                        filename,
                        cancel_check=lambda: self._diag_request_id != req_id,
                    )
                    if full_diag is not None and self._diag_request_id == req_id:
                        self.root.after(0, lambda d=full_diag, r=req_id: self._render_diagnostics(d, r))
                except Exception:
                    pass

            threading.Thread(target=_bg_worker, daemon=True).start()

    def open_comparison_report(self):
        if self.last_comparison_report and os.path.exists(self.last_comparison_report):
            webbrowser.open(Path(self.last_comparison_report).resolve().as_uri())
        else:
            messagebox.showinfo("Report Unavailable", "No comparison report is available yet.")

    def start_processing(self):
        # Capture all Tkinter variable values on the main UI thread for thread safety
        pdf_path = self.pdf_path.get().strip()
        title = self.title_var.get().strip()
        author = self.author_var.get().strip()
        diag_snapshot = self.current_diagnostics

        if not pdf_path:
            messagebox.showwarning("Missing Data", "Please select a PDF file.")
            return

        formats = []
        if self.var_epub.get():
            formats.append("EPUB")
        if self.var_azw3.get():
            formats.append("AZW3")
        if self.var_pdf.get():
            formats.append("PDF")

        if not formats:
            messagebox.showwarning("Formats", "Select at least one output format.")
            return

        self.btn_process.config(state="disabled")
        self.btn_report.config(state="disabled")
        self.status_label.config(text="Processing... Check console or wait.")

        thread = threading.Thread(
            target=self.run_core,
            args=(pdf_path, title, author, formats, diag_snapshot),
            daemon=True,
        )
        thread.start()

    def run_core(
        self,
        pdf_path: str,
        title: str,
        author: str,
        formats: list[str],
        diag_snapshot: DocumentDiagnostics | None = None,
    ):
        out_dir = os.path.join(os.path.dirname(pdf_path), "Restored_Output")

        try:
            result = process_book(
                pdf_path,
                out_dir,
                title,
                author,
                formats,
                diagnostics=diag_snapshot,
            )
            comp_path = result.get("comparison_html_path") if isinstance(result, dict) else None
            if comp_path and os.path.exists(comp_path):
                self.last_comparison_report = comp_path
                self.root.after(0, lambda: self.btn_report.config(state="normal"))

            failed_formats = result.get("failed_formats", {}) if isinstance(result, dict) else {}
            if failed_formats:
                failed_summary = "\n".join(f"- {fmt}: {err}" for fmt, err in failed_formats.items())
                self.root.after(
                    0,
                    lambda: self.status_label.config(
                        text="⚠️ Completed with format conversion warnings."
                    ),
                )
                self.root.after(
                    0,
                    lambda summary=failed_summary: messagebox.showwarning(
                        "Partial Completion",
                        f"Some requested formats failed to generate:\n{summary}\n\n"
                        f"Available files were saved at:\n{out_dir}",
                    ),
                )
            else:
                self.root.after(
                    0,
                    lambda: self.status_label.config(
                        text="✅ Process Complete! Check the Restored_Output folder."
                    ),
                )
                self.root.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Success", f"Processing finished!\nSaved at:\n{out_dir}"
                    ),
                )
        except Exception as e:
            error_msg = str(e)
            self.root.after(0, lambda: self.status_label.config(text="❌ An error occurred."))
            self.root.after(0, lambda msg=error_msg: messagebox.showerror("Critical Error", msg))
        finally:
            self.root.after(0, lambda: self.btn_process.config(state="normal"))


# Backward-compatible alias
EbookRestorerApp = LumeApp
