---
name: 3d-card
description: Use when turning a set of 3D parts into one printable kit card or sprue (parts gated to a flat frame, printed together, snipped free and assembled), when designing push-fit or pose-holding joints (pegs, axles, pivots, ball joints, tabs, laps) and measuring the printer's clearances with coupons, when checking that a part or card will print (first layer, overhangs, orientation), and when a kit card does not release its parts, a part breaks on the cut, or a card print fails on the plate. Python package `3d-card`, imported as `card3d`.
---

# 3d-card, from designed parts to a kit that prints and assembles

A kit card is a flat frame with the parts attached by small gates, like the sprue of a plastic model kit. The whole card prints in one job, each gate is cut with flush nippers, and the parts are assembled by hand. The frame is not decoration. It is a brim for every small part, because its long continuous walls hold the small parts to the plate. A card only works if the frame itself prints on layer 1.

This skill is the procedure that produced a working card, in order, with the mistakes that were made on the way and how each one was caught. Follow the order. Every step has a check that can fail, and a step is done only when its check passed and you read the number yourself.

## The rules that come before everything

- Never start a print without the user's explicit go-ahead for that print. A model that is still changing must not be printed, even when the card passes every check.
- Before a print, show the user four things built from the same code path, namely the card as printed (with the brim), the card alone, the parts as they come out of the card (the pieces recovered by the cut, not the input parts), and the assembled model. A card approved from one picture of the finished model failed on the plate.
- Measure, do not read pictures for contact. A render is reliable about shape and about absence (is there a hand, is the limb straight). It is unreliable about contact and overlap (do two parts touch, does a part hang over an edge). Every "they touch" reading from a render that was not measured was wrong. Render a part in world orientation when the question is where it sits, and in its own axes when the question is what it is.
- A check must be able to go red. Several checks in this work passed while the defect was present (one compared against a part the pipeline added later, one measured a bounding box that included a post meant to sit inside another part). When you add a check, break the thing once on purpose and confirm the check fails.
- When a number does not move after a change, stop editing. The changed code is not on the path that ran, or the value is overwritten later. Probe which code runs before changing anything else. This happened five times in a row with `oriented()`, which `build` never calls while `seat=True`.

## Step 1. Measure the clearances on your printer

The joint geometry in `card3d.joints` is cut from three measured numbers, all from one printer in PLA at 0.2 mm layers with a 0.4 mm nozzle.

```python
from card3d import joints
joints.CLEAR        # 0.30 mm diametral, push fits (peg, tab, lap); axles add joints.AXLE_PLAY = 0.45
joints.PIVOT_CLEAR  # 0.20 mm diametral, a pivot that turns by hand and holds a pose
joints.BALL_CLEAR   # equals PIVOT_CLEAR, per side in the ball socket cavity
```

Print the coupons before the card. They cost minutes and the card costs hours.

```bash
python -m card3d.coupons.fit_coupon     # writes fit-coupon2.stl and .step in the current folder
python -m card3d.coupons.ball_coupon    # geometry check of ball sockets at 3, 4, 5 and 6 mm
```

The fit coupon is a strip of five sockets for a 3.00 mm peg at 0.10, 0.15, 0.20, 0.25 and 0.30 mm, with one to five notches under each socket so the strip can still be read later, and five loose pegs printed lying down. Mark every coupon on the part itself. Six identical holes in a row tell you nothing an hour after the print.

How to read it. Ask the person holding it, hole by hole, how the peg went in (normally, with some pressure, with a lot of pressure, not at all), and explain first what a coupon and a socket are, because the words are not obvious to someone who has not designed one. On the reference printer the 0.30 hole took the peg normally, 0.25 needed extra pressure, 0.20 a lot of pressure, and 0.15 and 0.10 did not accept it. The answer sat at the end of the range, so a second coupon for pivots used a wider range (0.15 to 0.40 in steps of 0.05, six levers on 3.0 mm posts, 6 mm deep) and the second hole, 0.20, was the one that turned under finger pressure and held its position.

If your result differs, change the constant once and every joint refits, because each female feature is the male feature plus the clearance.

