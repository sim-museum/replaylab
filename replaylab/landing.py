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
        where = ("threshold = the gold touchdown point" if self.source == "inferred" else "threshold as given")
        return "runway %03.1f°, reference alt %.1f m, glide path %.1f° (%s: %s)" % (
            self.heading % 360, self.elev, self.glide, self.source, where)


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


def touchdown(track, ground_alt=None, tol=0.3, flare_from=15.0):
    """First contact after the final descent: the first time, after the aircraft was last `flare_from` m above the
    ground, that it comes within `tol` m of it. ground_alt: the wheels-on-ground altitude (default: the track's own
    ground_reference). None when the track never touches down."""
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


def infer_runway(track, glide=3.0, min_roll_s=3.0):
    """A Runway from a track that lands and rolls: heading from the ground roll, elevation from the roll altitude,
    threshold at the touchdown point. Raises ValueError when the track has no landing roll to read."""
    td = touchdown(track)
    if td is None:
        raise ValueError("%s does not end on the ground, so no runway can be inferred from it -- give one "
                         "(x, y, heading, elevation)" % track.label)
    roll = (track.t >= td.t) & (track["gs"] > 5.0)
    if track.t[roll].size < 3 or track.t[roll][-1] - track.t[roll][0] < min(min_roll_s, track.t[-1] - td.t):
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
