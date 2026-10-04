# replaylab

Compare flights recorded as Tacview text ACMI by MiG Alley, Battle of Britain and FreeFalcon, the way GPL's Replay
Analyzer compares laps. The model is a gold-standard flight (the AI's landing, recorded from a camera ship) against
the player's own, aligned and differenced across many channels. Backlog item 19 (REPLAY-LAB-1).

    pip install -e .            # in a venv: numpy, matplotlib, PyQt6, pyqtgraph, PyOpenGL
    replaylab view GOLD.acmi MINE.acmi [--compare 0,1 --align place]
    python3 -m replaylab info FILE.acmi
    python3 -m replaylab compare GOLD.acmi[:OBJ] MINE.acmi[:OBJ] --align time|dist|place \
        [--point X,Y[,ALT]] [--channels alt,gs,vs,g,IAS] --plot out.png --csv out.csv

OBJ is a hex id, a name, or `player` (the default).

- **Alignment.** `time` and `dist` measure from an event in each flight: the closest approach to `--point` (say a
  runway threshold) or `--events T1,T2`. `place` compares the two at the same place along the reference path, like
  laps at the same lap distance, and reports the cross-track offset.
- **Channels.** Everything recorded (position, attitude, IAS, ...), plus derived channels: ground and path speed,
  vertical speed and sink, distance flown, course and turn rate, flight-path angle, and load factor (g).
- **Where the files come from.**
  - MiG Alley and Battle of Britain write a `.acmi` beside each saved replay (`Videos/`).
  - FreeFalcon writes `acmibin/acmiNNNN.txt.acmi` beside every recording. When the recording becomes
    `TAPEnnnn.vhs`, the text file is renamed to `TAPEnnnn.txt.acmi`. It samples at ~11 Hz, where the tape
    samples at ~2 Hz.
- **Units.** Metres, m/s and degrees. MA and BoB tracks use their flat-theatre U/V metres, so sorties in one theatre
  share a frame. Lon/Lat tracks are projected around the reference track's origin.

**Landings** (`replaylab landing GOLD.acmi MINE.acmi [--runway X,Y,HEADING,ELEV] [--glide 3] [--plot out.png]`):
- **The runway frame:** distance to the threshold, centreline offset (+ = right), height above the runway, and
  glide-path deviation in metres and degrees.
- **Touchdown** for each flight: the point past the threshold, centreline offset, ground speed, sink rate over the
  last half second, pitch and peak g.
- **Approach gates** at 3, 2, 1 and 0.5 nm and at the threshold.
- **The approach plot:** both flights on the same distance-from-threshold axis, with both touchdowns marked.

Height is measured from where the wheels sit, since the games record the aircraft's reference point. Without
`--runway`, the runway is inferred from the gold landing: heading from its ground roll, height from its roll
altitude, and the threshold at the gold touchdown point. Flight data alone can't say where the painted threshold
is, so distances then read from the gold touchdown. The viewer has the same mode ("distance to the runway"); type
`x, y, heading, elev` in its Point field to give a runway.

**Recording a gold standard:** see [docs/GOLD_STANDARD.md](docs/GOLD_STANDARD.md). In short: hand your own aircraft
to the game's AI pilot and record it flying the mission (demonstrated in FreeFalcon: the AI landed TE-09 at 1.76 m/s
sink), then fly the same mission yourself.

**The viewer** (`replaylab view`) has three parts:
- **A 3D view** of the paths, with ground shadows, drop lines and banked aircraft glyphs. Heights can be
  exaggerated (auto for flat scenes such as approaches); the plots always show true values.
- **A timeline** with playback from 0.25x to 16x.
- **Stacked channel plots** on one cursor: drag it in any plot, or move the slider, and everything follows.

Pick a reference (gold) and a comparison and press Compare. The plots switch to the aligned axis, and each row
reads `gold ... you ... Δ ...` at the cursor. The two aircraft in 3D are always the pair being compared at that
moment, even when they flew at different times (the clock follows the gold flight).

Tests: `python3 -m unittest -v tests.test_core tests.test_landing`. Synthetic glides, turns and approaches have exact expected answers,
and every MA and BoB recording found on the machine must parse.
