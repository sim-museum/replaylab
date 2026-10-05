"""replaylab viewer: 3D flight paths, a timeline, and channel plots on one linked cursor.

Without a comparison every loaded track plays on the recordings' own clock. With a reference (gold) and a
comparison track chosen, the plots switch to the aligned axis (time or distance from an event, or the same place
along the reference path), the clock follows the reference flight, and the comparison aircraft is drawn at the
moment the alignment pairs with it -- so the two aircraft in the 3D view are always the two being compared.
"""
import math
import os
import sys

import numpy as np
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QAction, QColor
from PyQt6.QtWidgets import (QApplication, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QGroupBox,
                             QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow, QPushButton,
                             QSlider, QSplitter, QVBoxLayout, QWidget)

from . import acmi
from .align import compare
from .cli import UNITS
from .track import Track

GOLD, BLUE = "#c9a227", "#2f7de1"
PALETTE = [GOLD, BLUE, "#d04040", "#3aa655", "#9b4dca", "#e07b28", "#1aa3a3", "#c2559c"]
RUNWAY_ROWS = ["hat", "gp_dev", "rwy_xtrack"]
PLOT_CHANNELS = RUNWAY_ROWS + ["alt", "gs", "vs", "g", "IAS", "roll", "pitch", "course", "fpa", "turn", "AOA", "AGL", "Throttle"]
DEFAULT_ON = {"alt", "gs", "vs", "g"}
SPEEDS = [0.25, 0.5, 1, 2, 4, 8, 16]


def rgba(hexcol, a=1.0):
    c = QColor(hexcol)
    return (c.redF(), c.greenF(), c.blueF(), a)


