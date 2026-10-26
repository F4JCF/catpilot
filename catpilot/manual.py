"""Onglet « Mode d'emploi » : le manuel du logiciel, avec sommaire, recherche, impression et PDF.

Le texte est dans assets/manuel/manuel.html (un chapitre par <h2 id="...">), l'historique des
versions dans assets/manuel/nouveautes.txt. Les deux sont livrés avec l'exécutable.
"""
import html
import os
import re
import sys

from PySide6.QtCore import QMarginsF, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QPageLayout, QPageSize, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QDockWidget, QFileDialog, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)

from . import __version__

NEWS_ID = "nouveautes"


def manual_dir():
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(__file__), ".."))
    return os.path.join(base, "assets", "manuel")


def read_news(path=None):
    """Historique des versions : liste de (version, date, titre, lignes), la plus récente en premier."""
    path = path or os.path.join(manual_dir(), "nouveautes.txt")
    out, cur = [], None
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n")
            if line.startswith("#") or not line.strip():
                continue
            if line.startswith("== "):
                parts = [p.strip() for p in line[3:].split("|")] + ["", ""]
                cur = (parts[0], parts[1], parts[2], [])
                out.append(cur)
            elif cur is not None:
                cur[3].append(line)
    return out


def _date_fr(d):
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", d or "")
    return f"{m.group(3)}/{m.group(2)}/{m.group(1)}" if m else d


def news_html(news):
    parts = []
    for ver, date, title, lines in news:
        head = f"Version {html.escape(ver)}"
        if date:
            head += f" — {_date_fr(date)}"
        if title:
            head += f" — {html.escape(title)}"
        parts.append(f'<h3><a name="v{html.escape(ver)}"></a>{head}</h3>')
        items, para = [], []
        for l in lines:
            s = l.strip()
            if s.startswith("- "):
                cls = ' style="margin-left:18px"' if l.startswith("  ") else ""
                items.append(f"<li{cls}>{html.escape(s[2:])}</li>")
            else:
                para.append(f"<p>{html.escape(s)}</p>")
        parts.append("".join(para) + (f"<ul>{''.join(items)}</ul>" if items else ""))
    return "".join(parts)


def build(version=__version__):
    """Renvoie (corps HTML complet, liste des chapitres [(id, titre, html du chapitre)], en-tête)."""
    with open(os.path.join(manual_dir(), "manuel.html"), encoding="utf-8") as f:
        src = f.read()
    src = re.sub(r"<!--.*?-->", "", src, flags=re.S).replace("{VERSION}", version)
    pieces = re.split(r'(?=<h2 id=")', src)
    header, chapters = pieces[0], []
    for p in pieces[1:]:
        m = re.match(r'<h2 id="([^"]+)">(.*?)</h2>', p, re.S)
        cid, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
        body = f'<h2><a name="{cid}"></a>{m.group(2)}</h2>' + p[m.end():]
        chapters.append((cid, title, body))
    n = len(chapters) + 1
    news = read_news()
    chapters.append((NEWS_ID, f"{n}. Nouveautés des versions",
                     f'<h2><a name="{NEWS_ID}"></a>{n}. Nouveautés des versions</h2>'
                     f"<p>Ce qui a changé à chaque version, la plus récente en premier. La version installée est la "
                     f"<b>{html.escape(version)}</b>.</p>" + news_html(news)))
    return header, chapters


def _tables(s):
    return s.replace("<table>", '<table border="1" cellspacing="0" cellpadding="4" width="100%">')


def page_html(header, chapters, dark=False, printing=False, text=None):
    if printing:
        fg, accent, th, note, code = "#000000", "#1a4f8a", "#e4e9f0", "#555555", "#f2f2f2"
    elif dark:
        fg, accent, th, note, code = "#e8e8e8", "#7fb4ff", "#2a3442", "#a8a8a8", "#2b2b2b"
    else:
        fg, accent, th, note, code = "#1b1b1b", "#1a4f8a", "#e4e9f0", "#606060", "#f0f0f0"
    if text and not printing:            # couleur du thème (mode nuit : rouge)
        fg = text
        r, g = int(text[1:3], 16), int(text[3:5], 16)
        if r > 2 * g + 40:               # mode nuit : pas de bleu, tout reste rouge
            accent = note = text
    css = (f"body {{ color:{fg}; }} h1 {{ color:{accent}; }} h2 {{ color:{accent}; margin-top:18px; }}"
           f" h3 {{ margin-top:10px; }} th {{ background-color:{th}; text-align:left; }}"
           f" .note {{ color:{note}; font-style:italic; }} .sous-titre {{ color:{note}; }}"
           f" code {{ background-color:{code}; font-family:monospace; }}"
           f" table {{ border-color:{note}; border-style:solid; }}")
    body = "".join(c[2] for c in chapters)
    return f"<html><head><style>{css}</style></head><body>{_tables(header + body)}</body></html>"