```python
joints.CLEAR = 0.35        # before building any part
joints.PIVOT_CLEAR = 0.25
```

What was learned about clearances.

- A published clearance only transfers if the assembly method matches. Print-in-place figures say a pose-holding gap of 0.20 mm welds shut, because both faces print against each other. A joint printed apart and pushed together cannot fuse, and there 0.20 holds a pose. The two problems use the same units and are different problems.
- FDM holes print undersize, because the printer pushes material into the hole. Laser cutting is the opposite (the kerf makes holes oversize), so laser clearances do not transfer.
- Elephant-foot compensation in the slicer is a fit setting, not a cosmetic one. A squashed first layer fattens a post until it no longer enters its hole.
- The slicer can fuse or drop features with no warning. Surfaces closer than the slice gap closing radius (often 0.049 mm by default) are merged into one body, so set it to 0.01 mm. With the Arachne wall generator a feature under about 25% of the nozzle (0.10 mm) is dropped, so a gate drawn too thin does not print and its part is loose. Keep at least 0.6 mm of air between parts that must stay separate.

## Step 2. Build the joints into the parts

Each joint is a template with one free dimension, `size`, and everything else is derived. `joints.TEMPLATES` lists them with their size ranges. `male` is what sticks out and is unioned into the child part, `female` is the cutter subtracted from the parent.

```python
from card3d import joints as J
at, axis = (12.0, 0.0, 6.0), (1, 0, 0)
parent = parent.difference(J.female("pivot", 3.4, axis, at))
child = child.union(J.male("pivot", 3.4, axis, at))
made = [{"type": "pivot", "size": 3.4, "axis": axis, "at": at, "child": "arm", "parent": "body"}]
```

Keep the `made` list. The card needs it to keep gates and sole cuts away from every post and socket.

Which joint to use.

- `peg` holds still. The socket is `SOCKET_DEPTH` (1.15 mm) deeper than the peg so it always bottoms out.
- `axle` spins freely, with `AXLE_PLAY` added. Check a turning part with `J.spins(size, hole_wall_mm, board_gap_mm)`, which refuses an axle under 1.6 mm, less than 0.8 mm of wall around the hole, or a part that rubs its support.
- `pivot` turns by hand and holds a pose. It is deeper than a peg (2.6 x size against 2.2 x size), because a short post in a round hole wobbles and a joint that wobbles does not hold a pose.
- `ball` gives two degrees of freedom, for parts that must be twisted in any direction. Use a pivot where one axis is enough.
- `tab` and `lap` are for flat plates of `PLATE` thickness.

What went wrong with joints and is now built in.

- `male` extends the post `BACKSET` (3.5 mm) back into its own part. A post starting exactly at the joint point floats in the gap between two parts that do not touch, and the union leaves two bodies. On a rounded limb end even 3.5 mm did not reach material, so measure that the post is buried, and pass a longer `backset` where it is not.
- A ball socket that is a closed spherical cavity cannot be assembled, because the only opening is narrower than the ball. The socket is a cup that wraps past the equator, with four slits (`BALL_SLITS`, `BALL_SLIT_W` 0.55 mm, wider than a nozzle so the slicer draws them) so the mouth springs over the ball. A solid cup with a mouth smaller than the ball splits or refuses the ball.
- The grip is the input and the cup depth is derived (`J.ball_depth`, `J.ball_grip`). A fixed depth gave a 3 mm ball 0.014 mm of grip, under one layer. The least grip is `BALL_GRIP_MM` 0.12 mm or `BALL_GRIP_FRAC` of the radius.
- A printed ball is truncated at both poles (`BALL_TRUNC_DEG` 70) and never split at the equator. A first layer flares 0.15 to 0.25 mm per side, which is the whole clearance budget, and an equator split puts that flare on the band the socket grips.
- Slits can break through a thin part. Turn them with `slit_phase` (0 to pi/2), find where they reach with `J.slit_tips`, and require the part to clear `J.socket_reach(size)`, which is the slit corner's distance and larger than the radius alone (a 2.70 mm radius reaches 3.41 mm).
- Combine cutters with a real boolean union. `trimesh.util.concatenate` only appends faces, the overlapping shells leave walls inside the socket, and the result still reports watertight. Measured on one socket as 46 mm3 of phantom interference.

