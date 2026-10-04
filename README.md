# replaylab

Compare flights recorded as Tacview text ACMI by MiG Alley, Battle of Britain and FreeFalcon, the way GPL's Replay
Analyzer compares laps. The model is a gold-standard flight (the AI's landing, recorded from a camera ship) against
the player's own, aligned and differenced across many channels. Backlog item 19 (REPLAY-LAB-1).

    python3 -m replaylab info FILE.acmi
    python3 -m replaylab compare GOLD.acmi[:OBJ] MINE.acmi[:OBJ] --align time|dist|place \
        [--point X,Y[,ALT]] [--channels alt,gs,vs,g,IAS] --plot out.png --csv out.csv

OBJ is a hex id, a name, or `player` (the default).

- **Alignment.** `time` and `dist` measure from an event in each flight: the closest approach to `--point` (say a
  runway threshold) or `--events T1,T2`. `place` compares the two at the same place along the reference path, like
  laps at the same lap distance, and reports the cross-track offset.
- **Channels.** Everything recorded (position, attitude, IAS, ...), plus derived channels: ground and path speed,
  vertical speed and sink, distance flown, course and turn rate, flight-path angle, and load factor (g).
- **Units.** Metres, m/s and degrees. MA and BoB tracks use their flat-theatre U/V metres, so sorties in one theatre
  share a frame. Lon/Lat tracks are projected around the reference track's origin.

Tests: `python3 -m unittest -v tests.test_core`. Synthetic glides, turns and approaches have exact expected answers,
and every MA and BoB recording found on the machine must parse.
