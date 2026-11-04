"""Adaptation du logiciel à la taille et à la résolution de l'écran.

1. Avant de créer l'application, on regarde l'écran où la fenêtre était (ou l'écran principal) :
   surface utilisable, mise à l'échelle de Windows / du bureau Linux. On en déduit une échelle
   d'interface (QT_SCALE_FACTOR) pour que la face avant tienne entière sans être minuscule :
   moins de 100 % sur un petit écran (1366 × 768, ou 1920 × 1080 à 125-150 %), plus de 100 %
   sur un grand écran (2560 × 1440, 4K à 100 %).
2. Après l'ouverture, la fenêtre est ramenée dans l'écran (taille et position), et suit les
   changements d'écran ou de résolution ; les fenêtres de dialogue trop grandes sont réduites.
3. Si la face avant ne tient toujours pas, elle défile (barres de défilement) au lieu d'être coupée.

La taille minimale réelle de la fenêtre est mesurée à chaque séance et sert au calcul suivant.
"""
import math
import os

from PySide6.QtCore import QEvent, QObject, QRect, QSettings, QTimer

ORG, APP = "F4JCF", "CATPilot"
AUTO = "auto"
CHOICES = [(AUTO, "Automatique (selon l'écran)"), ("0.75", "75 %"), ("0.85", "85 %"), ("1.0", "100 %"),
           ("1.15", "115 %"), ("1.3", "130 %"), ("1.5", "150 %")]
# taille minimale de la fenêtre (pixels logiques, cadre compris) mesurée sur la version 0.27 (polices Linux) ;
# remplacée par la mesure faite sur l'ordinateur dès la première séance
DEFAULT_NATURAL = (1420, 885)
FRAME_W, FRAME_H = 16, 40            # bordures et barre de titre du système
ZOOM_MIN, ZOOM_MAX = 0.75, 1.5
AUTO_MAX = 1.35                      # agrandissement automatique maximal (grands écrans)


def _floor(x, step):
    return math.floor(x / step + 1e-9) * step


def choose_zoom(avail_w, avail_h, nat_w, nat_h):
    """Échelle de l'interface pour une surface utilisable (pixels logiques à l'échelle 1).

    nat_w, nat_h : taille nécessaire à l'échelle 1, cadre de fenêtre compris. Le cadre (barre de
    titre) est dessiné par le système et ne change pas avec l'échelle de l'interface."""
    fit = min((avail_w - FRAME_W) / (nat_w - FRAME_W), (avail_h - FRAME_H) / (nat_h - FRAME_H))
    if fit >= 1.25:                  # grand écran : on agrandit, en laissant de la place aux panneaux
        return round(min(AUTO_MAX, _floor(fit * 0.9, 0.05)), 2)
    if fit >= 1.0:
        return 1.0
    return round(max(ZOOM_MIN, _floor(fit, 0.01)), 2)


def _settings():
    return QSettings(ORG, APP)


def natural_size(s=None):
    s = s or _settings()
    try:
        w, h = (int(x) for x in str(s.value("ui_natural", "")).split("x"))
        if 600 < w < 4000 and 400 < h < 3000:
            return w, h
    except ValueError:
        pass
    return DEFAULT_NATURAL


def _probe_screen(last):
    """Surface utilisable (pixels logiques à l'échelle 1) de l'écran où se trouvait la fenêtre."""
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is not None or not hasattr(QGuiApplication, "shutdown"):
        return None
    app = QGuiApplication(["catpilot-ecran"])
    try:
        screens = app.screens()
        if not screens:
            return None
        scr = app.primaryScreen()
        if "," in last:
            try:
                x, y = (int(v) for v in last.split(","))
                scr = next((c for c in screens if c.geometry().contains(x, y)), scr)
            except ValueError:
                pass
        g = scr.availableGeometry()
        return g.width(), g.height(), scr.name(), scr.devicePixelRatio()
    finally:
        app.shutdown()
        del app


def prepare():
    """À appeler AVANT de créer QApplication. Renvoie l'échelle retenue (et la règle)."""
    os.environ.pop("QT_SCALE_FACTOR", None)        # reste d'un lancement précédent (redémarrage)
    s = _settings()
    choice = str(s.value("ui_zoom", AUTO) or AUTO)
    zoom, info = 1.0, None
    if choice != AUTO:
        try:
            zoom = max(ZOOM_MIN, min(ZOOM_MAX, float(choice)))
        except ValueError:
            zoom = 1.0
    else:
        nw, nh = natural_size(s)
        last = str(s.value("ui_screen_center", ""))
        del s                                        # l'application de test détruit les objets Qt
        try:
            info = _probe_screen(last)
        except Exception:
            info = None
        s = _settings()
        if info:
            zoom = choose_zoom(info[0], info[1], nw, nh)
    s.setValue("ui_zoom_used", zoom)
    s.setValue("ui_screen_info", f"{info[0]}x{info[1]} ({info[2]}, x{info[3]:g})" if info else "")
    s.sync()
    if abs(zoom - 1.0) > 0.001:
        os.environ["QT_SCALE_FACTOR"] = f"{zoom:g}"
    return zoom


