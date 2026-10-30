# Changelog

## 0.5.0

- A label that is printed follows the nozzle. `labels.number(text, height, depth, nozzle=Nozzle(...))` makes the text tall enough that its thinnest stroke is two of the nozzle's lines (`fit_height`), and at least two layers deep. `labels.stroke_width(text, height)` measures the thinnest stroke, as the widest brush whose opening keeps all but 2% of the text's area. Bold 4 mm text has strokes of 0.44 to 0.51 mm, one line of a 0.4 mm nozzle, so it prints as single wavy lines; at the nozzle it needs about 7 mm. `Nozzle` is 3d-base's, which 3d-card now needs at 0.5.0 or later.
- `BALL_NECK_MIN` says why it stays 2.0 mm with any nozzle. It is a floor for strength in PLA, and tied to the nozzle's lines a 0.2 mm nozzle would give the 1 mm neck that snapped.

## 0.4.1

- `slicecheck.check` compares an override given as a list (one value per extruder or filament, such as `nozzle_volume_type` on a dual-nozzle printer) with the comma-joined value the slicer writes. It compared the list's text and failed every such setting.

## 0.4.0

- A ball's neck is never thinner than `BALL_NECK_MIN` (2.0 mm, five lines of a 0.4 mm nozzle). As a fraction of the ball alone (`BALL_NECK`, 0.34), a 3 mm ball had a 1.02 mm neck, and on a printed kit those balls snapped off at the neck as they were pushed into their sockets. `ball_neck(size)` gives the diameter. A small ball now tilts less before its neck meets the rim, and `ball_coupon` reports it (a 3 mm ball turns 15 degrees, 4 to 6 mm balls 30).
- `female("ball", ...)` and `ball_depth` take `gap` (per side, in the cavity), `grip` (per side, at the rim) and `wall`, `male` takes `neck`, and `socket_reach` takes `gap` and `wall`. `ball_coupon.socket_block` and `ball_coupon.check` pass the same values, so a coupon can print and check one ball size in several fits.

## 0.3.0

- `card3d.slicecheck.parts_as_sliced(parts, card, sliced)` places each part of a card where the slicer printed it, and `part_at(placed, x, y)` names the part nearest a spot on the plate with its distance in mm (0 over the part). Together they tell which part a spot on a camera picture of a finished print is. `plate_transform(card, sliced)` gives the turn and move as one matrix, and `placed_as_sliced` now uses it.

## 0.2.0

