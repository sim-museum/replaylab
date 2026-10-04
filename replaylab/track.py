"""A flown track: one object's samples as numpy channels, plus channels derived from the motion.

Coordinates are local metres: x east, y north, alt up. A recording with U/V (MiG Alley and Battle of Britain write
their flat theatre metres there) is used as-is, so tracks from different sorties in one theatre share a frame;
otherwise Lon/Lat are projected around an origin (pass the same origin for both tracks of a comparison).

Derived channels (finite differences after a light moving average, so 20 Hz jitter does not swamp them):
  gs        ground speed, m/s             tas    3D path speed, m/s
  vs        vertical speed, m/s (+ up)    sink   -vs
  dist      horizontal distance flown, m  course course over ground, deg (0 = north, clockwise)
  turn      rate of change of course, deg/s
  fpa       flight-path angle, deg        g      load factor from the path's acceleration (1 = level flight)
Recorded numeric properties (IAS, TAS, AOA, AGL, Throttle, ...) are channels too, forward-filled.
"""
import math

import numpy as np

G0 = 9.80665
EARTH_R = 6371008.8


def _ffill(vals):
    """Floats with None forward-filled (leading gaps stay NaN)."""
    a = np.array([np.nan if v is None else v for v in vals], dtype=float)
    if a.size == 0:
        return a
    idx = np.where(np.isfinite(a), np.arange(a.size), 0)
    np.maximum.accumulate(idx, out=idx)
    return a[idx]


def smooth(a, t, window_s):
    """Centred moving average over ~window_s seconds (no-op when the window covers one sample)."""
    if a.size < 3 or window_s <= 0:
        return a
    dt = np.median(np.diff(t)) if t.size > 1 else 0
    n = int(round(window_s / dt)) if dt > 0 else 1
    if n < 2:
        return a
    n |= 1
    k = np.ones(n) / n
    pad = min(n // 2, a.size - 1)
    n = 2 * pad + 1
    k = np.ones(n) / n
    # odd reflection at the ends: a straight line stays exactly straight (repeating the end value made every
    # track appear to stop dead at its first and last sample -- ground speed dipped and g read 8 there)
    ap = np.concatenate([2 * a[0] - a[pad:0:-1], a, 2 * a[-1] - a[-2:-pad - 2:-1]])
    return np.convolve(ap, k, mode="valid")


def unwrap_deg(a):
    return np.degrees(np.unwrap(np.radians(a)))


class Track:
    def __init__(self, raw, origin=None, smooth_s=0.5, label=None, source=""):
        """raw: an acmi.RawObject. origin: (lon, lat) for projection when the track has no U/V."""
        self.raw = raw
        self.label = label or raw.label()
        self.source = source
        t = np.asarray(raw.t, dtype=float)
        keep = np.concatenate([[True], np.diff(t) > 0]) if t.size else np.zeros(0, bool)
        self.t = t[keep]
        P = {k: _ffill(v)[keep] for k, v in raw.pose.items()}
        has_uv = np.isfinite(P["u"]).any() and np.isfinite(P["v"]).any()
        if has_uv:
            self.x, self.y = P["u"], P["v"]
            self.frame = "uv"
        else:
            lon0, lat0 = origin if origin else (P["lon"][0], P["lat"][0])
            self.x = np.radians(P["lon"] - lon0) * EARTH_R * math.cos(math.radians(lat0))
            self.y = np.radians(P["lat"] - lat0) * EARTH_R
            self.frame = "lonlat@%.5f,%.5f" % (lon0, lat0)
        self.ch = {"x": self.x, "y": self.y, "alt": P["alt"], "lon": P["lon"], "lat": P["lat"]}
        for k in ("roll", "pitch", "yaw", "heading"):
            if np.isfinite(P[k]).any():
                self.ch[k] = P[k]
        for k, v in raw.channels.items():
            self.ch[k] = _ffill(v)[keep]
        self._derive(smooth_s)

    def _derive(self, smooth_s):
        t = self.t
        if t.size < 3:
            for k in ("gs", "tas", "vs", "sink", "dist", "course", "turn", "fpa", "g"):
                self.ch[k] = np.full(t.size, np.nan)
            return
        xs, ys, zs = (smooth(self.ch[k], t, smooth_s) for k in ("x", "y", "alt"))
        vx, vy, vz = np.gradient(xs, t), np.gradient(ys, t), np.gradient(zs, t)
        gs = np.hypot(vx, vy)
        self.ch["gs"] = gs
        self.ch["tas"] = np.sqrt(vx ** 2 + vy ** 2 + vz ** 2)
        self.ch["vs"] = vz
        self.ch["sink"] = -vz
        seg = np.hypot(np.diff(self.x), np.diff(self.y))
        self.ch["dist"] = np.concatenate([[0.0], np.cumsum(seg)])
        course = np.degrees(np.arctan2(vx, vy)) % 360.0
        self.ch["course"] = course
        self.ch["turn"] = np.gradient(smooth(unwrap_deg(course), t, smooth_s), t)
        self.ch["fpa"] = np.degrees(np.arctan2(vz, gs))
        ax, ay, az = (np.gradient(smooth(v, t, smooth_s), t) for v in (vx, vy, vz))
        self.ch["g"] = np.sqrt(ax ** 2 + ay ** 2 + (az + G0) ** 2) / G0

    @property
    def channels(self):
        return sorted(self.ch)

    def __getitem__(self, name):
        return self.ch[name]

    def at(self, name, t):
        """Channel `name` linearly interpolated at time(s) t (NaN outside the track)."""
        return np.interp(t, self.t, self.ch[name], left=np.nan, right=np.nan)

    def duration(self):
        return float(self.t[-1] - self.t[0]) if self.t.size else 0.0
