"""replaylab core: python3 -m unittest -v tests.test_core   (from ~/replaylab)"""
import glob
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from replaylab import acmi  # noqa: E402
from replaylab.align import closest_approach, compare  # noqa: E402
from replaylab.track import Track  # noqa: E402


def approach(t0=0.0, speed=70.0, glide_deg=3.0, offset_y=0.0, lateral=0.0, hz=20, secs=60, oid="1", extra=""):
    """A straight-in approach along +x to a threshold at x=0, alt 0, as Tacview text with U/V transforms."""
    lines = []
    for k in range(int(secs * hz) + 1):
        t = k / hz
        x = -speed * (secs - t) + offset_y
        alt = max(0.0, -x * math.tan(math.radians(glide_deg)))
        lines.append("#%.2f" % (t0 + t))
        lines.append("%s,T=||%.6f|0|-3|90|%.6f|%.6f|90,IAS=%.1f%s" % (oid, alt, x, lateral, speed, extra))
    return lines


def text(*bodies):
    head = ["FileType=text/acmi/tacview", "FileVersion=2.2", "0,ReferenceTime=2026-10-04T00:00:00Z"]
    out = head[:]
    for b in bodies:
        out += b
    return "\n".join(out) + "\n"


class ParserTest(unittest.TestCase):
    def test_partial_updates_removal_escapes_and_lonlat(self):
        rec = acmi.read_text(text([
            "0,ReferenceLongitude=10", "0,ReferenceLatitude=50",
            "#0", "a1,T=0.5|0.25|1000,Name=Spitfire\\, Mk I,Type=Air+FixedWing,Color=Blue,Pilot=Player",
            "#1", "a1,T=|0.26|",                  # only latitude changes
            "#2", "a1,T=0.51||1100,IAS=80",       # lon and alt change
            "// a comment",
            "#3", "-a1",
            "0,Event=Message|a1|landed",
        ]))
        o = rec.find("player")
        self.assertEqual(o.props["Name"], "Spitfire, Mk I")
        self.assertEqual(o.t, [0.0, 1.0, 2.0])
        self.assertEqual(o.pose["lon"], [10.5, 10.5, 10.51])
        self.assertEqual(o.pose["lat"], [50.25, 50.26, 50.26])
        self.assertEqual(o.pose["alt"], [1000.0, 1000.0, 1100.0])
        self.assertEqual(o.channels["IAS"], [None, None, 80.0])
        self.assertEqual(o.removed_at, 3.0)
        self.assertEqual(rec.events, [(3.0, "Message|a1|landed")])
        tr = Track(o, origin=(10.5, 50.25))
        self.assertEqual(tr.frame, "lonlat@10.50000,50.25000")
        self.assertAlmostEqual(tr.y[1], 0.01 / 180 * math.pi * 6371008.8, places=1)

    def test_nine_field_transform_uses_uv(self):
        rec = acmi.read_text(text(approach(secs=2)))
        tr = Track(rec.find("1"))
        self.assertEqual(tr.frame, "uv")
        self.assertAlmostEqual(tr.x[-1], 0.0, places=6)


class DerivedTest(unittest.TestCase):
    def test_straight_glide_has_exact_speeds_and_one_g(self):
        tr = Track(acmi.read_text(text(approach(speed=70, glide_deg=3, secs=60))).find("1"))
        mid = slice(0, None)        # the whole track, ends included
        self.assertTrue(np.allclose(tr["gs"][mid], 70.0, atol=1e-6))
        self.assertTrue(np.allclose(tr["vs"][mid], -70 * math.tan(math.radians(3)), atol=1e-6))
        self.assertTrue(np.allclose(tr["fpa"][mid], -3.0, atol=1e-6))
        self.assertTrue(np.allclose(tr["g"][mid], 1.0, atol=1e-6))
        self.assertTrue(np.allclose(tr["course"][mid], 90.0, atol=1e-6))
        self.assertAlmostEqual(tr["dist"][-1], 70 * 60, places=6)

    def test_level_turn_load_factor(self):
        """A level circle at 100 m/s with radius 500 m: n = sqrt(1 + (v^2/r/g)^2)."""
        v, r, hz = 100.0, 500.0, 20
        lines = []
        for k in range(60 * hz):
            t = k / hz
            a = v / r * t
            lines += ["#%.2f" % t, "1,T=||1000|0|0|0|%.4f|%.4f|0" % (r * math.sin(a), r * math.cos(a))]
        tr = Track(acmi.read_text(text(lines)).find("1"), smooth_s=0)
        expect = math.sqrt(1 + (v * v / r / 9.80665) ** 2)
        self.assertAlmostEqual(float(np.median(tr["g"][50:-50])), expect, places=2)
        self.assertAlmostEqual(float(np.median(tr["turn"][50:-50])), math.degrees(v / r), places=2)