Check every joint before it reaches a card.

```python
from card3d import simulator as S
ok, worst_mm3, at_mm = S.insertion_sweep(child_post, parent, axis, travel=10.0)
```

A final-pose check misses a collision on the way in. `insertion_sweep` slides the child along its axis from clear to seated. Sweep the post with `backset=0`, because the buried root never passes through the hole. For ball joints, `card3d.coupons.ball_coupon.check(size)` measures four things (one sound solid with no sealed void, rim narrower than the ball, interference when the ball is withdrawn, at least 30 degrees of free tilt all round). Print the sizes you use and turn them by hand.

## Step 3. Write the source and build the first card

`build` and `best_card` take a callable that returns `(parts, made, notes)`, with parts as named trimesh meshes in their assembled positions.

```python
from card3d import tosprue

def source():
    return parts, made, []

got, report = tosprue.best_card(
    source=source,
    rows=[["head"], ["arm_left", "body", "arm_right"], ["leg_left", "leg_right"]],
    down=["arm_left", "arm_right", "leg_left", "leg_right"],
    across=["head"],
    bed=(235.5, 256.0),
)
got["card"].export("card.stl")
```

`best_card` builds, runs the round trip, and accepts a card only when the round trip holds, the card is one body, and its first layer is at least 2000 mm2. A card whose parts were never attached passes a round trip, so the body count is part of the test. To also try the dense MaxRects layout with a routed runner, pass `anatomical=False`, otherwise both of its attempts use the reading-order layout. `export(out="card", name="card.stl", **kw)` builds once and writes the file.

What `build` does, and the numbers behind it.

1. `seated` turns each part onto one of its convex hull's faces (`REST_FACES` 60 candidates) and shaves a flat sole in `SOLE_STEPS` (0.0, 0.2, 0.3, 0.6, 0.9, 1.2, 1.5 mm) until the first layer reaches `MIN_BED` 30 mm2, never closer than `SOLE_CLEAR` 0.4 mm to a post or socket. The sole is the published practice for printed figures (flat-sided ball joints print without supports), and it costs 0.2 to 12 percent of a part's volume.
2. The layout places rows top to bottom so the card reads like the model and can be assembled without instructions. Parts not named go into a last row. Every part of one kind belongs in `down` or `across`, or an unlisted one keeps its angle and can set the card's width alone.
3. Runner bars `BAR_W` 3.0 mm wide run under each row, at least `BAR_CLEAR` 3.0 mm from every part. The frame is `FRAME_W` 6.0 mm wide and `FRAME_T` 2.4 mm thick (12 layers at 0.2).
4. Gates are `GATE` 1.8 mm square, at most `GATE_MAX` 6.0 mm long, reach `GATE_BITE` 2.0 mm into the part and `GATE_ROOT` 1.6 mm into the frame, and stay at frame level (the part point must be under 3.2 mm high). Two per part, at least `sprue.MIN_GATE_SEP` 4.5 mm apart in the plane, chosen where the assembled model hides the mark best, never within half a joint's size plus 2.16 mm of a joint, and away from sections thinner than 3.9 mm along the cut.
5. Numbers are stamped on the frame on the far side of the bar, so nothing marks a part and no number can merge with a gate.
6. Everything is unioned, slivers under `SLIVER_MM3` are dropped, anything below z=0 is trimmed, the card is healed if it is not a volume, and the first layer, size and bed fit are measured on the built card, not the plan.

Sampling is seeded (`seed=11`), so the same design always gets the same gates. With random sampling two builds of one design differed, one freed every part and the next did not.

## Step 4. Read the build output

With `verbose=True` (the default for `build` and `export`), read every line. `best_card` builds quietly, so after it print `got["notes"]`, or call `build` once with the same options to see the full output.

