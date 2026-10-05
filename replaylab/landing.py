"""Landing analysis: a runway frame, touchdown detection, and approach gates.

Runway frame channels, added to a track by `runway_channels`:
  rwy_dist    metres along the runway axis from the threshold (negative on approach, positive past it)
  rwy_xtrack  metres from the extended centreline, + = right of it (looking along the landing direction)
  hat         height above the runway reference, m
  gp_dev      height above (+) or below (-) the glide path through the threshold, m
  gp_dev_deg  the same as an angle: the aircraft's elevation angle seen from the threshold minus the glide angle

The runway reference is where the WHEELS are: MiG Alley, Battle of Britain and FreeFalcon record the aircraft's
reference point, which sits gear-height above the surface on the roll. An inferred runway takes its elevation
from the gold flight's own landing roll, so `hat` reads 0 at touchdown for that aircraft type. A runway you give
(`Runway(x, y, heading, elev)`) is used as given.

Inferring a runway from the gold landing: heading from its ground roll, elevation from its roll altitude, and the
"threshold" placed at the gold touchdown point -- flight data alone cannot say where the painted threshold is, so
inferred-runway distances read "from the gold touchdown point" and the glide path is aimed at it.
"""
import math
from dataclasses import dataclass

import numpy as np

NM = 1852.0
GATES_NM = (3.0, 2.0, 1.0, 0.5, 0.0)


@dataclass
class Runway:
    x: float                 # threshold, local metres (east)
    y: float                 # threshold, local metres (north)
    heading: float           # landing direction, degrees true (0 = north, clockwise)
    elev: float              # wheels-on-runway reference altitude, m
    glide: float = 3.0       # glide-path angle, degrees
    source: str = "given"

    def describe(self):
        where = ("threshold = the gold touchdown point" if self.source.startswith("inferred")
                 else "threshold as given")
        return "runway %03.1f°, reference alt %.1f m, glide path %.1f° (%s: %s)" % (
            self.heading % 360, self.elev, self.glide, self.source, where)


def runway_coords(rwy, x, y):
    """(distance past the threshold, offset right of the centreline) of a point, metres."""
    h = math.radians(rwy.heading)
    dx, dy = x - rwy.x, y - rwy.y
    return dx * math.sin(h) + dy * math.cos(h), dx * math.cos(h) - dy * math.sin(h)


def runway_channels(track, rwy):
    """Add the runway-frame channels to `track` (in place) and return it."""
    h = math.radians(rwy.heading)
    ex, ey = math.sin(h), math.cos(h)            # along the landing direction
    rx, ry = math.cos(h), -math.sin(h)           # to the right of it
    dx, dy = track.x - rwy.x, track.y - rwy.y
    d = dx * ex + dy * ey
    track.ch["rwy_dist"] = d
    track.ch["rwy_xtrack"] = dx * rx + dy * ry
    hat = track["alt"] - rwy.elev
    track.ch["hat"] = hat
    track.ch["gp_dev"] = hat - (-d) * math.tan(math.radians(rwy.glide))
    with np.errstate(invalid="ignore", divide="ignore"):
        track.ch["gp_dev_deg"] = np.where(d < -1.0, np.degrees(np.arctan2(hat, -d)) - rwy.glide, np.nan)
    return track


def ground_reference(track, settle_s=2.0):
    """The aircraft's altitude on the ground if the track ENDS on the ground (a landing roll or a stop), else None:
    the last `settle_s` seconds must be level (|vs| < 1 m/s, altitude spread < 1 m)."""
    t, a = track.t, track["alt"]
    tail = t >= t[-1] - settle_s
    if tail.sum() < 3 or t[-1] - t[0] < settle_s * 2:
        return None
    if np.nanmax(np.abs(track["vs"][tail])) > 1.0 or np.ptp(a[tail]) > 1.0:
        return None
    return float(np.median(a[tail]))


