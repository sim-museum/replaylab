"""Lining two tracks up, GPL-Replay-Analyzer style, and taking their differences.

Three ways to put a reference track (the gold standard, e.g. the AI's landing) and a comparison track (the
player's) on one axis:
  time   seconds from an event in each track (by default the closest approach to a point, e.g. the runway
         threshold; or explicit event times)
  dist   metres flown since that event
  place  the comparison is projected onto the reference path: each reference sample is compared with the
         comparison at the SAME PLACE (its station along the reference path), the way a lap is compared at the same
         lap distance. Robust when one pilot flew the same approach faster or slower.
"""
import numpy as np

ANGLES = {"course", "heading", "yaw", "roll"}     # differences taken around the circle, in -180..180


def _wrap(d):
    return (d + 180.0) % 360.0 - 180.0


def closest_approach(track, x, y, alt=None):
    """(time, index, distance) of the track's closest approach to a point (3D when alt is given)."""
    d2 = (track.x - x) ** 2 + (track.y - y) ** 2
    if alt is not None:
        d2 = d2 + (track["alt"] - alt) ** 2
    i = int(np.nanargmin(d2))
    return float(track.t[i]), i, float(np.sqrt(d2[i]))


def stations(ref, px, py):
    """Station (metres along the reference path) of each point (px, py), by projection onto the nearest segment."""
    ax, ay = ref.x[:-1], ref.y[:-1]
    bx, by = ref.x[1:], ref.y[1:]
    sx, sy = bx - ax, by - ay
    L2 = sx * sx + sy * sy
    L2[L2 == 0] = 1e-12
    base = ref["dist"][:-1]
    seglen = np.sqrt(L2)
    out = np.empty(len(px))
    off = np.empty(len(px))
    for k, (qx, qy) in enumerate(zip(px, py)):
        u = np.clip(((qx - ax) * sx + (qy - ay) * sy) / L2, 0.0, 1.0)
        cx, cy = ax + u * sx, ay + u * sy
        d2 = (qx - cx) ** 2 + (qy - cy) ** 2
        j = int(np.argmin(d2))
        out[k] = base[j] + u[j] * seglen[j]
        # signed cross-track offset: + = right of the reference direction of travel
        off[k] = np.sign(sx[j] * (qy - cy[j]) - sy[j] * (qx - cx[j])) * -np.sqrt(d2[j])
    return out, off


class Comparison:
    """Two tracks on one axis. axis: the grid; ref/cmp/diff: {channel: array on the grid}."""

    def __init__(self, ref, cmp, mode, axis, ref_vals, cmp_vals, axis_label, extra=None):
        self.ref, self.cmp, self.mode, self.axis, self.axis_label = ref, cmp, mode, axis, axis_label
        self.ref_vals, self.cmp_vals = ref_vals, cmp_vals
        self.diff = {k: (_wrap(cmp_vals[k] - ref_vals[k]) if k in ANGLES else cmp_vals[k] - ref_vals[k])
                     for k in ref_vals}
        self.extra = extra or {}

    def times_at(self, a):
        """The moment in each flight that axis value `a` corresponds to: (ref_t, cmp_t); NaN off the grid."""
        rt = float(np.interp(a, self.axis, self.extra["ref_t"], left=np.nan, right=np.nan))
        ct = float(np.interp(a, self.axis, self.extra["cmp_t"], left=np.nan, right=np.nan))
        return rt, ct

    def axis_at_ref_time(self, t):
        """The axis value at reference time t (the timeline drives the cursor through this)."""
        rt = self.extra["ref_t"]
        ok = np.isfinite(rt)
        return float(np.interp(t, rt[ok], self.axis[ok], left=np.nan, right=np.nan))

    def stats(self, name):
        d = self.diff[name]
        d = d[np.isfinite(d)]
        if d.size == 0:
            return {"n": 0}
        return {"n": int(d.size), "mean": float(d.mean()), "rms": float(np.sqrt((d ** 2).mean())),
                "max_abs": float(np.abs(d).max())}


def compare(ref, cmp, channels, mode="time", ref_event=None, cmp_event=None, point=None, step=None):
    """ref_event/cmp_event: event times; or point=(x, y[, alt]) to use each track's closest approach to it.
    With neither, both tracks are measured from their own start."""
    channels = [c for c in channels if c in ref.ch and c in cmp.ch]
    if point is not None:
        ref_event = closest_approach(ref, *point)[0]
        cmp_event = closest_approach(cmp, *point)[0]
    ref_event = ref.t[0] if ref_event is None else ref_event
    cmp_event = cmp.t[0] if cmp_event is None else cmp_event
    if mode == "time":
        lo = max(ref.t[0] - ref_event, cmp.t[0] - cmp_event)
        hi = min(ref.t[-1] - ref_event, cmp.t[-1] - cmp_event)
        step = step or float(np.median(np.diff(ref.t)))
        grid = np.arange(lo, hi + step / 2, step)
        rv = {c: ref.at(c, grid + ref_event) for c in channels}
        cv = {c: cmp.at(c, grid + cmp_event) for c in channels}
        return Comparison(ref, cmp, mode, grid, rv, cv, "seconds from event",
                          {"ref_event": ref_event, "cmp_event": cmp_event,
                           "ref_t": grid + ref_event, "cmp_t": grid + cmp_event})
    if mode == "dist":
        rd = ref["dist"] - np.interp(ref_event, ref.t, ref["dist"])
        cd = cmp["dist"] - np.interp(cmp_event, cmp.t, cmp["dist"])
        lo, hi = max(rd[0], cd[0]), min(rd[-1], cd[-1])
        step = step or 10.0
        grid = np.arange(lo, hi + step / 2, step)
        rv = {c: np.interp(grid, rd, ref[c], left=np.nan, right=np.nan) for c in channels}
        cv = {c: np.interp(grid, cd, cmp[c], left=np.nan, right=np.nan) for c in channels}
        return Comparison(ref, cmp, mode, grid, rv, cv, "metres flown from event",
                          {"ref_event": ref_event, "cmp_event": cmp_event,
                           "ref_t": np.interp(grid, rd, ref.t), "cmp_t": np.interp(grid, cd, cmp.t)})
    if mode == "place":
        st, off = stations(ref, cmp.x, cmp.y)
        # keep the comparison's samples while it moves forward along the reference path
        order = np.argsort(st, kind="stable")
        st_s = st[order]
        uniq = np.concatenate([[True], np.diff(st_s) > 1e-6])
        st_u = st_s[uniq]
        grid = ref["dist"]
        rv = {c: ref[c].astype(float) for c in channels}
        cv = {c: np.interp(grid, st_u, cmp[c][order][uniq], left=np.nan, right=np.nan) for c in channels}
        xt = np.interp(grid, st_u, off[order][uniq], left=np.nan, right=np.nan)
        cmp_t = np.interp(grid, st_u, cmp.t[order][uniq], left=np.nan, right=np.nan)
        return Comparison(ref, cmp, mode, grid, rv, cv, "metres along the reference path",
                          {"cross_track": xt, "time_delta": (cmp_t - cmp.t[0]) - (ref.t - ref.t[0]),
                           "ref_t": ref.t.copy(), "cmp_t": cmp_t})
    raise ValueError("mode must be time, dist or place")
