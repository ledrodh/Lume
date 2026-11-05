import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from core.converter import process_book


class LumeApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Lume")
        self.root.geometry("520x480")
        self.root.resizable(False, False)

        self.pdf_path = tk.StringVar()
        self.title_var = tk.StringVar()
        self.author_var = tk.StringVar()
        self.var_epub = tk.BooleanVar(value=True)
        self.var_azw3 = tk.BooleanVar(value=True)
        self.var_pdf = tk.BooleanVar(value=False)

        self.create_widgets()

    def create_widgets(self):
        padding = {"padx": 15, "pady": 5}

        frame_file = ttk.LabelFrame(self.root, text="Source PDF")
        frame_file.pack(fill="x", padx=15, pady=10)

        ttk.Entry(frame_file, textvariable=self.pdf_path, state="readonly").pack(
            side="left", fill="x", expand=True, **padding
        )
        ttk.Button(frame_file, text="Browse...", command=self.browse_file).pack(
            side="right", **padding
        )

        frame_meta = ttk.LabelFrame(self.root, text="Book Metadata (Optional)")
        frame_meta.pack(fill="x", padx=15, pady=10)

        ttk.Label(frame_meta, text="Book Title:").grid(row=0, column=0, sticky="w", **padding)
        ttk.Entry(frame_meta, textvariable=self.title_var, width=40).grid(row=0, column=1, **padding)

        ttk.Label(frame_meta, text="Author:").grid(row=1, column=0, sticky="w", **padding)
        ttk.Entry(frame_meta, textvariable=self.author_var, width=40).grid(row=1, column=1, **padding)

        frame_format = ttk.LabelFrame(self.root, text="Output Formats")
        frame_format.pack(fill="x", padx=15, pady=10)

        ttk.Checkbutton(frame_format, text="EPUB", variable=self.var_epub).pack(side="left", **padding)
        ttk.Checkbutton(frame_format, text="Kindle (AZW3)", variable=self.var_azw3).pack(side="left", **padding)
        ttk.Checkbutton(frame_format, text="PDF (Text-based)", variable=self.var_pdf).pack(side="left", **padding)

        self.btn_process = ttk.Button(
            self.root, text="START RESTORATION", command=self.start_processing
        )
        self.btn_process.pack(pady=20)

        self.status_label = ttk.Label(self.root, text="Ready.")
        self.status_label.pack()

    def browse_file(self):
        filename = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")])
        if filename:
            self.pdf_path.set(filename)

    def start_processing(self):
        # Capture all Tkinter variable values on the main UI thread for thread safety
        pdf_path = self.pdf_path.get().strip()
        title = self.title_var.get().strip()
        author = self.author_var.get().strip()

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
        self.status_label.config(text="Processing... Check console or wait.")

        thread = threading.Thread(
            target=self.run_core,
            args=(pdf_path, title, author, formats),
            daemon=True,
        )
        thread.start()

    def run_core(self, pdf_path: str, title: str, author: str, formats: list[str]):
        out_dir = os.path.join(os.path.dirname(pdf_path), "Restored_Output")

        try:
            result = process_book(pdf_path, out_dir, title, author, formats)
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
