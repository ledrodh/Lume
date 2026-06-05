 ui/main_window.py
import tkinter as tk 
from tkinter import filedialog, messagebox, ttk 
import threading 
import os 
 
from core.converter import process_book 
 
class LumeApp: 
    def __init__(self, root): 
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
        padding = {'padx': 15, 'pady': 5} 
 
        frame_file = ttk.LabelFrame(self.root, text="Source PDF") 
        frame_file.pack(fill="x", padx=15, pady=10) 
         
        ttk.Entry(frame_file, textvariable=self.pdf_path, state="readonly").pack(side="left", fill="x", expand=True, **padding) 
        ttk.Button(frame_file, text="Browse...", command=self.browse_file).pack(side="right", **padding) 
 
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
 
        self.btn_process = ttk.Button(self.root, text="START RESTORATION", command=self.start_processing) 
        self.btn_process.pack(pady=20) 
         
        self.status_label = ttk.Label(self.root, text="Ready.") 
        self.status_label.pack() 
 
    def browse_file(self): 
        filename = filedialog.askopenfilename(filetypes=[("PDF Files", "*.pdf")]) 
        if filename: 
            self.pdf_path.set(filename) 
 
    def start_processing(self): 
        if not self.pdf_path.get(): 
            messagebox.showwarning("Missing Data", "Please select a PDF file.") 
            return 
 
        formats = [] 
        if self.var_epub.get(): formats.append("EPUB") 
        if self.var_azw3.get(): formats.append("AZW3") 
        if self.var_pdf.get(): formats.append("PDF") 
 
        if not formats: 
            messagebox.showwarning("Formats", "Select at least one output format.") 
            return 
 
        self.btn_process.config(state="disabled") 
        self.status_label.config(text="Processing... Check console or wait.") 
         
        thread = threading.Thread(target=self.run_core, args=(formats,)) 
        thread.start() 
 
    def run_core(self, formats): 
        out_dir = os.path.join(os.path.dirname(self.pdf_path.get()), "Restored_Output") 
         
        try: 
            process_book(self.pdf_path.get(), out_dir, self.title_var.get(), self.author_var.get(), formats) 
            self.root.after(0, lambda: self.status_label.config(text="✅ Process Complete! Check the Restored_Output folder.")) 
            self.root.after(0, lambda: messagebox.showinfo("Success", f"Processing finished!\nSaved at:\n{out_dir}")) 
        except Exception as e: 
            error_msg = str(e) 
            self.root.after(0, lambda: self.status_label.config(text="❌ An error occurred.")) 
            self.root.after(0, lambda msg=error_msg: messagebox.showerror("Critical Error", msg)) 
        finally: 
            self.root.after(0, lambda: self.btn_process.config(state="normal"))