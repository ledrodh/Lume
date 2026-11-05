import tkinter as tk
from tkinter import ttk
from ui.main_window import LumeApp

if __name__ == "__main__":
    root = tk.Tk()

    # Apply a clean native theme depending on the operating system
    style = ttk.Style()
    if "vista" in style.theme_names():
        style.theme_use("vista")
    elif "clam" in style.theme_names():
        style.theme_use("clam")

    app = LumeApp(root)
    root.mainloop()
