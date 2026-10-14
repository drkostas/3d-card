# Changelog

## Unreleased

- Ball sockets can now be assembled when the ball sits deep in the part. The cut below the rim used to narrow toward the outside, so a ball seated more than about its own radius under the surface met solid material on the way in. It is now a lead-in a little wider than the ball, and the slit rim is the only squeeze.
- `joints.push_in` measures how hard a ball is to push home into a socket in any part, and the ball coupon checks it as its fifth check.

## 0.1.0

First release.

- `tosprue.build`, `best_card`, `export`, `snip` and `round_trip` make a model-kit card from 3D parts and check it comes apart
- Reading-order layouts through `rows`, `down` and `across`, and the printer bed as a setting
- `sprue` and `roundtrip` for flat kit cards
- `joints` for pegs, axles, pivots, ball joints, tabs and cross laps, with test-print coupons
- `simulator` for overhangs, insertion sweeps, print orientation and a MuJoCo stand-up test
- `labels` for small 3D numbers
- A Claude Code skill, installed with `3d-card skill`
