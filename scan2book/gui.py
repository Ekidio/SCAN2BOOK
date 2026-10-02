"""Asztali felület (Tkinter): fotózott PDF → könyvszerűen szedett PDF."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
import webbrowser
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import pymupdf

from .pipeline import Options, convert, parse_page_range

SOURCE_URL = "https://github.com/Ekidio/SCAN2BOOK"
FONTS = {"Libertinus Serif": "LibertinusSerif", "EB Garamond": "EBGaramond"}


def open_file(path: str) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
    elif os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", path])


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SCAN2BOOK – From bad scans to beautiful books")
        self.minsize(640, 420)
        self.q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None

        self.in_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self.lang_var = tk.StringVar(value="hun")
        self.pages_var = tk.StringVar()
        self.font_var = tk.StringVar(value="Libertinus Serif")
        self.size_var = tk.DoubleVar(value=11.0)
        self.dewarp_var = tk.BooleanVar(value=True)
        self.italic_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Válaszd ki a lefotózott könyvoldalakat tartalmazó PDF-et.")
        self._build()
        self.after(100, self._poll)

    # --- felület -------------------------------------------------------------------
    def _build(self):
        pad = {"padx": 10, "pady": 5}
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)

        ttk.Label(root, text="Fotózott könyv → szedett PDF", font=("Helvetica", 17, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        ttk.Label(root, text="Bemenet (PDF):").grid(row=1, column=0, sticky="w", **pad)
        ttk.Entry(root, textvariable=self.in_var).grid(row=1, column=1, sticky="ew", **pad)
        ttk.Button(root, text="Tallózás…", command=self._pick_in).grid(row=1, column=2, **pad)

        ttk.Label(root, text="Kimenet (PDF):").grid(row=2, column=0, sticky="w", **pad)
        ttk.Entry(root, textvariable=self.out_var).grid(row=2, column=1, sticky="ew", **pad)
        ttk.Button(root, text="Mentés ide…", command=self._pick_out).grid(row=2, column=2, **pad)

        opts = ttk.LabelFrame(root, text="Beállítások", padding=10)
        opts.grid(row=3, column=0, columnspan=3, sticky="ew", pady=10)
        for c in range(4):
            opts.columnconfigure(c, weight=1)

        ttk.Label(opts, text="OCR nyelv:").grid(row=0, column=0, sticky="w")
        ttk.Combobox(opts, textvariable=self.lang_var, width=12,
                     values=["hun", "hun+eng", "eng"]).grid(row=0, column=1, sticky="w")
        ttk.Label(opts, text="Oldalak (pl. 1-10,15):").grid(row=0, column=2, sticky="w")
        ttk.Entry(opts, textvariable=self.pages_var, width=14).grid(row=0, column=3, sticky="w")

        ttk.Label(opts, text="Betűtípus:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(opts, textvariable=self.font_var, state="readonly", width=16,
                     values=list(FONTS)).grid(row=1, column=1, sticky="w", pady=(8, 0))
        ttk.Label(opts, text="Betűméret (pt):").grid(row=1, column=2, sticky="w", pady=(8, 0))
        ttk.Spinbox(opts, from_=8, to=16, increment=0.5, textvariable=self.size_var, width=6).grid(
            row=1, column=3, sticky="w", pady=(8, 0))

        ttk.Checkbutton(opts, text="Lapgörbület kiegyenesítése", variable=self.dewarp_var).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))
        ttk.Checkbutton(opts, text="Dőlt betűk felismerése", variable=self.italic_var).grid(
            row=2, column=2, columnspan=2, sticky="w", pady=(8, 0))

        self.progress = ttk.Progressbar(root, mode="determinate", maximum=1.0)
        self.progress.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(6, 4))
        ttk.Label(root, textvariable=self.status_var, wraplength=580).grid(
            row=5, column=0, columnspan=3, sticky="w")

        # AGPL: a forráskód elérhetősége a felhasználó számára
        foot = ttk.Frame(root)
        foot.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        src = ttk.Label(foot, text="Nyílt forrás (AGPL-3.0) · github.com/Ekidio/SCAN2BOOK",
                        foreground="#8a7a66", cursor="hand2")
        src.pack(side="left", anchor="s")
        src.bind("<Button-1>", lambda e: webbrowser.open(SOURCE_URL))

        btns = ttk.Frame(foot)
        btns.pack(side="right")
        self.open_btn = ttk.Button(btns, text="Eredmény megnyitása", state="disabled",
                                   command=lambda: open_file(self.out_var.get()))
        self.open_btn.pack(side="left", padx=6)
        self.run_btn = ttk.Button(btns, text="Átalakítás indítása", command=self._start)
        self.run_btn.pack(side="left")

    def _pick_in(self):
        p = filedialog.askopenfilename(title="Fotózott PDF kiválasztása", filetypes=[("PDF", "*.pdf")])
        if p:
            self.in_var.set(p)
            if not self.out_var.get():
                self.out_var.set(str(Path(p).with_name(Path(p).stem + "_konyv.pdf")))
            try:
                with pymupdf.open(p) as d:
                    self.status_var.set(f"{d.page_count} oldal. Indítható az átalakítás.")
            except Exception as e:
                self.status_var.set(f"Nem olvasható PDF: {e}")

    def _pick_out(self):
        init = self.out_var.get() or self.in_var.get()
        p = filedialog.asksaveasfilename(
            title="Kimeneti PDF", defaultextension=".pdf", filetypes=[("PDF", "*.pdf")],
            initialdir=str(Path(init).parent) if init else None,
            initialfile=Path(init).name if init else "konyv.pdf")
        if p:
            self.out_var.set(p)

    # --- futtatás ------------------------------------------------------------------
    def _start(self):
        src, dst = self.in_var.get().strip(), self.out_var.get().strip()
        if not src or not Path(src).exists():
            messagebox.showwarning("SCAN2BOOK", "Válassz ki egy létező bemeneti PDF-et.")
            return
        if not dst:
            dst = str(Path(src).with_name(Path(src).stem + "_konyv.pdf"))
            self.out_var.set(dst)
        if Path(dst).resolve() == Path(src).resolve():
            messagebox.showwarning("SCAN2BOOK", "A kimenet nem lehet azonos a bemenettel.")
            return
        try:
            with pymupdf.open(src) as d:
                pages = parse_page_range(self.pages_var.get(), d.page_count)
            opts = Options(lang=self.lang_var.get().strip() or "hun", italics=self.italic_var.get(),
                           font_size=float(self.size_var.get()), pages=pages,
                           dewarp=self.dewarp_var.get(), font=FONTS[self.font_var.get()])
        except Exception as e:
            messagebox.showerror("SCAN2BOOK", f"Hibás beállítás: {e}")
            return
        self.run_btn.configure(state="disabled")
        self.open_btn.configure(state="disabled")
        self.progress["value"] = 0

        def job():
            try:
                convert(src, dst, opts, lambda f, m: self.q.put(("prog", f, m)))
                self.q.put(("done", dst))
            except Exception as e:
                traceback.print_exc()
                self.q.put(("error", str(e)))

        self.worker = threading.Thread(target=job, daemon=True)
        self.worker.start()

    def _poll(self):
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "prog":
                    self.progress["value"] = msg[1]
                    self.status_var.set(msg[2])
                elif msg[0] == "done":
                    self.run_btn.configure(state="normal")
                    self.open_btn.configure(state="normal")
                    self.status_var.set(f"Kész! Mentve: {msg[1]}")
                elif msg[0] == "error":
                    self.run_btn.configure(state="normal")
                    self.status_var.set("Hiba történt.")
                    messagebox.showerror("SCAN2BOOK", msg[1])
        except queue.Empty:
            pass
        self.after(100, self._poll)


def main():
    App().mainloop()


if __name__ == "__main__":
    main()
