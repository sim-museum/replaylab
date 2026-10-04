"""replaylab command line.

  replaylab info FILE.acmi
  replaylab compare REF.acmi[:OBJ] CMP.acmi[:OBJ] [--align time|dist|place] [--point X,Y[,ALT]]
                    [--events T_REF,T_CMP] [--channels alt,gs,vs,g] [--plot out.png] [--csv out.csv]
OBJ is a hex id, a name, or 'player' (the default).
"""
import argparse
import csv
import os
import sys

import numpy as np

from . import acmi
from .align import compare
from .track import Track

DEFAULT_CHANNELS = ["alt", "gs", "vs", "g", "IAS", "roll", "pitch", "course"]
UNITS = {"hat": "m", "gp_dev": "m", "gp_dev_deg": "deg", "rwy_dist": "m", "rwy_xtrack": "m", "alt": "m", "x": "m", "y": "m", "gs": "m/s", "tas": "m/s", "vs": "m/s", "sink": "m/s", "IAS": "m/s",
         "TAS": "m/s", "dist": "m", "roll": "deg", "pitch": "deg", "yaw": "deg", "heading": "deg", "course": "deg",
         "turn": "deg/s", "fpa": "deg", "g": "g", "AOA": "deg", "AGL": "m", "cross_track": "m"}


def load(spec, origin=None):
    """FILE or FILE:OBJ -> (recording, Track). Without OBJ: the Pilot=Player object, else the first aircraft."""
    path, key = spec, ""
    if ":" in spec:
        p, k = spec.rsplit(":", 1)
        if os.path.exists(p):
            path, key = p, k
    rec = acmi.read(path)
    if key:
        obj = rec.find(key)
    else:
        players = [o for o in rec.objects.values() if o.props.get("Pilot", "").lower() == "player"]
        obj = players[0] if players else rec.aircraft()[0]
    return rec, Track(obj, origin=origin or (rec.ref_lon, rec.ref_lat), source=path)


def cmd_info(a):
    rec = acmi.read(a.file)
    g = rec.globals
    print("%s\n  %s | %s | reference %s, %.4f/%.4f" % (a.file, g.get("DataSource", "?"), g.get("Title", ""),
                                                      g.get("ReferenceTime", "?"), rec.ref_lon, rec.ref_lat))
    for o in rec.objects.values():
        if not o.t:
            continue
        tr = Track(o, origin=(rec.ref_lon, rec.ref_lat))
        print("  %-34s %5d samples  t=%7.1f..%7.1f s  alt %6.0f..%6.0f m  gs %4.0f..%4.0f m/s  [%s]" % (
            o.label()[:34], tr.t.size, tr.t[0], tr.t[-1], np.nanmin(tr["alt"]), np.nanmax(tr["alt"]),
            np.nanmin(tr["gs"]), np.nanmax(tr["gs"]), ",".join(sorted(o.channels)) or "-"))
    if rec.events:
        print("  events: %d (first: %.1f s %s)" % (len(rec.events), rec.events[0][0], rec.events[0][1][:60]))


def cmd_compare(a):
    rrec, ref = load(a.ref)
    _crec, cmp_ = load(a.cmp, origin=(rrec.ref_lon, rrec.ref_lat))
    point = tuple(float(v) for v in a.point.split(",")) if a.point else None
    ev = [float(v) for v in a.events.split(",")] if a.events else (None, None)
    chans = a.channels.split(",") if a.channels else DEFAULT_CHANNELS
    c = compare(ref, cmp_, chans, mode=a.align, ref_event=ev[0], cmp_event=ev[1], point=point)
    print("reference : %s  (%s)\ncomparison: %s  (%s)\naligned by %s; %d points" % (
        ref.label, ref.source, cmp_.label, cmp_.source, c.axis_label, c.axis.size))
    print("  %-8s %10s %10s %10s   (comparison minus reference)" % ("channel", "mean", "rms", "max|d|"))
    for k in c.diff:
        s = c.stats(k)
        if s["n"]:
            print("  %-8s %10.2f %10.2f %10.2f %s" % (k, s["mean"], s["rms"], s["max_abs"], UNITS.get(k, "")))
    if a.csv:
        with open(a.csv, "w", newline="") as f:
            w = csv.writer(f)
            keys = list(c.diff)
            w.writerow([c.axis_label] + ["ref_" + k for k in keys] + ["cmp_" + k for k in keys])
            for i in range(c.axis.size):
                w.writerow([round(float(c.axis[i]), 3)] + [c.ref_vals[k][i] for k in keys] +
                           [c.cmp_vals[k][i] for k in keys])
        print("wrote", a.csv)
    if a.plot:
        plot(c, a.plot)
        print("wrote", a.plot)


