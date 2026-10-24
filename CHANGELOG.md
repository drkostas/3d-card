# Changelog

## Unreleased

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