@dataclass
class Touchdown:
    t: float
    x: float
    y: float
    gs: float
    sink: float              # m/s over the last 0.5 s before contact
    pitch: float
    peak_g: float            # around contact (-0.5 s .. +1.5 s)
    ground_alt: float
    rwy_dist: float = float("nan")
    rwy_xtrack: float = float("nan")
    extrapolated: float = 0.0   # >0: the recording ends this many metres above the ground and contact was projected


def _touchdown_agl(track, tol, flare_from):
    """Contact from a recorded AGL (height above ground): where it reaches `tol`, or -- when the recording ENDS in the
    flare (Battle of Britain's AI landing leaves the exported list at touchdown) -- projected from the last sample at
    the final sink rate, if that is under 3 m up and descending."""
    t, agl, a = track.t, track["AGL"], track["alt"]
    above = np.where(agl > flare_from)[0]
    start = int(above[-1]) if above.size else 0
    hits = np.where(agl[start:] <= tol)[0]
    if hits.size:
        i = start + int(hits[0])
        g = float(a[i] - agl[i])
        return touchdown(track, ground_alt=g, tol=tol, flare_from=flare_from)
    end_agl = float(agl[-1])
    w = t >= t[-1] - 0.5
    sink = float((a[w][0] - a[-1]) / max(t[-1] - t[w][0], 1e-6))
    if not (0.0 < end_agl < 3.0 and sink > 0.05):
        return None
    dt = end_agl / sink
    vx = float(np.polyfit(t[w], track.x[w], 1)[0]) if w.sum() > 1 else 0.0
    vy = float(np.polyfit(t[w], track.y[w], 1)[0]) if w.sum() > 1 else 0.0
    pitch = float(track["pitch"][-1]) if "pitch" in track.ch else float(track["fpa"][-1])
    td = Touchdown(t=float(t[-1] + dt), x=float(track.x[-1] + vx * dt), y=float(track.y[-1] + vy * dt),
                   gs=float(math.hypot(vx, vy)), sink=sink, pitch=pitch, peak_g=float("nan"),
                   ground_alt=float(a[-1] - end_agl), extrapolated=end_agl)
    return td


def touchdown(track, ground_alt=None, tol=0.3, flare_from=15.0):
    """First contact after the final descent: the first time, after the aircraft was last `flare_from` m above the
    ground, that it comes within `tol` m of it. ground_alt: the wheels-on-ground altitude (default: the recorded AGL
    if any, else the track's own ground_reference). None when the track never touches down."""
    if ground_alt is None and "AGL" in track.ch and np.isfinite(track["AGL"]).any():
        return _touchdown_agl(track, tol, flare_from)
    g = ground_reference(track) if ground_alt is None else ground_alt
    if g is None:
        return None
    t, a = track.t, track["alt"]
    above = np.where(a > g + flare_from)[0]
    start = int(above[-1]) if above.size else 0
    hits = np.where(a[start:] <= g + tol)[0]
    if not hits.size:
        return None
    i = start + int(hits[0])
    # interpolate the crossing of g + tol between samples i-1 and i
    if i > 0 and a[i - 1] > g + tol:
        f = (a[i - 1] - (g + tol)) / (a[i - 1] - a[i])
        tt = float(t[i - 1] + f * (t[i] - t[i - 1]))
    else:
        tt = float(t[i])
    # contact is `tol` below the crossing: extrapolate down at the local sink rate (else a 0.3 m tolerance reads
    # 0.3 s early at 1 m/s -- 20 m of runway at approach speed)
    s0 = float((track.at("alt", tt - 0.5) - track.at("alt", tt)) / 0.5)
    if s0 > 0.05:
        tt = min(tt + tol / s0, tt + 1.0, float(t[-1]))
    sink = float((track.at("alt", tt - 0.5) - track.at("alt", tt)) / 0.5)
    win = (t >= tt - 0.5) & (t <= tt + 1.5)
    pitch = float(track.at("pitch", tt)) if "pitch" in track.ch else float(track.at("fpa", tt))
    td = Touchdown(t=tt, x=float(track.at("x", tt)), y=float(track.at("y", tt)), gs=float(track.at("gs", tt)),
                   sink=sink, pitch=pitch, peak_g=float(np.nanmax(track["g"][win])) if win.any() else float("nan"),
                   ground_alt=g)
    if "rwy_dist" in track.ch:
        td.rwy_dist = float(track.at("rwy_dist", tt))
        td.rwy_xtrack = float(track.at("rwy_xtrack", tt))
    return td


