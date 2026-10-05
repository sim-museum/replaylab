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

## MiG Alley (in progress)

"Landing / Takeoff practice" is quick mission 0. Handed to the AI (`MA_AI_PILOT=<seconds>`), the player's jet
goes to `AUTO_LANDING`, but it would orbit at 500 m forever. **That's a 1999 bug, now fixed:** the message that
clears an AI aircraft to land dropped its type byte, and that path runs in multiplayer and whenever a replay
records. With the fix, the clearance arrives and the AI begins the approach turns. It then falls back into the
orbit from the tight turn onto the runway (landing step 3 back to 0), which is the next thing to investigate. The
export writes AGL here too.

## Why not a multiplayer camera ship

- **None of the three games has an observer mode.** Battle of Britain's only "spectator camera" is a test-harness
  camera.
- **A camera ship would watch a different aircraft.** It records the AI flying some other aircraft, in whatever
  formation slot it holds, and you still have to fly the comparison flight separately.
- **The AI-takeover recording is strictly closer to what you'll fly yourself.** Same aircraft, same mission, same
  weather, same start.

If you still want a camera ship, for example to record a whole formation, it would need new code in each game's
multiplayer layer: an occupied slot that flies nothing.
