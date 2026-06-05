# main.py
import tkinter as tk
from ui.main_window import EbookRestorerApp

if __name__ == "__main__":
    root = tk.Tk()
    
    # Aplica um tema nativo elegante dependendo do Sistema Operacional
    style = tk.ttk.Style()
    if "vista" in style.theme_names():
        style.theme_use("vista")
    elif "clam" in style.theme_names():
        style.theme_use("clam")
        
    app = EbookRestorerApp(root)
    root.mainloop()