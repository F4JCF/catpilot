"""Mode compact : petite fenêtre à garder à côté de WSJT-X ou d'un logiciel de log."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)


class CompactWindow(QWidget):
    restore = Signal()

    def __init__(self, win, freq_display_cls, bands, mode_labels):
        super().__init__(None, Qt.Window)
        self.win, self.ctrl = win, win.ctrl
        self.bands, self.mode_labels = bands, mode_labels
        self.setWindowTitle("CAT Pilot")
        self._upd = False
        v = QVBoxLayout(self)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        self.freq = freq_display_cls("cfreq")
        self.freq.tune.connect(win.tune_by)
        v.addWidget(self.freq)
        h = QHBoxLayout()
        self.cb_band = QComboBox()
        self.cb_band.addItem("Bande")
        for name, *_r in bands:
            self.cb_band.addItem(name)
        self.cb_band.activated.connect(lambda i: i > 0 and win.goto_band(self.cb_band.itemText(i)))
        self.cb_mode = QComboBox()
        self.cb_mode.activated.connect(lambda: self.ctrl.set_mode(self.cb_mode.currentData()))
        h.addWidget(self.cb_band)
        h.addWidget(self.cb_mode)
        v.addLayout(h)
        h = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(10)
        self.lb_s = QLabel("")
        self.lb_s.setObjectName("value")
        self.lb_s.setMinimumWidth(70)
        h.addWidget(self.bar, 1)
        h.addWidget(self.lb_s)
        v.addLayout(h)
        h = QHBoxLayout()
        self.b_mox = QPushButton("MOX")
        self.b_mox.setObjectName("ptt")
        self.b_mox.setCheckable(True)
        self.b_mox.toggled.connect(lambda on: None if self._upd else self.ctrl.set_ptt(on))
        self.ck_top = QCheckBox("Au premier plan")
        self.ck_top.toggled.connect(self._on_top)
        b = QPushButton("Fenêtre complète")
        b.clicked.connect(self.restore.emit)
        h.addWidget(self.b_mox, 1)
        v.addLayout(h)
        h = QHBoxLayout()
        h.addWidget(self.ck_top)
        h.addStretch()
        h.addWidget(b)
        v.addLayout(h)
        self.ctrl.state_changed.connect(self.on_state)
        self.resize(360, 170)

    def _on_top(self, on):
        self.setWindowFlag(Qt.WindowStaysOnTopHint, on)
        self.show()

    def fill_modes(self, modes):
        self.cb_mode.clear()
        for m in modes:
            self.cb_mode.addItem(self.mode_labels.get(m, m), m)

    def on_state(self, st):
        if not self.isVisible():
            return
        self._upd = True
        try:
            self.freq.set_freq(st.freq)
            i = self.cb_mode.findData(st.mode)
            if i >= 0 and not self.cb_mode.view().isVisible():
                self.cb_mode.setCurrentIndex(i)
            band = next((n for n, lo, hi, _d in self.bands if lo <= st.freq <= hi), None)
            j = self.cb_band.findText(band) if band else 0
            self.cb_band.setCurrentIndex(max(0, j))
            if st.ptt:
                self.bar.setValue(int(st.po * 1000))
                self.lb_s.setText(f"PO {round(st.po * 100)} %")
            else:
                self.bar.setValue(int(st.smeter * 1000))
                self.lb_s.setText(st.s_text)
            self.b_mox.setChecked(st.ptt)
        finally:
            self._upd = False

    def closeEvent(self, e):
        self.restore.emit()
        e.ignore()
