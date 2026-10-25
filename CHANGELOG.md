# Changelog

## Unreleased

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