def _runway_from_final(track, td, glide):
    """No roll to read (the recording ends at or just before contact): heading from the straight final approach."""
    t, course = track.t, track["course"]
    ref = float(np.median(course[t >= t[-1] - 2.0]))
    straight = (t >= t[-1] - 20.0) & (np.abs((course - ref + 180.0) % 360.0 - 180.0) < 3.0)
    first = np.where(straight)[0]
    if first.size < 3:
        raise ValueError("%s has no straight final approach to give a runway heading" % track.label)
    head = float(np.degrees(np.angle(np.mean(np.exp(1j * np.radians(course[first]))))) % 360.0)
    return Runway(td.x, td.y, head, td.ground_alt, glide, source="inferred from the final approach")


def infer_runway(track, glide=3.0, min_roll_s=3.0):
    """A Runway from a track that lands: heading from the ground roll (or, with no roll recorded, from the straight
    final), elevation from the roll altitude or the recorded AGL, threshold at the touchdown point. Raises ValueError
    when the track gives neither."""
    td = touchdown(track)
    if td is not None and (td.extrapolated or not ((track.t > td.t + 1.0) & (track["gs"] > 5.0)).any()):
        return _runway_from_final(track, td, glide)
    if td is None:
        raise ValueError("%s does not end on the ground, so no runway can be inferred from it -- give one "
                         "(x, y, heading, elevation)" % track.label)
    # the straight part of the roll only: from touchdown until the course leaves the post-touchdown course by
    # more than 3 degrees or speed drops below 15 m/s. The first real AI landing (FreeFalcon TE-09) rolled
    # straight on 340.0 for a minute, then turned off and taxied; including the taxi gave 335.5.
    t, gs, course = track.t, track["gs"], track["course"]
    ref_course = float(track.at("course", min(td.t + 2.0, t[-1])))
    after = np.where(t >= td.t)[0]
    end = after[-1]
    for i in after:
        if gs[i] < 15.0 or abs((course[i] - ref_course + 180.0) % 360.0 - 180.0) > 3.0:
            end = i - 1
            break
    roll = np.zeros(t.size, bool)
    roll[after[0]:end + 1] = True
    if roll.sum() < 3 or t[roll][-1] - t[roll][0] < min(min_roll_s, t[-1] - td.t):
        raise ValueError("%s's landing roll is too short to give a runway heading" % track.label)
    rx, ry = track.x[roll], track.y[roll]
    # principal direction of the roll, oriented along the direction of travel
    pts = np.column_stack([rx - rx.mean(), ry - ry.mean()])
    _, _, vt = np.linalg.svd(pts, full_matrices=False)
    ux, uy = vt[0]
    if ux * (rx[-1] - rx[0]) + uy * (ry[-1] - ry[0]) < 0:
        ux, uy = -ux, -uy
    heading = math.degrees(math.atan2(ux, uy)) % 360.0
    return Runway(td.x, td.y, heading, td.ground_alt, glide, source="inferred")


def gate_values(track, channels=("hat", "gp_dev", "rwy_xtrack", "gs", "sink"), gates_nm=GATES_NM):
    """{gate_nm: {channel: value}} at each distance before the threshold, on the final approach (the last time the
    track passes that distance while approaching)."""
    d = track["rwy_dist"]
    out = {}
    for g in gates_nm:
        target = -g * NM
        cross = np.where((d[:-1] <= target) & (d[1:] > target))[0]
        if not cross.size:
            out[g] = None
            continue
        i = int(cross[-1])
        f = (target - d[i]) / (d[i + 1] - d[i])
        out[g] = {c: float(track[c][i] + f * (track[c][i + 1] - track[c][i])) for c in channels if c in track.ch}
    return out
