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

## MiG Alley and Battle of Britain (identified, not yet demonstrated)

Both Rowan engines hand the player's aircraft to the AI with `ManualPilot::AutoToggle(AUTO)`: the autopilot key, and
the accelerated-time modes. That is the same movecode the computer's aircraft fly, and it includes `AUTO_LANDING`
for the recovery at the end of a sortie. Battle of Britain also has training takeoff and landing missions, flown on
the dedicated `AUTO_TRAININGTAKEOFF` / `AUTO_TRAININGLANDING` movecodes. Those are the natural gold standard there:
the AI flies the training landing, then you fly it. Both games already write the Tacview text file beside each saved
replay (`Videos/<name>.acmi`).

Still to do: run each end to end (the AI flying a full recovery and landing, recorded), and confirm what the
in-game autopilot key does in each game's current port.

## Why not a multiplayer camera ship

- **None of the three games has an observer mode.** Battle of Britain's only "spectator camera" is a test-harness
  camera.
- **A camera ship would watch a different aircraft.** It records the AI flying some other aircraft, in whatever
  formation slot it holds, and you still have to fly the comparison flight separately.
- **The AI-takeover recording is strictly closer to what you'll fly yourself.** Same aircraft, same mission, same
  weather, same start.

If you still want a camera ship, for example to record a whole formation, it would need new code in each game's
multiplayer layer: an occupied slot that flies nothing.