def after_app_created():
    """Qt a lu l'échelle : on ne la transmet pas aux programmes lancés ensuite."""
    os.environ.pop("QT_SCALE_FACTOR", None)


def fit_rect(rect, avail):
    """Rectangle ramené dans la surface disponible (taille réduite si besoin, puis déplacé)."""
    w, h = min(rect.width(), avail.width()), min(rect.height(), avail.height())
    x = min(max(rect.x(), avail.x()), avail.right() - w + 1)
    y = min(max(rect.y(), avail.y()), avail.bottom() - h + 1)
    return QRect(x, y, w, h)


class DialogFitter(QObject):
    """Aucune fenêtre (dialogue, panneau détaché) ne dépasse de l'écran à son ouverture."""

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Show and getattr(obj, "isWindow", None) and obj.isWindow() \
                and obj.objectName() != "mainwindow":
            QTimer.singleShot(0, lambda o=obj: self._fit(o))
        return False

    @staticmethod
    def _fit(w):
        try:
            scr = w.screen()
            if scr is None or w.isMaximized() or w.isFullScreen():
                return
            avail = scr.availableGeometry()
            fg = w.frameGeometry()
            extra_w, extra_h = fg.width() - w.width(), fg.height() - w.height()
            if fg.width() <= avail.width() and fg.height() <= avail.height() and avail.contains(fg):
                return
            r = fit_rect(fg, avail)
            w.resize(max(100, r.width() - extra_w), max(80, r.height() - extra_h))
            w.move(r.topLeft())
        except RuntimeError:            # fenêtre déjà détruite
            pass


class WindowFitter(QObject):
    """La fenêtre principale tient dans son écran, et suit les changements d'écran ou de résolution."""

    def __init__(self, win, measure):
        super().__init__(win)
        self.win, self.measure = win, measure
        self._screen = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self.fit)

    def start(self, first_run):
        h = self.win.windowHandle()
        if h is not None:
            h.screenChanged.connect(self._screen_changed)
        self._screen_changed(self.win.screen())
        if first_run:
            self.first_placement()
        else:
            self.fit()
        QTimer.singleShot(1500, self.remember)

    def _screen_changed(self, scr):
        if self._screen is not None:
            try:
                self._screen.availableGeometryChanged.disconnect(self._changed)
            except (RuntimeError, TypeError):
                pass
        self._screen = scr
        if scr is not None:
            scr.availableGeometryChanged.connect(self._changed)
            self._changed()

    def _changed(self, *_a):
        self._timer.start()

    def first_placement(self):
        """Premier lancement : fenêtre à la taille de l'écran (agrandie si l'écran est juste assez grand)."""
        scr = self.win.screen()
        if scr is None:
            return
        avail = scr.availableGeometry()
        need = self.win.minimumSizeHint()
        nat = self.measure()
        if avail.width() < nat[0] * 1.25 or avail.height() < nat[1] * 1.15:
            self.win.showMaximized()
            return
        w = min(avail.width() - FRAME_W, max(need.width(), int(nat[0] * 1.1)))
        h = min(avail.height() - FRAME_H, max(need.height(), int(nat[1] * 1.08)))
        self.win.resize(w, h)
        self.win.move(avail.x() + (avail.width() - w) // 2, avail.y() + max(0, (avail.height() - h - 30) // 2))

    def fit_now(self):
        w = self.win
        if w.isMaximized() or w.isFullScreen():
            w.showNormal()
        scr = w.screen()
        if scr is None:
            return
        avail = scr.availableGeometry()
        nw, nh = self.measure()
        if nw > avail.width() * 0.97 or nh > avail.height() * 0.97:
            w.showMaximized()
            return
        w.resize(nw - FRAME_W, nh - FRAME_H)
        r = fit_rect(w.frameGeometry(), avail)
        w.move(avail.x() + (avail.width() - r.width()) // 2, avail.y() + (avail.height() - r.height()) // 2)

    def fit(self):
        w = self.win
        if w.isMaximized() or w.isFullScreen() or w.isMinimized():
            return
        scr = w.screen()
        if scr is None:
            return
        avail = scr.availableGeometry()
        fg = w.frameGeometry()
        if avail.contains(fg):
            return
        extra_w, extra_h = fg.width() - w.width(), fg.height() - w.height()
        if fg.width() > avail.width() or fg.height() > avail.height():
            if fg.width() >= avail.width() * 0.97 and fg.height() >= avail.height() * 0.97:
                w.showMaximized()
                return
        r = fit_rect(fg, avail)
        w.resize(r.width() - extra_w, r.height() - extra_h)
        w.move(r.topLeft())

    def remember(self):
        """Mesure la taille minimale réelle et l'écran utilisé, pour le prochain lancement."""
        try:
            nw, nh = self.measure()
            s = self.win.settings
            zoom = float(s.value("ui_zoom_used", 1.0) or 1.0)
            # la mesure est en pixels logiques de cette séance ; on la ramène à l'échelle 1
            s.setValue("ui_natural", f"{int(nw)}x{int(nh)}")
            c = self.win.frameGeometry().center()
            s.setValue("ui_screen_center", f"{int(c.x() * zoom)},{int(c.y() * zoom)}")
        except RuntimeError:
            pass