class Viewer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("replaylab")
        self.tracks = []                 # (Track, colour)
        self.cmp = None                  # Comparison or None
        self.clock = 0.0                 # recording time, or reference time when comparing
        self.origin = None               # scene origin (x, y, z floor) in metres
        self.playing = False
        self._cursor_guard = False
        self._build()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(33)

    # ---------------- layout ----------------
    def _build(self):
        left = QWidget()
        lv = QVBoxLayout(left)
        openb = QPushButton("Open recordings…")
        openb.clicked.connect(self.open_dialog)
        lv.addWidget(openb)
        lv.addWidget(QLabel("Tracks"))
        self.track_list = QListWidget()
        self.track_list.itemChanged.connect(lambda _i: self.refresh_scene())
        lv.addWidget(self.track_list, 2)
        box = QGroupBox("Compare")
        f = QFormLayout(box)
        self.ref_combo, self.cmp_combo = QComboBox(), QComboBox()
        self.align_combo = QComboBox()
        for label, mode in (("time from event", "time"), ("distance from event", "dist"),
                            ("same place on the reference path", "place"),
                            ("distance to the runway (landing)", "runway")):
            self.align_combo.addItem(label, mode)
        self.event_combo = QComboBox()
        self.event_combo.addItems(["start of each track", "closest approach to a point", "explicit times"])
        self.point_edit = QLineEdit()
        self.point_edit.setPlaceholderText("x, y[, alt]  (metres)")
        self.ev_ref, self.ev_cmp = QDoubleSpinBox(), QDoubleSpinBox()
        for sb in (self.ev_ref, self.ev_cmp):
            sb.setRange(-1e7, 1e7)
            sb.setDecimals(2)
        f.addRow("Reference (gold)", self.ref_combo)
        f.addRow("Comparison", self.cmp_combo)
        f.addRow("Align by", self.align_combo)
        f.addRow("Event", self.event_combo)
        f.addRow("Point", self.point_edit)
        evr = QHBoxLayout()
        evr.addWidget(self.ev_ref)
        evr.addWidget(self.ev_cmp)
        f.addRow("Event times", evr)
        go = QPushButton("Compare")
        go.clicked.connect(self.run_compare)
        clear = QPushButton("Clear")
        clear.clicked.connect(self.clear_compare)
        row = QHBoxLayout()
        row.addWidget(go)
        row.addWidget(clear)
        f.addRow(row)
        lv.addWidget(box)
        vrow = QHBoxLayout()
        vrow.addWidget(QLabel("3D vertical scale ×"))
        self.vex = QDoubleSpinBox()
        self.vex.setRange(0, 50)
        self.vex.setDecimals(1)
        self.vex.setSpecialValueText("auto")
        self.vex.setToolTip("Exaggerate heights in the 3D view (auto: flat scenes such as approaches are stretched "
                            "until height is a quarter of the width). Plots are always true values.")
        self.vex.valueChanged.connect(lambda _v: self.refresh_scene())
        vrow.addWidget(self.vex)
        lv.addLayout(vrow)
        lv.addWidget(QLabel("Plot channels"))
        self.chan_list = QListWidget()
        self.chan_list.itemChanged.connect(lambda _i: self.refresh_plots())
        lv.addWidget(self.chan_list, 2)
        self.readout = QLabel()
        self.readout.setWordWrap(True)
        self.readout.setTextFormat(Qt.TextFormat.RichText)
        lv.addWidget(self.readout)
        left.setMaximumWidth(330)

        self.view3d = gl.GLViewWidget()
        self.view3d.setBackgroundColor(QColor("#14181f"))
        self.plots = pg.GraphicsLayoutWidget()
        self.plots.setBackground("#14181f")
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.view3d)
        split.addWidget(self.plots)
        split.setSizes([480, 420])

        bar = QHBoxLayout()
        self.play_btn = QPushButton("▶")
        self.play_btn.setFixedWidth(40)
        self.play_btn.clicked.connect(self.toggle_play)
        self.speed = QComboBox()
        for s in SPEEDS:
            self.speed.addItem("%gx" % s, s)
        self.speed.setCurrentIndex(SPEEDS.index(1))
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.valueChanged.connect(self._slider_moved)
        self.time_label = QLabel("0.0 s")
        self.time_label.setMinimumWidth(170)
        for w in (self.play_btn, self.speed):
            bar.addWidget(w)
        bar.addWidget(self.slider, 1)
        bar.addWidget(self.time_label)

        centre = QWidget()
        cv = QVBoxLayout(centre)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.addWidget(split, 1)
        cv.addLayout(bar)
        main = QSplitter(Qt.Orientation.Horizontal)
        main.addWidget(left)
        main.addWidget(centre)
        main.setSizes([320, 1100])
        self.setCentralWidget(main)
        fm = self.menuBar().addMenu("&File")
        a = QAction("&Open recordings…", self)
        a.triggered.connect(self.open_dialog)
        fm.addAction(a)
        self.resize(1440, 920)
        for name in PLOT_CHANNELS:
            it = QListWidgetItem(name)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if name in DEFAULT_ON else Qt.CheckState.Unchecked)
            self.chan_list.addItem(it)

    # ---------------- loading ----------------
    def open_dialog(self):
        paths, _ = QFileDialog.getOpenFileNames(self, "Open Tacview recordings", os.path.expanduser("~"),
                                                "Tacview ACMI (*.acmi *.txt.acmi *.zip.acmi);;All files (*)")
        for p in paths:
            self.load(p)

    def load(self, path, keys=None):
        """Load a recording's aircraft (or only `keys`: ids, names or 'player'). Returns the new Tracks."""
        rec = acmi.read(path)
        objs = [rec.find(k) for k in keys] if keys else [o for o in rec.aircraft() if len(o.t) > 2]
        base = os.path.basename(path)
        origin = (self.tracks[0][0].raw_origin if self.tracks else (rec.ref_lon, rec.ref_lat))
        new = []
        for o in objs:
            tr = Track(o, origin=origin, source=path, label="%s — %s" % (o.label(), base))
            tr.raw_origin = origin
            col = PALETTE[len(self.tracks) % len(PALETTE)]
            self.tracks.append((tr, col))
            new.append(tr)
            it = QListWidgetItem(tr.label)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked)
            it.setForeground(QColor(col))
            self.track_list.addItem(it)
            for cb in (self.ref_combo, self.cmp_combo):
                cb.addItem(tr.label)
        if self.cmp_combo.count() > 1 and self.cmp_combo.currentIndex() == 0:
            self.cmp_combo.setCurrentIndex(1)
        self.origin = None
        self.refresh_scene()
        self.refresh_plots()
        self._set_clock(self.t_range()[0])
        return new

    # ---------------- comparison ----------------
    def run_compare(self):
        if len(self.tracks) < 2:
            return
        ref, cmp_ = self.tracks[self.ref_combo.currentIndex()][0], self.tracks[self.cmp_combo.currentIndex()][0]
        kw = {}
        ev = self.event_combo.currentIndex()
        self.runway = None
        if self.align_combo.currentData() == "runway":
            from .landing import Runway, infer_runway, runway_channels
            txt = self.point_edit.text().replace(" ", "")
            try:
                if txt.count(",") == 3:
                    x, y, hdg, elev = (float(v) for v in txt.split(","))
                    self.runway = Runway(x, y, hdg, elev)
                else:
                    self.runway = infer_runway(ref)
            except ValueError as e:
                self.readout.setText("<span style='color:#d04040'>%s</span>" % e)
                return
            for tr in (ref, cmp_):
                runway_channels(tr, self.runway)
        elif ev == 1:
            try:
                kw["point"] = tuple(float(v) for v in self.point_edit.text().replace(" ", "").split(","))
            except ValueError:
                self.readout.setText("<span style='color:#d04040'>Point: x, y[, alt] in metres</span>")
                return
        elif ev == 2:
            kw["ref_event"], kw["cmp_event"] = self.ev_ref.value(), self.ev_cmp.value()
        chans = [self.chan_list.item(i).text() for i in range(self.chan_list.count())]
        self.cmp = compare(ref, cmp_, chans, mode=self.align_combo.currentData(), **kw)
        if self.runway is not None:
            self.cmp.extra["runway"] = self.runway
        self.refresh_scene()
        self.refresh_plots()
        self._set_clock(self.t_range()[0])

    def clear_compare(self):
        self.cmp = None
        self.refresh_scene()
        self.refresh_plots()
        self._set_clock(self.t_range()[0])

    def visible(self):
        if self.cmp is not None:
            return [(self.cmp.ref, GOLD), (self.cmp.cmp, BLUE)]
        return [(t, c) for k, (t, c) in enumerate(self.tracks)
                if self.track_list.item(k).checkState() == Qt.CheckState.Checked]

    # ---------------- the clock ----------------
    def t_range(self):
        if self.cmp is not None:
            rt = self.cmp.extra["ref_t"]
            ok = np.isfinite(rt) & np.isfinite(self.cmp.extra["cmp_t"])
            return (float(rt[ok][0]), float(rt[ok][-1])) if ok.any() else (0.0, 1.0)
        vis = self.visible()
        if not vis:
            return 0.0, 1.0
        return min(t.t[0] for t, _ in vis), max(t.t[-1] for t, _ in vis)

    def times_now(self):
        """{Track: time} -- where each visible aircraft is drawn at the current clock."""
        if self.cmp is not None:
            a = self.cmp.axis_at_ref_time(self.clock)
            rt, ct = self.cmp.times_at(a)
            return {self.cmp.ref: rt, self.cmp.cmp: ct}
        return {t: self.clock for t, _ in self.visible()}

    def _set_clock(self, t):
        lo, hi = self.t_range()
        self.clock = min(max(t, lo), hi)
        self.slider.blockSignals(True)
        self.slider.setValue(int(round(10000 * (self.clock - lo) / (hi - lo))) if hi > lo else 0)
        self.slider.blockSignals(False)
        self.update_cursor()

    def _slider_moved(self, v):
        lo, hi = self.t_range()
        self._set_clock(lo + (hi - lo) * v / 10000.0)

    def toggle_play(self):
        self.playing = not self.playing
        self.play_btn.setText("⏸" if self.playing else "▶")
        lo, hi = self.t_range()
        if self.playing and self.clock >= hi:
            self._set_clock(lo)

    def _tick(self):
        if not self.playing:
            return
        lo, hi = self.t_range()
        self._set_clock(self.clock + 0.033 * self.speed.currentData())
        if self.clock >= hi:
            self.toggle_play()

    # ---------------- 3D ----------------
    def refresh_scene(self):
        v = self.view3d
        for it in list(v.items):
            v.removeItem(it)
        self.markers = {}
        vis = self.visible()
        if not vis:
            return
        xs = np.concatenate([t.x for t, _ in vis])
        ys = np.concatenate([t.y for t, _ in vis])
        zs = np.concatenate([t["alt"] for t, _ in vis])
        cx, cy = float(np.nanmean([xs.min(), xs.max()])), float(np.nanmean([ys.min(), ys.max()]))
        floor = float(np.floor(np.nanmin(zs) / 100.0) * 100.0) if np.nanmin(zs) > 50 else 0.0
        width = float(max(xs.max() - xs.min(), ys.max() - ys.min(), 200.0))
        height = float(max(np.nanmax(zs) - floor, 1.0))
        self.zx = self.vex.value() or min(10.0, max(1.0, width / (4.0 * height)))
        self.origin = (cx, cy, floor)
        ext = float(max(width, height * self.zx))
        self.glyph = ext * 0.02
        grid = gl.GLGridItem()
        step = 10 ** math.floor(math.log10(ext / 4))
        grid.setSize(ext * 1.6, ext * 1.6)
        grid.setSpacing(step, step)
        grid.setColor((90, 100, 120, 120))
        v.addItem(grid)
        for tr, col in vis:
            pts = np.column_stack([tr.x - cx, tr.y - cy, (tr["alt"] - floor) * self.zx])
            ok = np.isfinite(pts).all(axis=1)
            # translucent, not pyqtgraph's default additive blending (gold + blue overlapping summed to white)
            v.addItem(gl.GLLinePlotItem(pos=pts[ok], color=rgba(col, 0.9), width=2, antialias=True,
                                        glOptions="translucent"))
            shadow = pts[ok].copy()
            shadow[:, 2] = 0.0
            v.addItem(gl.GLLinePlotItem(pos=shadow, color=rgba(col, 0.25), width=1, antialias=True,
                                        glOptions="translucent"))
            body = gl.GLLinePlotItem(pos=np.zeros((6, 3)), color=rgba(col, 1.0), width=3, mode="lines",
                                     glOptions="translucent")
            drop = gl.GLLinePlotItem(pos=np.zeros((2, 3)), color=rgba(col, 0.5), width=1, mode="lines",
                                     glOptions="translucent")
            v.addItem(body)
            v.addItem(drop)
            self.markers[tr] = (body, drop)
        rwy = self.cmp.extra.get("runway") if self.cmp is not None else None
        if rwy is not None:                   # the runway outline, 45 m x 2500 m from the threshold
            h = math.radians(rwy.heading)
            e, r = np.array([math.sin(h), math.cos(h)]), np.array([math.cos(h), -math.sin(h)])
            p0 = np.array([rwy.x - cx, rwy.y - cy])
            ring = [p0 - r * 22, p0 - r * 22 + e * 2500, p0 + r * 22 + e * 2500, p0 + r * 22, p0 - r * 22]
            z = (rwy.elev - floor) * self.zx
            v.addItem(gl.GLLinePlotItem(pos=np.array([[q[0], q[1], z] for q in ring]), color=(0.85, 0.85, 0.85, 1),
                                        width=2, glOptions="translucent"))
        v.setCameraPosition(distance=ext * 1.5, elevation=25, azimuth=-60)
        v.opts["center"] = pg.Vector(0, 0, height * self.zx / 3)
        self.update_cursor()

    def _place_marker(self, tr, t):
        body, drop = self.markers[tr]
        if not np.isfinite(t) or t < tr.t[0] or t > tr.t[-1]:
            body.setData(pos=np.zeros((6, 3)))
            drop.setData(pos=np.zeros((2, 3)))
            return
        cx, cy, floor = self.origin
        p = np.array([tr.at("x", t) - cx, tr.at("y", t) - cy, (tr.at("alt", t) - floor) * self.zx])
        # Heading (true course) first: MiG Alley and Battle of Britain write Tacview's Yaw negated (360 - course),
        # which is what Tacview's model orientation needs in their frame, so Yaw would point the glyph backwards
        ch = "heading" if "heading" in tr.ch else ("yaw" if "yaw" in tr.ch else "course")
        yaw = math.radians(float(tr.at(ch, t)))
        pitch = math.radians(float(tr.at("pitch", t)) if "pitch" in tr.ch else float(tr.at("fpa", t)))
        roll = math.radians(float(tr.at("roll", t))) if "roll" in tr.ch else 0.0
        fwd = np.array([math.sin(yaw) * math.cos(pitch), math.cos(yaw) * math.cos(pitch), math.sin(pitch)])
        right0 = np.array([math.cos(yaw), -math.sin(yaw), 0.0])
        up0 = np.cross(right0, fwd)
        right = right0 * math.cos(roll) - up0 * math.sin(roll)
        up = np.cross(right, fwd)
        L = self.glyph
        body.setData(pos=np.array([p - fwd * L, p + fwd * L,               # fuselage
                                   p - right * L, p + right * L,           # wings (banked)
                                   p - fwd * L, p - fwd * L + up * L * 0.6]))  # fin
        drop.setData(pos=np.array([p, [p[0], p[1], 0.0]]))

    # ---------------- plots ----------------
    def chosen_channels(self):
        return [self.chan_list.item(i).text() for i in range(self.chan_list.count())
                if self.chan_list.item(i).checkState() == Qt.CheckState.Checked]

    def refresh_plots(self):
        self.plots.clear()
        self.cursors, self.row_labels = [], []
        chans = self.chosen_channels()
        first = None
        rows = []
        if self.cmp is not None:
            if self.cmp.mode == "runway":     # the runway frame always leads in a landing comparison
                chans = RUNWAY_ROWS + [c for c in chans if c not in RUNWAY_ROWS]
            chans = [c for c in chans if c in self.cmp.ref_vals]
            for c in chans:
                rows.append((c, [(self.cmp.axis, self.cmp.ref_vals[c], GOLD), (self.cmp.axis, self.cmp.cmp_vals[c], BLUE)]))
            if self.cmp.mode == "place":
                rows.append(("cross_track", [(self.cmp.axis, self.cmp.extra["cross_track"], "#9b4dca")]))
            xlabel = self.cmp.axis_label
        else:
            for c in chans:
                series = [(t.t, t[c], col) for t, col in self.visible() if c in t.ch]
                if series:
                    rows.append((c, series))
            xlabel = "seconds"
        for r, (c, series) in enumerate(rows):
            p = self.plots.addPlot(row=r, col=0)
            p.setLabel("left", c, units=None)
            p.showGrid(x=True, y=True, alpha=0.25)
            p.setMenuEnabled(False)
            if first is None:
                first = p
            else:
                p.setXLink(first)
            for x, y, col in series:
                p.plot(x, y, pen=pg.mkPen(col, width=2 if col == GOLD else 1.5), connect="finite")
            line = pg.InfiniteLine(angle=90, movable=True, pen=pg.mkPen("#e6e6e6", width=1))
            line.sigPositionChanged.connect(self._cursor_dragged)
            p.addItem(line)
            self.cursors.append(line)
            lab = pg.TextItem(anchor=(0, 0), color="#e6e6e6")
            lab.setParentItem(p.vb)
            lab.setPos(4, 2)
            self.row_labels.append((c, lab))
            if r == len(rows) - 1:
                p.setLabel("bottom", xlabel)
        self.update_cursor()

    def _cursor_dragged(self, line):
        if self._cursor_guard:
            return
        a = line.value()
        if self.cmp is not None:
            t, _ = self.cmp.times_at(a)
            if np.isfinite(t):
                self._set_clock(t)
        else:
            self._set_clock(a)

    def update_cursor(self):
        """Move the plot cursors, the 3D aircraft and the readout to the current clock."""
        times = self.times_now()
        for tr, t in times.items():
            if tr in getattr(self, "markers", {}):
                self._place_marker(tr, t)
        a = self.cmp.axis_at_ref_time(self.clock) if self.cmp is not None else self.clock
        self._cursor_guard = True
        for line in getattr(self, "cursors", []):
            if np.isfinite(a):
                line.setValue(a)
        self._cursor_guard = False
        if self.cmp is not None:
            rt, ct = times[self.cmp.ref], times[self.cmp.cmp]
            self.time_label.setText("%s %.1f  |  gold %.1f s  you %.1f s" % (
                "t" if self.cmp.mode == "time" else "d", a, rt, ct))
            if self.cmp.mode == "runway" and getattr(self, "runway", None) is not None:
                self.time_label.setText(self.time_label.text() + "  |  " + ("%.0f m to threshold" % -a if a < 0
                                                                          else "%.0f m past threshold" % a))
            parts = []
            for c, lab in getattr(self, "row_labels", []):
                if c in self.cmp.ref_vals:
                    rv = float(np.interp(a, self.cmp.axis, self.cmp.ref_vals[c]))
                    cv = float(np.interp(a, self.cmp.axis, self.cmp.cmp_vals[c]))
                    d = float(np.interp(a, self.cmp.axis, self.cmp.diff[c]))
                    lab.setText("%s  gold %.1f  you %.1f  Δ %+.1f %s" % (c, rv, cv, d, UNITS.get(c, "")))
                    parts.append("<b>%s</b> Δ %+.1f" % (c, d))
                elif c == "cross_track":
                    x = float(np.interp(a, self.cmp.axis, self.cmp.extra["cross_track"]))
                    lab.setText("cross-track %+.1f m (+ = right of gold)" % x)
            self.readout.setText("<span style='color:%s'>gold</span>: %s<br><span style='color:%s'>you</span>: %s"
                                 "<br>%s" % (GOLD, self.cmp.ref.label, BLUE, self.cmp.cmp.label, " &nbsp; ".join(parts)))
        else:
            self.time_label.setText("t %.1f s" % self.clock)
            for c, lab in getattr(self, "row_labels", []):
                vals = ["%.1f" % t.at(c, self.clock) for t, _ in self.visible() if c in t.ch]
                lab.setText("%s  %s %s" % (c, "  ".join(vals), UNITS.get(c, "")))
            self.readout.setText("")


