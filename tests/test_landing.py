"""Landing analysis on synthetic landings with analytic answers: python3 -m unittest -v tests.test_landing"""
import math
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from replaylab import acmi  # noqa: E402
from replaylab.align import compare  # noqa: E402
from replaylab.landing import NM, Runway, gate_values, infer_runway, runway_channels, touchdown  # noqa: E402
from replaylab.track import Track  # noqa: E402

GROUND, GEAR, HC = 10.0, 2.0, 3.0       # runway altitude, gear height, height of the constant-sink final segment


def expected_td_x(aim, v, glide, sink):
    """Where the wheels touch: the glide path reaches HC above the runway at aim - HC/tan(glide), then a constant
    sink covers v*HC/sink metres."""
    return aim - HC / math.tan(math.radians(glide)) + v * HC / sink


def landing(aim=0.0, v=70.0, glide=3.0, sink=1.0, y=0.0, hz=20, before=80.0, roll_s=20.0, decel=3.0, t0=0.0):
    """Land eastbound (heading 090) on a runway at altitude GROUND; returns Tacview text."""
    x_td = expected_td_x(aim, v, glide, sink)
    x_c = aim - HC / math.tan(math.radians(glide))
    x0 = x_td - v * before
    t_c = (x_c - x0) / v
    L = ["FileType=text/acmi/tacview", "FileVersion=2.2"]
    for k in range(int((before + roll_s) * hz) + 1):
        t = k / hz
        if t <= before:
            x = x0 + v * t
            hat = (aim - x) * math.tan(math.radians(glide)) if t <= t_c else max(0.0, HC - sink * (t - t_c))
        else:
            tau = t - before
            x, hat = x_td + v * tau - 0.5 * decel * tau * tau, 0.0
        L += ["#%.3f" % (t0 + t), "1,T=||%.6f|0|%.2f|90|%.6f|%.6f|90,Pilot=Player" % (GROUND + GEAR + hat, -3.0, x, y)]
    return "\n".join(L) + "\n"


def track(**kw):
    return Track(acmi.read_text(landing(**kw)).find("1"))


class LandingTest(unittest.TestCase):
    def setUp(self):
        self.gold = track(aim=0.0, v=70.0, sink=1.0)
        # the player: aimed 400 m long, faster, a firm 2.5 m/s arrival, 8 m right of the centreline (south)
        self.mine = track(aim=400.0, v=75.0, sink=2.5, y=-8.0, t0=33.0)

    def test_touchdown_point_speed_and_sink(self):
        td = touchdown(self.gold)
        self.assertAlmostEqual(td.x, expected_td_x(0, 70, 3, 1.0), delta=0.5)
        self.assertAlmostEqual(td.sink, 1.0, delta=0.02)
        self.assertAlmostEqual(td.gs, 70.0, delta=0.5)
        self.assertAlmostEqual(td.ground_alt, GROUND + GEAR, places=6)
        td2 = touchdown(self.mine)
        self.assertAlmostEqual(td2.x, expected_td_x(400, 75, 3, 2.5), delta=0.5)
        self.assertAlmostEqual(td2.sink, 2.5, delta=0.05)

    def test_runway_inferred_from_the_gold_roll(self):
        rwy = infer_runway(self.gold)
        self.assertAlmostEqual(rwy.heading, 90.0, places=3)
        self.assertAlmostEqual(rwy.elev, GROUND + GEAR, places=6)
        self.assertAlmostEqual(rwy.x, expected_td_x(0, 70, 3, 1.0), delta=0.5)
        self.assertEqual(rwy.source, "inferred")

    def test_runway_frame_and_the_players_touchdown_against_gold(self):
        rwy = infer_runway(self.gold)
        for tr in (self.gold, self.mine):
            runway_channels(tr, rwy)
        td = touchdown(self.mine)
        self.assertAlmostEqual(td.rwy_dist, expected_td_x(400, 75, 3, 2.5) - expected_td_x(0, 70, 3, 1.0), delta=0.6)
        self.assertAlmostEqual(td.rwy_xtrack, 8.0, places=6)                 # right of the centreline
        self.assertAlmostEqual(touchdown(self.gold).rwy_dist, 0.0, delta=0.6)

    def test_approach_compared_at_the_same_distance_from_the_threshold(self):
        rwy = infer_runway(self.gold)
        for tr in (self.gold, self.mine):
            runway_channels(tr, rwy)
        c = compare(self.gold, self.mine, ["hat", "gp_dev", "rwy_xtrack"], mode="runway")
        i = int(np.argmin(np.abs(c.axis + 1000.0)))
        self.assertAlmostEqual(c.diff["hat"][i], 400 * math.tan(math.radians(3)), places=3)   # aimed 400 m long
        # the gold is BELOW a glide path aimed at its own touchdown point by exactly its float past the aim point
        self.assertAlmostEqual(c.ref_vals["gp_dev"][i], -rwy.x * math.tan(math.radians(3)), places=3)
        self.assertTrue(np.allclose(c.cmp_vals["rwy_xtrack"][np.isfinite(c.cmp_vals["rwy_xtrack"])], 8.0))
        rt, ct = c.times_at(-1000.0)
        self.assertAlmostEqual(self.gold.at("rwy_dist", rt), -1000.0, places=3)
        self.assertAlmostEqual(self.mine.at("rwy_dist", ct), -1000.0, places=3)

    def test_gates(self):
        rwy = Runway(0.0, 0.0, 90.0, GROUND + GEAR)                           # a given runway: threshold at x = 0
        runway_channels(self.gold, rwy)
        g = gate_values(self.gold)
        self.assertAlmostEqual(g[1.0]["hat"], NM * math.tan(math.radians(3)), places=2)    # on the glide path
        self.assertAlmostEqual(g[1.0]["gp_dev"], 0.0, places=2)
        self.assertAlmostEqual(g[2.0]["gs"], 70.0, places=3)

    def test_a_track_that_never_lands(self):
        approach_only = Track(acmi.read_text("\n".join(landing().splitlines()[:2 + 2 * 1200])).find("1"))
        self.assertIsNone(touchdown(approach_only))
        with self.assertRaises(ValueError):
            infer_runway(approach_only)


if __name__ == "__main__":
    unittest.main()