```
  15 parts on a card 111.1 x 233.5 x 38.5 mm, 30 gates, 1 body(ies)
  first layer on the plate: 6464 mm2
  fits the bed 235.5 x 256.0: True
```

- More than one body means something is loose before any cut. Find what with `tosprue.why_stuck(got)` and the notes.
- The first layer is the card's grip on the plate. Thousands of mm2 is normal. A card resting on a gate nub had 9.5 mm2.
- The bed check is against the built card. Pass `bed=(width, depth)` or set `card3d.sprue.BED`.

The notes, prefixed with `!`, and what to do about each.

- `FIRST LAYER IS ONLY ... mm2` means the card is not on the plate and will print in the air. Find the lowest point (`got["card"].bounds[0]`) and which part or gate reaches it. Do not print.
- `trimmed material that hung below the plate` means something dipped under z=0. The trim is a safety net, and a trim can open holes, so read the next lines for a card that is not a solid.
- `THE CARD IS NOT A SOLID` means no gate can be cut. Heal or rebuild the offending part. One bad input fails the whole union.
- `card union failed (...); parts left loose` names every input that is not a volume, or says that all inputs are volumes and the union itself failed. Check each part with `is_volume` before the card.
- `seating left ... not a volume` means the turn and trim broke a part. Repair that part's mesh at its source.
- `the card came back W x H mm where the layout planned ...` means something reaches past the frame. One case was 17.8 mm longer than planned and stayed hidden until an unrelated change pushed the card off the bed.
- `runner could not reach` (dense layout only) means a part has no branch and therefore no gate.

Read the per-part seating log too, because the card total hides a starved part.

```python
for r in sorted(got["seat"], key=lambda r: r["bed_mm2"]):
    print(r["part"], r["bed_mm2"], r["sole_mm"], r["post_off_plate_deg"], r["lost_pct"])
```

Parts under about 14 mm2 are scored as starved. A part with under about 5 mm2 detaches in the first layers and the nozzle drags it across the plate. Use `tosprue.bed_area(mesh)` for this number, never `simulator.overhang_report(mesh)["bed_area"]`, which counts downward faces near the lowest point and reported 11 mm2 for a part whose real first layer was 0.27 mm2. Posts should lie within about 20 degrees of the plate, because PLA is weak between layers and a post standing in Z shears along them at roughly half its strength.

## Step 5. Read the round trip

```python
report = tosprue.round_trip(got)
```

```
  snipped 30 gates -> 15 parts came off
  matched 15/15
  ROUND TRIP HOLDS
```

