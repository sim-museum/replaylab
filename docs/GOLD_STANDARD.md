# Recording a gold-standard flight

To compare your landing against the AI's, as GPL's Replay Analyzer compares laps, you need the AI's flight
recorded in the same mission, aircraft and weather. Backlog item 19 imagined joining a multiplayer mission as a
camera ship to record it. Sprint 5 found a better way, available in all three games: **hand your own aircraft to the
AI and record it flying the mission**. The gold flight then has exactly your aircraft type, mission, weather and
starting point, and needs no second machine or observer slot.

## FreeFalcon (demonstrated)

1. **Let the AI fly your jet.** In Setup → Simulation, set **Autopilot** to its third choice ("intelligent"). In
   the Linux port, `FF_AP_MODE=0` forces the same thing for one run without changing your saved setting. With the
   other settings, **A** engages an attitude or waypoint hold that does not land.
2. **Fly the mission and press A** once airborne. The AI flies the route, the approach, the flare, the landing,
   the rollout and the taxi.
3. **The recording is automatic.** The port records every flight, and next to the usual tape it writes
   `acmibin/acmiNNNN.txt.acmi`. When you return to the menus the tape becomes `TAPEnnnn.vhs` and the text file
   becomes `TAPEnnnn.txt.acmi`. That file is your gold.
4. **Fly the same mission yourself**, without A. That recording is yours.
5. **Compare:**

       replaylab landing acmibin/TAPE0194.txt.acmi acmibin/TAPE0195.txt.acmi --plot landing.png
       replaylab view    acmibin/TAPE0194.txt.acmi acmibin/TAPE0195.txt.acmi --compare 0,1 --align runway

**Measured, TE-09 "Landing Final Approach"** (scratch install, `FF_AP_MODE=0`, A at 5 s): the AI landed 166 s after
engaging. Touchdown was at 75.3 m/s (146 kt), sinking 1.76 m/s, at 11.5° pitch and 1.34 g peak, followed by a
straight rollout on 340.0° and a turn off to taxi. Its approach gates (height above the runway, glide-path
deviation, centreline offset, ground speed):

| gate | height | vs a 3° path | centreline | speed |
|---|---|---|---|---|
| 3 nm | 324 m | +33 m | −8 m | 104 m/s |
| 2 nm | 213 m | +19 m | −7 m | 96 m/s |
| 1 nm | 102 m | +4.5 m | −3 m | 86 m/s |
| 0.5 nm | 46 m | −2.6 m | −1.5 m | 83 m/s |
| threshold | 0.2 m | +0.2 m | 0 m | 75 m/s |

The runway was inferred from that landing roll, so the threshold is the AI's own touchdown point (see the README).
The waypoint autopilot is a very different "pilot": with the default setting, its run toward the mission's 0 ft
landing waypoint hit the ground 17 km short, and `replaylab landing` flags that contact as not on the runway.

## Battle of Britain (demonstrated)

The **Landing** training quick mission (Training family, index 1) puts the player's aircraft on the game's
training-landing routine, but in manual control. Handed to the AI, it flies the game's own landing:
- **descent** from 1,219 m;
- a **left-hand circuit**;
- a **steep, Spitfire-style final:** nose −10°, −10 m/s;
- a **flare** to a steady 1 m/s sink at 10° pitch.

In the game today, the only hand-over is accelerated time, which records at a fraction of the rate. The Linux
port adds `BOB_AI_PILOT=<seconds>`, which uses the game's own `AutoToggle` to hand over at normal speed.

The landed aircraft leaves the game's list of moving objects at touchdown, so the export never sees a rollout. The
export therefore now writes Tacview's **AGL** (height above ground, from the game's own terrain) for the player.
replaylab uses it: when a recording ends in the flare just above the ground, contact is **projected** at the final
sink rate, and the report says so.

**Measured**, Landing training: the recording ends 1.27 m above the ground, sinking 1.0 m/s. The projected contact
is at 39.7 m/s (77 kt) and 10.1° pitch (a three-point attitude), on a runway of 336.6° inferred from the straight
final. The field elevation from AGL is 104.7 m; the game's own ground trace says 104.66 m. The final is short
(the AI turns in inside 1 nm), so only the 0.5 nm gate applies.

    BOB_AI_PILOT=10 BOB_QM_INDEX=1 ...   then   replaylab landing acmi_current.txt <yours>.acmi

## MiG Alley (demonstrated)

"Landing / Takeoff practice" is quick mission 0. Handed to the AI (`MA_AI_PILOT=<seconds>`, using the game's own
`AutoToggle`), the F-86 does all of this:
- **holds** over the field;
- is **cleared to land**;
- **turns in**, with an S-turn to line up;
- **flies a steep final** at 115 kt, nose 8° down;
- **flares** to 1 m/s sink at 10° pitch;
- **touches down at 97 kt**, rolls out, taxis and parks.

It took three fixes to get there, and two of them affected every MiG Alley player:
1. **Recording froze the AI's landing.** While a replay records, the game copied a stale copy of the aircraft's
   AI state over the live one every ~20 s, resetting the landing to its first step, so the AI orbited forever.
   It was found with a hardware watchpoint on the landing-step field.
2. **A 1999 dropped byte.** The "cleared to land" message dropped its type byte, which affects multiplayer and
   recording.
3. **The Tacview export's clock ran 2.5x slow** in single player: it used the multiplayer data-rate setting. Every
   MiG Alley Tacview file had a stretched timeline and speeds 2.5x too low, and the export's IAS had been
   "calibrated" to match. The fixed export runs at the sim's real 50 Hz, and its ground speed equals the game's
   own airspeed to 0.1%.

**Measured**, Landing / Takeoff practice: touchdown at 49.8 m/s (97 kt), sinking 1.0 m/s, at 10.1° pitch and
1.22 g peak, on a runway of 135.7° inferred from the rollout. Gates: 1 nm 241 m (+144 m above a 3° path),
0.5 nm 105 m (+56 m), threshold 0 m. The AI flies a steep, fast final and then flares.

## Why not a multiplayer camera ship

- **None of the three games has an observer mode.** Battle of Britain's only "spectator camera" is a test-harness
  camera.
- **A camera ship would watch a different aircraft.** It records the AI flying some other aircraft, in whatever
  formation slot it holds, and you still have to fly the comparison flight separately.
- **The AI-takeover recording is strictly closer to what you'll fly yourself.** Same aircraft, same mission, same
  weather, same start.

If you still want a camera ship, for example to record a whole formation, it would need new code in each game's
multiplayer layer: an occupied slot that flies nothing.