- A gate ends in a neck where it meets the part, `NECK_W` 1.0 mm wide and `NECK_H` 0.8 mm tall (four whole layers of 0.2 mm), for the last `NECK_L` 1.0 mm, after the bar of `GATE` 1.8 mm square from the frame. It was the full 1.8 mm square into the part, which printed kit cards avoid (Rego Kit Card necks its gates to about 0.8 mm at whole layers, and a gate as thick as the part tears on removal). The cutter takes the gate at the neck, so the mark on the part is small. `_gate_solid(p0, p1)` builds one.
- `card3d.slicecheck` reads a sliced plate back and checks it against the card, for the settings that landed (`settings_in`), the plate, the filament per layer, each first-layer island's lines and brim (`check`), the walls of every few layers (`coverage`), and a picture of the first layer (`picture`). `placed_as_sliced` finds the card where the slicer put it, including a quarter turn. `read_3mf` reads the G-code 3MF Bambu Studio and OrcaSlicer write, and `toolpath` reads arcs.
- `sprue` and `slicecheck` use trimesh's `to_2D` in place of the deprecated `to_planar`.
- `NEST_UPRIGHT_SLACK` is 10 mm (was 5). With real outlines a C-shaped part often nests lower turned, and at 5 mm one of a mirrored pair of hands came out a quarter turned. `build` returns `reads` (each part's reading turn) and `off_reading` (the parts not at it, also named in the notes, see `off_reading(moved, reads)`), and the nest prefers a try that keeps them.
- `footprint` merges a part's upward-facing triangles on a 0.001 mm grid. The exact merge it used before failed on some fine meshes (a GEOS topology error, or a few broken pieces), and the bounding box took its place, up to three times the part's real shadow, so a nested card was packed round boxes. On one kit five of nineteen parts were nested as boxes, and one shadow came back as a third of its area.
- A number tag on a nested card sits at least `NEST_TAG_OWN` (2 mm) nearer its own part than any other part, so the number cannot send a reader to the wrong part. Two tags keep at least `NEST_TAG_APART` (3 mm) apart, so two numbers never read as one. When no place on the runners passes, the tag stands in the open beside its part on a stub of runner at most `NEST_TAG_STUB` (8 mm) long, as on many moulded frames. A part whose tag still finds no place gets more room and the nest is laid again, as for a part the runners cannot hold, up to `NEST_TRIES` (6) times, and the best try is kept (fewest weak parts, then fewest unclear tags, then the shortest card). Each try reshuffles the whole nest, so the last one was not always the best. `build` returns the tag plates as `tags`, `tag_clearance(tags, parts)` measures them, and a tag that is still unclear is named in the notes.
- `reading_numbers(names, rows)` gives the numbers `build` stamps.
- The numbers stamped on a card follow the reading order given in `rows` (top row first, then left to right), also on a nested card, whose layout has no rows. Parts no row names come after, in alphabetical order. Before, the numbers were alphabetical whatever `rows` said.
- A nested card keeps each part named in `upright` at its reading turn (a head face up, a limb hanging) unless another quarter turn sits more than `NEST_UPRIGHT_SLACK` (10 mm) lower in the nest. `nest_outlines` takes it as `prefer`, a turn per part.
- `build(nest=True)` makes a nested card, the way most printed kit cards are drawn. `nest_outlines` fits the parts close by their real outlines, each tried in four quarter turns, inside a thin frame with round corners. `web_runners` holds every part with two to four thin straight runners from different sides (a straight runner along an axis where one fits, an L of two where a part is boxed in, a 45 degree or shortest runner as the last resort), so the card can be shaken and nothing swings or drops. A part that cannot be held from two sides gets more room and the nest is laid again. Each runner end carries a gate (`_gates_at`), and the result reports `holds` and `weak`.
- `build(plate="NAME")` puts the name on a plate along the top edge of a nested card (`name_plate`).
- `number_tags` gives each part of a nested card a small number tag on a runner near it, as moulded frames do.
- `lay_out_anatomical` takes `frame_w`, `clear` and `lane`, the frame width, the clearance to it and the room between rows, with the old values as defaults.
- `build` and `best_card` take `upright={part: "up" | "long"}`, so a part reads on the card the way it sits on the model. "up" turns the model's up toward the top of the card (a head reads face up). "long" stands a limb's long axis down the card with its joint end at the top. The model's up is carried through the seating turn, so a part laid flat for printing still reads the right way up. It wins over `down` and `across`.
- `build` and `best_card` take `cross=True`, which adds vertical runners in the clear lanes between the horizontal bars, so the frame is a grid and a long part is held on more than one side. A runner is placed only where it clears every part by `BAR_CLEAR`, so it never fuses a part to the frame. `cross_bars` returns the segments.
- `tosprue.flat_sides(mesh)` returns the two flat sides of a part cut from a plate, for `REST`. A clip or C-ring printed on its flat side has its flexing arms along the layers. Stood on its edge, they are split across the layer lines. The score alone could lay one of a mirrored pair flat and stand the other on its edge.
- `build` and `best_card` return `as_written`, the card written as an STL and read back (3d-base's `as_written`): pieces, holes, touching edges and loose volume. One closed body in memory can be several pieces with holes in the file. Needs 3d-base 0.3.
- `build` and `best_card` return `to_card`, one matrix per part from the world to the card (the seat and then the layout's moves), so a world point such as a joint's centre can be found on the card. `moved` alone starts from the seated part.
- Ball sockets can now be assembled when the ball sits deep in the part. The cut below the rim used to narrow toward the outside, so a ball seated more than about its own radius under the surface met solid material on the way in. It is now a lead-in a little wider than the ball, and the slit rim is the only squeeze.
- `joints.push_in` measures how hard a ball is to push home into a socket in any part, and the ball coupon checks it as its fifth check.
- `tosprue.REST` names the faces a part may rest on, by part name, for what a score cannot judge: a wheel stood on its tread has its sole cut into the tread and no longer rolls. A named part is seated only on those faces, and the seat log records `rest` as `named` or `scored`. Parts not named are seated as before.

## 0.1.0

First release.

- `tosprue.build`, `best_card`, `export`, `snip` and `round_trip` make a model-kit card from 3D parts and check it comes apart
- Reading-order layouts through `rows`, `down` and `across`, and the printer bed as a setting
- `sprue` and `roundtrip` for flat kit cards
- `joints` for pegs, axles, pivots, ball joints, tabs and cross laps, with test-print coupons
- `simulator` for overhangs, insertion sweeps, print orientation and a MuJoCo stand-up test
- `labels` for small 3D numbers
- A Claude Code skill, installed with `3d-card skill`