def plot(c, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    keys = [k for k in c.diff if c.stats(k)["n"]]
    bottom = "cross_track" in c.extra or c.mode in ("time", "dist")
    rows = len(keys) + (1 if bottom else 0)
    fig = plt.figure(figsize=(13, 2.2 * rows))
    gs = fig.add_gridspec(rows, 2, width_ratios=[3, 1.2])
    ax0 = None
    for i, k in enumerate(keys):
        ax = fig.add_subplot(gs[i, 0], sharex=ax0)
        ax0 = ax0 or ax
        ax.plot(c.axis, c.ref_vals[k], color="#c9a227", lw=1.6, label="reference")
        ax.plot(c.axis, c.cmp_vals[k], color="#2f7de1", lw=1.2, label="comparison")
        ax.set_ylabel("%s\n%s" % (k, UNITS.get(k, "")))
        ax.grid(alpha=0.3)
        ax2 = ax.twinx()
        ax2.fill_between(c.axis, 0, c.diff[k], color="#d04040", alpha=0.15, lw=0)
        ax2.set_ylabel("Δ", color="#d04040")
        for x, col, lab in c.extra.get("marks", []):
            ax.axvline(x, color=col, lw=1, ls="--")
        if i == 0:
            ax.legend(loc="upper right", fontsize=8)
            for x, col, lab in c.extra.get("marks", []):
                ax.annotate(lab, (x, 1.0), xycoords=("data", "axes fraction"), color=col, fontsize=8,
                            ha="left", va="bottom")
    if not bottom:
        ax.set_xlabel(c.axis_label)
    else:
        _bottom_row(fig, gs, len(keys), ax0, c)
    pv = fig.add_subplot(gs[:, 1])
    _plan_view(pv, c)
    fig.suptitle("%s  vs  %s" % (c.ref.label, c.cmp.label), fontsize=10)
    fig.tight_layout()
    fig.savefig(path, dpi=90)
    plt.close(fig)


def _bottom_row(fig, gs, r, ax0, c):
    ax = fig.add_subplot(gs[r, 0], sharex=ax0)
    if c.mode == "place":
        ax.plot(c.axis, c.extra["cross_track"], color="#9b4dca")
        ax.set_ylabel("cross-track\nm (+right)")
    else:
        ax.plot(c.axis, np.hypot(c.ref.at("x", c.axis + c.extra["ref_event"]) - c.cmp.at("x", c.axis + c.extra["cmp_event"]),
                                 c.ref.at("y", c.axis + c.extra["ref_event"]) - c.cmp.at("y", c.axis + c.extra["cmp_event"])),
                color="#9b4dca")
        ax.set_ylabel("separation\nm")
    ax.set_xlabel(c.axis_label)
    ax.grid(alpha=0.3)


def _plan_view(pv, c):
    pv.plot(c.ref.x, c.ref.y, color="#c9a227", lw=1.6, label="reference")
    pv.plot(c.cmp.x, c.cmp.y, color="#2f7de1", lw=1.2, label="comparison")
    pv.plot(c.ref.x[0], c.ref.y[0], "o", color="#c9a227")
    pv.plot(c.cmp.x[0], c.cmp.y[0], "o", color="#2f7de1")
    if c.mode != "runway":            # a straight-in approach squashes to a line at equal aspect
        pv.set_aspect("equal", adjustable="datalim")
    rwy = c.extra.get("runway")
    if rwy is not None:
        h = np.radians(rwy.heading)
        e, r = np.array([np.sin(h), np.cos(h)]), np.array([np.cos(h), -np.sin(h)])
        p0 = np.array([rwy.x, rwy.y])
        corners = [p0 - r * 22, p0 - r * 22 + e * 2500, p0 + r * 22 + e * 2500, p0 + r * 22, p0 - r * 22]
        pv.plot([q[0] for q in corners], [q[1] for q in corners], color="#888", lw=1)
    for x, col, lab in c.extra.get("plan_marks", []):
        pv.plot(x[0], x[1], "x", color=col, ms=8)
    pv.set_title("plan view (m)", fontsize=9)
    pv.grid(alpha=0.3)


def cmd_landing(a):
    from .landing import GATES_NM, NM, Runway, gate_values, infer_runway, runway_channels, touchdown

    rrec, ref = load(a.ref)
    _crec, mine = load(a.cmp, origin=(rrec.ref_lon, rrec.ref_lat))
    if a.runway:
        x, y, hdg, elev = (float(v) for v in a.runway.split(","))
        rwy = Runway(x, y, hdg, elev, a.glide)
    else:
        try:
            rwy = infer_runway(ref, glide=a.glide)
        except ValueError as e:
            print("replaylab: %s" % e, file=sys.stderr)
            return 2
    for tr in (ref, mine):
        runway_channels(tr, rwy)
    tds = [touchdown(tr, ground_alt=None if touchdown(tr) else rwy.elev) for tr in (ref, mine)]
    print("gold: %s  (%s)\nyou : %s  (%s)\n%s" % (ref.label, ref.source, mine.label, mine.source, rwy.describe()))
    if not any(tds):
        print("\ntouchdown: neither recording touches down")
    else:
        print("\ntouchdown          %12s %12s %10s" % ("gold", "you", "\u0394"))
    rows = [("point", "rwy_dist", "m past threshold"), ("centreline", "rwy_xtrack", "m (+ right)"),
            ("ground speed", "gs", "m/s"), ("sink rate", "sink", "m/s"), ("pitch", "pitch", "deg"),
            ("peak g", "peak_g", "g")]
    for name, attr, unit in (rows if any(tds) else []):
        v = [getattr(td, attr) if td else float("nan") for td in tds]
        print("  %-14s %12.2f %12.2f %+10.2f  %s" % (name, v[0], v[1], v[1] - v[0], unit))
    for who, td in zip(("gold", "you"), tds):
        if any(tds) and td is None:
            print("  (%s did not touch down in this recording)" % who)
    print("\napproach gates     height above runway | glide-path dev | centreline | ground speed  (gold / you)")
    gg, gm = gate_values(ref), gate_values(mine)
    if not any(gg.get(g) and gm.get(g) for g in GATES_NM):
        print("  no gate reached by both: gold ends %.1f nm and you end %.1f nm before the threshold" % (
            -ref["rwy_dist"][-1] / NM, -mine["rwy_dist"][-1] / NM))
    for g in GATES_NM:
        if gg.get(g) and gm.get(g):
            print("  %4.1f nm  %7.1f / %7.1f m | %+6.1f / %+6.1f m | %+6.1f / %+6.1f m | %5.1f / %5.1f m/s" % (
                g, gg[g]["hat"], gm[g]["hat"], gg[g]["gp_dev"], gm[g]["gp_dev"], gg[g]["rwy_xtrack"],
                gm[g]["rwy_xtrack"], gg[g]["gs"], gm[g]["gs"]))
    chans = [c for c in ("hat", "gp_dev", "rwy_xtrack", "gs", "vs", "IAS", "pitch", "roll") if c in ref.ch and c in mine.ch]
    c = compare(ref, mine, chans, mode="runway")
    c.extra["runway"] = rwy
    c.extra["marks"] = [(td.rwy_dist, col, lab) for td, col, lab in zip(tds, ("#c9a227", "#2f7de1"),
                                                                          ("gold TD", "your TD")) if td]
    c.extra["plan_marks"] = [((td.x, td.y), col, "") for td, col in zip(tds, ("#c9a227", "#2f7de1")) if td]
    if a.plot:
        plot(c, a.plot)
        print("\nwrote", a.plot)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="replaylab", description="Tacview flight comparison (MA, BoB, FF)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("info")
    i.add_argument("file")
    c = sub.add_parser("compare")
    c.add_argument("ref")
    c.add_argument("cmp")
    c.add_argument("--align", choices=("time", "dist", "place"), default="time")
    c.add_argument("--point")
    c.add_argument("--events")
    c.add_argument("--channels")
    c.add_argument("--plot")
    c.add_argument("--csv")
    ld = sub.add_parser("landing")
    ld.add_argument("ref")
    ld.add_argument("cmp")
    ld.add_argument("--runway", help="X,Y,HEADING,ELEV: threshold (local m), landing heading, wheels-on alt (m)")
    ld.add_argument("--glide", type=float, default=3.0)
    ld.add_argument("--plot")
    sub.add_parser("view", add_help=False)
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["view"]:
        from .viewer import main as view_main
        return view_main(argv[1:])
    a = ap.parse_args(argv)
    return {"info": cmd_info, "compare": cmd_compare, "landing": cmd_landing}[a.cmd](a) or 0


def entry():
    sys.exit(main())


if __name__ == "__main__":
    entry()