def main(argv):
    """replaylab view [FILE[:OBJ] ...] [--compare REF_INDEX,CMP_INDEX] [--align time|dist|place] [--point X,Y]"""
    import argparse

    ap = argparse.ArgumentParser(prog="replaylab view")
    ap.add_argument("files", nargs="*")
    ap.add_argument("--compare", help="track indices (0-based, in load order), e.g. 1,0")
    ap.add_argument("--align", choices=("time", "dist", "place", "runway"), default="time")
    ap.add_argument("--point")
    ap.add_argument("--runway", help="X,Y,HEADING,ELEV for --align runway (default: inferred from the gold)")
    a = ap.parse_args(argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    pg.setConfigOptions(antialias=True)
    w = Viewer()
    for spec in a.files:
        path, keys = spec, None
        if ":" in spec and os.path.exists(spec.rsplit(":", 1)[0]):
            path, k = spec.rsplit(":", 1)
            keys = [k]
        w.load(path, keys)
    if a.compare:
        r, c = (int(v) for v in a.compare.split(","))
        w.ref_combo.setCurrentIndex(r)
        w.cmp_combo.setCurrentIndex(c)
        w.align_combo.setCurrentIndex([w.align_combo.itemData(i) for i in range(w.align_combo.count())].index(a.align))
        if a.runway:
            w.point_edit.setText(a.runway)
        if a.point:
            w.event_combo.setCurrentIndex(1)
            w.point_edit.setText(a.point)
        w.run_compare()
    w.show()
    shot = os.environ.get("REPLAYLAB_SHOT")       # test hook: screenshot at a point of the timeline, then exit
    if shot:
        frac = float(os.environ.get("REPLAYLAB_SHOT_AT", "0.5"))

        def take():
            lo, hi = w.t_range()
            w._set_clock(lo + (hi - lo) * frac)
            app.processEvents()
            w.grab().save(shot)
            print("[replaylab] screenshot %s at clock %.2f" % (shot, w.clock), flush=True)
            app.quit()
        QTimer.singleShot(1500, take)
    return app.exec()