class ManualDock(QDockWidget):
    def __init__(self, win, app_name="CAT Pilot"):
        super().__init__("Mode d'emploi", win if isinstance(win, QWidget) else None)
        self.win, self.app_name = win, app_name
        self.setObjectName("manueldock")
        self.header, self.chapters = "", []
        self._loaded = False
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(4, 4, 4, 4)
        top = QHBoxLayout()
        self.ed_find = QLineEdit()
        self.ed_find.setPlaceholderText("Rechercher dans le mode d'emploi… (Entrée : suivant)")
        self.ed_find.setClearButtonEnabled(True)
        self.ed_find.returnPressed.connect(self.find_next)
        top.addWidget(self.ed_find, 1)
        b = QPushButton("Suivant")
        b.clicked.connect(self.find_next)
        top.addWidget(b)
        top.addSpacing(12)
        for label, tip, slot in (("A−", "Texte plus petit", lambda: self.zoom(-1)),
                                 ("A+", "Texte plus grand", lambda: self.zoom(1))):
            b = QPushButton(label)
            b.setToolTip(tip)
            b.setFixedWidth(40)
            b.clicked.connect(slot)
            top.addWidget(b)
        top.addSpacing(12)
        self.b_print = QPushButton("Imprimer…")
        self.b_print.setToolTip("Imprimer tout le mode d'emploi")
        self.b_print.clicked.connect(lambda: self.print_doc(chapter_only=False))
        self.b_print_ch = QPushButton("Imprimer ce chapitre…")
        self.b_print_ch.setToolTip("Imprimer seulement le chapitre choisi dans le sommaire")
        self.b_print_ch.clicked.connect(lambda: self.print_doc(chapter_only=True))
        self.b_pdf = QPushButton("Enregistrer en PDF…")
        self.b_pdf.setToolTip("Créer un fichier PDF de tout le mode d'emploi")
        self.b_pdf.clicked.connect(self.save_pdf)
        for b in (self.b_print, self.b_print_ch, self.b_pdf):
            top.addWidget(b)
        v.addLayout(top)
        sp = QSplitter(Qt.Horizontal)
        self.toc = QListWidget()
        self.toc.setMinimumWidth(200)
        self.toc.setWordWrap(True)
        self.toc.currentRowChanged.connect(self.goto_row)
        sp.addWidget(self.toc)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.anchorClicked.connect(self._link)
        self.view.verticalScrollBar().valueChanged.connect(lambda _v: self._follow_timer.start())
        sp.addWidget(self.view)
        sp.setStretchFactor(1, 1)
        sp.setSizes([260, 900])
        v.addWidget(sp, 1)
        self.lb = QLabel("")
        self.lb.setObjectName("hint")
        v.addWidget(self.lb)
        self.setWidget(w)
        self._follow_timer = QTimer(self)
        self._follow_timer.setSingleShot(True)
        self._follow_timer.setInterval(120)
        self._follow_timer.timeout.connect(self._follow)
        self._zoom = int(win.settings.value("manual_zoom", 0) or 0)
        self._syncing = False
        self.visibilityChanged.connect(lambda vis: vis and self.load())

    # --- contenu --------------------------------------------------------------------------
    def _dark(self):
        return self.view.palette().base().color().lightness() < 128

    def load(self, force=False):
        if self._loaded and not force:
            return
        try:
            self.header, self.chapters = build()
        except Exception as e:
            self.view.setPlainText(f"Mode d'emploi introuvable : {e}")
            return
        self._loaded = True
        self.view.setHtml(page_html(self.header, self.chapters, dark=self._dark(), text=self.view.palette().text().color().name()))
        if self._zoom:
            self.view.zoomIn(self._zoom)
        self._syncing = True
        self.toc.clear()
        for cid, title, _b in self.chapters:
            it = QListWidgetItem(title)
            it.setData(Qt.UserRole, cid)
            self.toc.addItem(it)
        self.toc.setCurrentRow(0)
        self._syncing = False
        self.lb.setText(f"{self.app_name} {__version__} · {len(self.chapters)} chapitres · "
                        "F1 ouvre ce mode d'emploi à tout moment")

    def changeEvent(self, e):
        super().changeEvent(e)
        if e.type() == e.Type.PaletteChange and self._loaded:     # mode nuit / thème
            pos = self.view.verticalScrollBar().value()
            self.view.setHtml(page_html(self.header, self.chapters, dark=self._dark(), text=self.view.palette().text().color().name()))
            self.view.verticalScrollBar().setValue(pos)

    def goto_row(self, row):
        if self._syncing or row < 0 or row >= len(self.chapters):
            return
        self.goto(self.chapters[row][0])

    def goto(self, anchor):
        self.load()
        self._syncing = True
        self.view.scrollToAnchor(anchor)
        for i, c in enumerate(self.chapters):
            if c[0] == anchor:
                self.toc.setCurrentRow(i)
        self._syncing = False

    def show_news(self):
        """Ouvre le mode d'emploi sur les nouveautés de la version installée."""
        self.load()
        self.show()
        self.raise_()
        QTimer.singleShot(50, lambda: self.goto(f"v{__version__}"))
        QTimer.singleShot(60, lambda: self.toc.setCurrentRow(len(self.chapters) - 1))

    def _anchor_positions(self):
        doc, out = self.view.document(), []
        names = {c[0]: i for i, c in enumerate(self.chapters)}
        block = doc.begin()
        while block.isValid():
            it = block.begin()
            while not it.atEnd():
                frag = it.fragment()
                for n in frag.charFormat().anchorNames():
                    if n in names:
                        out.append((frag.position(), names[n]))
                it += 1
            block = block.next()
        return sorted(out)

    def current_chapter(self):
        row = self.toc.currentRow()
        return row if 0 <= row < len(self.chapters) else 0

    def _follow(self):
        """Le sommaire suit le chapitre affiché en haut de la page."""
        if self._syncing or not self.chapters:
            return
        top = self.view.cursorForPosition(self.view.viewport().rect().topLeft()).position()
        row = 0
        for pos, i in self._anchor_positions():
            if pos <= top + 1:
                row = i
        if row != self.toc.currentRow():
            self._syncing = True
            self.toc.setCurrentRow(row)
            self._syncing = False

    def _link(self, url):
        if url.scheme() in ("http", "https", "mailto"):
            QDesktopServices.openUrl(url)
        elif url.hasFragment():
            self.goto(url.fragment())

    def zoom(self, d):
        self._zoom = max(-4, min(8, self._zoom + d))
        self.view.zoomIn(d)
        self.win.settings.setValue("manual_zoom", self._zoom)

    def find_next(self):
        txt = self.ed_find.text().strip()
        if not txt:
            return
        if not self.view.find(txt):
            c = self.view.textCursor()
            c.movePosition(QTextCursor.Start)
            self.view.setTextCursor(c)
            if not self.view.find(txt):
                self.lb.setText(f"« {txt} » n'apparaît pas dans le mode d'emploi")
                return
        self.lb.setText("")
        self._follow()

    # --- impression -----------------------------------------------------------------------
    def print_document(self, chapter_only=False):
        """Document à imprimer (noir sur blanc), tout le manuel ou un chapitre."""
        self.load()
        chs = [self.chapters[self.current_chapter()]] if chapter_only else self.chapters
        head = self.header if not chapter_only else (
            f"<p class='sous-titre'>{self.app_name} {__version__} — mode d'emploi</p>")
        doc = QTextDocument()
        f = QFont(self.view.font())
        f.setPointSizeF(9.5)
        doc.setDefaultFont(f)
        doc.setHtml(page_html(head, chs, printing=True))
        doc.setDocumentMargin(0)
        return doc

    @staticmethod
    def _printer(pdf_path=None):
        from PySide6.QtPrintSupport import QPrinter
        p = QPrinter(QPrinter.HighResolution)
        p.setPageLayout(QPageLayout(QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(4, 6, 4, 4),
                                    QPageLayout.Millimeter))
        if pdf_path:
            p.setOutputFormat(QPrinter.PdfFormat)
            p.setOutputFileName(pdf_path)
        p.setDocName("Mode d'emploi")
        return p

    def print_doc(self, chapter_only=False):
        try:
            from PySide6.QtPrintSupport import QPrintDialog
        except ImportError as e:
            QMessageBox.warning(self, "Impression", f"Impression indisponible sur cet ordinateur : {e}")
            return
        doc = self.print_document(chapter_only)
        printer = self._printer()
        dlg = QPrintDialog(printer, self)
        title = self.chapters[self.current_chapter()][1] if chapter_only else "tout le mode d'emploi"
        dlg.setWindowTitle(f"Imprimer — {title}")
        if dlg.exec() != QPrintDialog.Accepted:
            return
        doc.print_(printer)
        self.lb.setText(f"Impression envoyée : {title}")

    def save_pdf(self, path=None):
        from .logbook import data_dir
        if not path:
            default = os.path.join(data_dir(), f"Mode d'emploi {self.app_name} {__version__}.pdf")
            path, _ = QFileDialog.getSaveFileName(self, "Enregistrer le mode d'emploi en PDF", default, "PDF (*.pdf)")
            if not path:
                return None
            if not path.lower().endswith(".pdf"):
                path += ".pdf"
        doc = self.print_document(False)
        doc.print_(self._printer(path))
        self.lb.setText(f"PDF enregistré : {path}")
        if not getattr(self, "_quiet", False):
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        return path