class AlignTest(unittest.TestCase):
    def setUp(self):
        self.ref = Track(acmi.read_text(text(approach(t0=0, glide_deg=3))).find("1"))
        # the "player": same approach flown 37 s later in the recording, 0.5 degrees steeper, 20 m right of centre
        self.cmp = Track(acmi.read_text(text(approach(t0=37, glide_deg=3.5, lateral=-20))).find("1"))

    def test_time_from_threshold_lines_the_flights_up(self):
        c = compare(self.ref, self.cmp, ["alt", "gs"], mode="time", point=(0, 0, 0))
        self.assertAlmostEqual(c.extra["cmp_event"] - c.extra["ref_event"], 37.0, places=6)
        self.assertLess(c.stats("gs")["max_abs"], 1e-6)               # same speed
        i = int(np.argmin(np.abs(c.axis + 10)))                         # 10 s before the threshold, 700 m out
        expect = 700 * (math.tan(math.radians(3.5)) - math.tan(math.radians(3)))
        self.assertAlmostEqual(c.diff["alt"][i], expect, places=3)

    def test_same_place_comparison_and_cross_track(self):
        c = compare(self.ref, self.cmp, ["alt"], mode="place")
        ok = np.isfinite(c.extra["cross_track"])
        self.assertTrue(np.allclose(c.extra["cross_track"][ok], 20.0, atol=1e-6))   # 20 m right of the reference
        j = int(np.argmin(np.abs(self.ref.x + 1000)))                  # 1 km before the threshold
        expect = -self.ref.x[j] * (math.tan(math.radians(3.5)) - math.tan(math.radians(3)))   # that sample's range
        self.assertAlmostEqual(c.diff["alt"][j], expect, places=4)

    def test_course_differences_wrap_around_north(self):
        a = Track(acmi.read_text(text(approach(secs=5))).find("1"))
        b = Track(acmi.read_text(text(approach(secs=5))).find("1"))
        a.ch["course"] = np.full(a.t.size, 359.0)
        b.ch["course"] = np.full(b.t.size, 1.0)
        c = compare(a, b, ["course"], mode="time")
        self.assertTrue(np.allclose(c.diff["course"], 2.0))

    def test_distance_alignment(self):
        c = compare(self.ref, self.cmp, ["alt"], mode="dist", point=(0, 0, 0))
        i = int(np.argmin(np.abs(c.axis + 1400)))
        self.assertAlmostEqual(c.diff["alt"][i], 1400 * (math.tan(math.radians(3.5)) - math.tan(math.radians(3))),
                               places=2)
        self.assertEqual(closest_approach(self.ref, 0, 0, 0)[2], 0.0)


SAMPLES = sorted(set(glob.glob(os.path.expanduser("~/ma-sp/drive_c/rowan/mig/Videos/*.acmi")) +
                     glob.glob(os.path.expanduser("~/Documents/2608*/WP/drive_c/Program Files (x86)/Tacview/bob*.acmi"))))


@unittest.skipUnless(SAMPLES, "no real MA/BoB recordings on this machine")
class RealRecordingsTest(unittest.TestCase):
    def test_every_ma_and_bob_recording_parses(self):
        for path in SAMPLES:
            rec = acmi.read(path)
            air = [o for o in rec.aircraft() if len(o.t) > 2]
            self.assertTrue(air, path)
            for o in air:
                tr = Track(o)
                self.assertTrue(np.all(np.diff(tr.t) > 0), path)
                self.assertEqual(tr.frame, "uv", path)
                self.assertTrue(np.isfinite(tr["gs"]).all(), path)


if __name__ == "__main__":
    unittest.main()
