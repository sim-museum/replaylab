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

A jump faster than JUMP_MS (a respawn, a new flight appended to the same file, a recorder glitch) splits the track
into segments: each is derived on its own, so one teleport cannot put 600 km/s and 100000 g on the plots, and the
3D path and the plots leave a gap there instead of a line across the theatre.
"""
import math

import numpy as np

G0 = 9.80665
JUMP_MS = 1500.0      # m/s; Mach 4.4, well past anything these sims fly
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
        self.segments = self._find_segments()
        der = {}
        for a, b in self.segments:
            for k, v in self._derive(a, b, smooth_s).items():
                der.setdefault(k, np.full(self.t.size, np.nan))[a:b] = v
        for k, v in der.items():                # a 1-2 sample glitch segment has no derivative: hold its neighbour's
            if k != "dist" and np.isfinite(v).any():
                idx = np.where(np.isfinite(v), np.arange(v.size), -1)
                np.maximum.accumulate(idx, out=idx)
                first = int(np.argmax(np.isfinite(v)))
                der[k] = v[np.where(idx < 0, first, idx)]
        dist = np.zeros(self.t.size)            # distance flown keeps counting across a jump, but not the jump
        off = 0.0
        for a, b in self.segments:
            dist[a:b] = der["dist"][a:b] + off
            off = dist[b - 1]
        der["dist"] = dist
        self.ch.update(der)

    def _find_segments(self):
        """[(start, stop)] index ranges with no step faster than JUMP_MS between samples."""
        n = self.t.size
        if n < 2:
            return [(0, n)]
        step = np.sqrt(np.diff(self.x) ** 2 + np.diff(self.y) ** 2 + np.diff(self.ch["alt"]) ** 2)
        cut = np.nonzero(step / np.diff(self.t) > JUMP_MS)[0] + 1
        edges = np.concatenate([[0], cut, [n]])
        return [(int(a), int(b)) for a, b in zip(edges[:-1], edges[1:])]

    def path_breaks(self, a):
        """a with NaN at each segment's first sample, so a plot drawn with connect="finite" leaves the jump open."""
        a = np.array(a, dtype=float)
        for s, _ in self.segments[1:]:
            a[s] = np.nan
        return a

    def _derive(self, a, b, smooth_s):
        """Derived channels for samples a:b (one segment)."""
        t = self.t[a:b]
        names = ("gs", "tas", "vs", "sink", "dist", "course", "turn", "fpa", "g")
        if t.size < 3:
            return {k: np.full(t.size, np.nan) for k in names}
        out = {}
        sl = lambda k: self.ch[k][a:b]
        # Differentiate on an EVEN time grid, then interpolate back to the samples. Recordings are not evenly
        # spaced (FreeFalcon's twin interleaves every-3rd-frame samples with the tape's every-16th records, 0.02 to
        # 0.14 s apart), and a moving average over a fixed number of samples bends a straight path into kinks on
        # uneven spacing -- the first FF approach showed ground speed spiking to 2000 m/s from that alone.
        dt = float(np.median(np.diff(t)))
        dt = min(dt, 0.05) if dt > 0 else 0.05
        tg = np.arange(t[0], t[-1] + dt / 2, dt)
        xs, ys, zs = (smooth(np.interp(tg, t, sl(k)), tg, smooth_s) for k in ("x", "y", "alt"))
        vx, vy, vz = np.gradient(xs, tg), np.gradient(ys, tg), np.gradient(zs, tg)
        ax, ay, az = (np.gradient(smooth(v, tg, smooth_s), tg) for v in (vx, vy, vz))
        course_g = np.degrees(np.arctan2(vx, vy)) % 360.0
        turn_g = np.gradient(smooth(unwrap_deg(course_g), tg, smooth_s), tg)
        back = lambda a: np.interp(t, tg, a)
        gs = back(np.hypot(vx, vy))
        out["gs"] = gs
        out["tas"] = back(np.sqrt(vx ** 2 + vy ** 2 + vz ** 2))
        out["vs"] = back(vz)
        out["sink"] = -out["vs"]
        seg = np.hypot(np.diff(sl("x")), np.diff(sl("y")))
        out["dist"] = np.concatenate([[0.0], np.cumsum(seg)])
        out["course"] = np.degrees(np.unwrap(np.radians(back(unwrap_deg(course_g))))) % 360.0
        out["turn"] = back(turn_g)
        out["fpa"] = np.degrees(np.arctan2(out["vs"], gs))
        out["g"] = back(np.sqrt(ax ** 2 + ay ** 2 + (az + G0) ** 2) / G0)
        return out

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