The round trip cuts every gate the way flush nippers do (a round cutter of radius 0.85 x GATE, overshooting `OVERSHOOT` 1.6 mm into the frame and stopping at the part's own surface), splits the card, drops crumbs under a quarter of the smallest part's volume, and matches pieces to parts by a global assignment on volume and size. A piece may differ from its part by `VOL_TOL` 0.18 of volume (0.35 under `SMALL_VOL_MM3` 60 mm3, where the gate stub is a large share) and by `BBOX_TOL` 4.0 mm in size.

- `missing X` means X never separated from the frame or from another part. Run `tosprue.why_stuck(got, names=["X"])`, which reports whether X touches the frame, touches another part, how many gates it owns, and whether another part's gate lands on it.
- `wrong (X, volume, size error)` means a piece was recovered but does not match. A large size error with the right volume is a whisker (a gate that was too long, or square gate corners that survived the cut). A small volume is a part the cut broke.
- `ignored N crumb(s)` is normal cutting debris. Debris is filtered because one crumb once took a slot in the assignment and pushed a real part onto the wrong name.

## Step 6. Diagnose a card that does not release its parts

| Symptom | Cause found | How it was caught | Fix |
|---|---|---|---|
| Part missing, touches the frame | A bar 2.0 mm behind the row left 0.5 mm to a part, within one printed layer | `why_stuck` says touches the frame | Bars keep `BAR_CLEAR` 3.0 mm, rows never reach the side rails |
| Small part destroyed on the cut | Two gates 1.67 mm apart on a 7 mm wheel acted as one wide gate | Recovered volume far under the part's | `MIN_GATE_SEP` 4.5 mm, measured in the plane and not in 3D |
| Post cut away with the gate | A 2.8 mm post against a 3.06 mm cutter, the gate landed on the post | Part came back as a 77 mm3 stub of 458 | List every joint in `made` so gates keep clear of it |
| Thin part cut in half | The cutter went 3.6 mm into a 6.94 mm wheel through its thinnest ring | Two pieces where one was expected | Flush cut that stops at the part surface, thickness rule on gate points |
| Piece 10 mm too long | Gate grew to 10.7 mm while chasing thick material | Right volume, wrong length, matched to the wrong name | `GATE_MAX` 6.0 mm. A wider cutter did not help and cut thin parts again |
| Part held by a hairline web | Cutters concatenated rather than unioned, so overlaps cut nothing | Gate showed as 94 percent removed, which is not severed | Union the cutters, one at a time as fallback |
| Part held by gate corners | Cutter radius 1.296 mm against a gate half diagonal of 1.273 mm | Round trip stuck one part short | Radius 0.85 x GATE, 1.53 mm |
| Part held by its number | Stamp centred on the bar merged with a gate | Stuck part with all its gates cut | Stamps on the far side of the bar, sunk 0.4 mm into it |
| Two parts fused | Nesting by projected outline let a part sit 810 mm3 inside another | `why_stuck` says touches the other part | Nest by bounding box, aim gates by outline |
| Card in several bodies | Boxes that only touch (bar end on a rail, L-shaped runner elbows) union as separate bodies | Body count above 1 before any cut | Overlap every joining box by its width |
| Parts left on the frame after orienting | Unknown, seen only with `orient=True` | Two parts missing, every other check clean | Off by default. `best_card` tries options and keeps the passing one |
| Wheels and discs will not release | The nearest point to the frame is a tangent on a curve, the worst place for a gate | Round trip fell from 15/15 to 14/19 when wheels were added | The flat sole gives the part a face near the frame, and the flush cut stops at its surface |

The general pattern behind most of these was a correct idea with no room in it (5 microns of gate below the plate, 23 microns of cutter margin, 0.1 mm of post against its socket, a 7.8 mm3 crumb). When a check fails by a hair, look for the missing margin before a new theory.

## Step 7. Layout size and the bed

- The card is as tall as its tallest part, and the slicer height check is against that.
- Margins must not be counted twice. When both the packer and the layout added a full gap, a card was 84 percent empty (412 cm2 of bed for 67 cm2 of parts). The layout margin is now `GAP` 2.0 mm on top of `sprue.GAP` 7.0 mm only in the dense layout.
- Do not turn each part to its narrowest angle to save width. A narrower part is a taller one, the rows grow, and one card went from 235.6 mm to 265.4 mm long (off a 256 mm bed) with no gain in width. Use `down` and `across` instead.
- If the reading-order card does not fit, wrap a row by listing fewer parts in it, or try `anatomical=False` for the dense layout.

## Step 8. Slice, then verify the slice before printing

- Slice for the plate that is actually on the printer. A job sliced for a smooth cool plate on a textured plate was refused as an incompatible plate, and the bed temperature differs (about 35 against 55 degrees C for PLA).
- Use a brim of about 5 mm, outer only, and confirm in the G-code that it rings every island. The first time it ringed one island, and that was the clue that only one island touched layer 1.
- Dump extruded length per layer from the G-code. Layer 1 should be the largest layer of the card. In the failed print layers 1 to 3 laid down 13, 2.1 and 2.1 mm of filament and layer 4 laid down 894 mm, so the whole card started in the air.
- Confirm every setting you passed actually landed in the G-code. A slicer API silently dropped unknown override keys.
- Print with no supports. Supports scar mating faces and change a fit by about `simulator.SCAR` 0.15 mm, and the frame already holds the parts.

## Step 9. The first physical print

1. Get the user's go-ahead for this exact file.
2. Look at a current camera picture of the plate before starting or clearing anything. Marking a plate clear lets a queued job start, and a job started on an occupied plate prints onto the last object. Queue jobs with manual start so nothing begins on its own.
3. Clean the plate (dish soap and water, then isopropyl alcohol, handle it by the edges). Finger oil is the most common reason PLA does not stick.
4. Watch the first ten layers. A failure caught there costs minutes instead of hours.
5. If it fails, stop the job and look at the photo before forming a theory. In the failed card only the pieces with a large footprint (the frame rails) were still stuck and every small part was in the nest, which pointed at layer 1 and not at the parts.
6. When it finishes, remove the card, cut each gate with flush nippers with the flat face against the part, and never twist a part free. Trim the remaining nub with a blade, not the nippers, which concentrate force and crack small parts.
7. Assemble and record each joint by name as fits and turns, too tight, or too loose. Compare against the coupon result and change `CLEAR` or `PIVOT_CLEAR` only from printed evidence.

## Diagnosing a failed print

| Symptom | Likely cause | Check | Fix |
|---|---|---|---|
| Nest of filament, frame still on the plate, small parts loose | The card started above layer 1 | Per-layer extrusion in the G-code, `got["first_layer_mm2"]` | Find what hangs below z=0, rebuild, confirm the first layer note is gone |
| Single small parts detach and are dragged | Part first layer under about 5 to 14 mm2 | The `seat` log, `bed_area` per part | More sole, a different resting face, a brim |
| Print stops in the first layer with no hardware error | The printer's first-layer inspection judged the layer bad | Printer state and error code | Clean the plate, level the bed, then retry |
| Peg will not enter its socket | Elephant foot, support scar, or a clearance from another printer | Coupon result, `insertion_sweep` with `strip_supports` | Elephant-foot compensation, no supports on mating faces, measured clearance |
| Pivot flops under the model's weight | Clearance too large for a pose-holding joint | Pivot coupon | Smaller `PIVOT_CLEAR` |
| Two parts printed as one | Slicer gap closing radius larger than the gap | The parts in the sliced preview | Set it to 0.01 mm, keep 0.6 mm of air |
| A gate missing from the print | Feature under the slicer's minimum size | Sliced preview at the gate | Keep `GATE` at or above two line widths |

## Other tools in the package

- Flat kit cards of uniform thickness. `sprue.make_card(parts, thickness, inner_w=195.0)` returns a build123d part, the card size, the placement and the gates. Export it with build123d's `export_stl`, load it as a trimesh, and check it with `roundtrip.check(parts, card_mesh, gates, plate)`. A flat gate is `sprue.GATE_W` 1.6 mm (four extrusion widths) and the round trip cuts `roundtrip.GATE_CUT` 2.2 mm.
- Orientation and overhangs. `simulator.best_orientation(mesh, peg_axes)` scores bed contact first, then support, then peg angle. `simulator.overhang_report` flags faces past `OVERHANG_DEG` 45 that need support. `simulator.strip_supports` models a scarred surface standing proud by 0.15 mm.
- Will the assembled model stand. With the `sim` extra, `simulator.convex_pieces(mesh, name, out_dir)` decomposes the assembled model and `simulator.stand_test(pieces, out_dir, nudge=(0.05, 0, 0))` drops it in MuJoCo and reports `standing` (up axis within 25 degrees) and `tilt_deg`. A single convex hull stands on anything, which is why the model is decomposed. If it topples, build with `with_base=True` and a `base_for(parts)` callable returning the base mesh and a spec with `size_mm`, `tip_deg` and `com_mm`.
- Numbers for pictures. `labels.beside`, `labels.reading_order` and `labels.spread` number parts in two views so the same part can be found in both. They are scene meshes and are never added to the printed card.

## Before you call a card done

- `got["bodies"] == 1`, `report["ok"]`, `got["first_layer_mm2"] >= 2000`, `got["fits_bed"]`, and no `!` note left unexplained.
- Every part in the seating log has a real first layer and its posts near the plate.
- Every joint passed `insertion_sweep`, and the clearances come from coupons printed on this printer.
- The four views (as printed, card, recovered parts, assembled) were rebuilt from the current code and looked at, from several sides, after the last change.
- The user said to print this file.
