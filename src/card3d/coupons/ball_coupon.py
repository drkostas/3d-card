"""Ball-joint coupon. Checks that a ball and socket assemble, hold, and turn, by measuring them.

For each ball size the check builds the socket in a small block and the ball on a stem, using the
joint geometry in card3d.joints, and measures four things.

1. The socket is one solid with no sealed voids inside it.
2. The socket rim is narrower than the ball, so something retains the ball.
3. Pulling the ball out of the socket meets interference, so the ball does not fall out.
4. The seated ball tilts at least 30 degrees in every direction without clashing.

To use it, run `python -m card3d.coupons.ball_coupon`. It reports each size from 3 mm to 6 mm. Then
print the joints at the sizes you need, push each ball into its socket by hand and test the twist.
If a ball is too tight or falls out, adjust the clearance in card3d.joints and run the check again.

The checks encode the following lessons.

- A ball joint for a kit that is printed flat and assembled by hand needs a mouth the ball can be
  pushed through. A cavity whose only opening is a stem bore narrower than the ball cannot be
  assembled.
- `trimesh.util.concatenate` merges face lists and does not perform a union. Cutters combined that
  way remain overlapping shells, and subtracting them leaves walls where they cross. The socket can
  then contain sealed voids and still report `is_watertight`. Check 1 catches this.
- A cylindrical mouth through a full spherical cavity cannot retain anything. The cavity is the
  ball plus clearance, so wherever the bore is narrower than the cavity it is also narrower than
  the ball. Check 2 catches this.
- Retention is not measured on the seated ball. A seated ball should not touch the rim, so zero
  interference there is correct. The test pulls the ball out and measures what it has to pass on
  the way, which is check 3.
"""
import numpy as np
import trimesh

from card3d import joints as J


def socket_block(size, axis, at):
    """Return a block standing in for the parent part, with just enough material to hold the cup."""
    R = size / 2.0
    c = J.ball_centre(size, axis, at)
    blk = trimesh.creation.cylinder(radius=R + J.BALL_CLEAR + J.BALL_WALL,
                                    height=(R + J.BALL_CLEAR) * 2 + J.BALL_WALL * 2)
    blk.apply_translation(c)
    return blk.difference(J.female("ball", size, axis, at))


def check(size=5.0, verbose=True):
    """Measure one ball size and return the results, with "ok" true when all four checks pass."""
    axis, at = np.array([0.0, 0.0, 1.0]), np.zeros(3)
    R = size / 2.0
    c = float(J.ball_centre(size, axis, at)[2])
    depth = J.ball_depth(size)
    rim = float(np.sqrt((R + J.BALL_CLEAR) ** 2 - depth ** 2))

    sock = socket_block(size, axis, at)
    ball = J.male("ball", size, axis, at, backset=3.0)

    pieces = sock.split(only_watertight=False)
    solids = [p for p in pieces if p.volume > 0]
    voids = [p for p in pieces if p.volume < 0]

    # 1. the socket must be one solid with nothing sealed inside it
    sound = len(solids) == 1 and not voids

    # 2. the rim must be narrower than the ball, or nothing holds it in
    grips = rim < R

    # 3. the ball must resist being pulled out
    peak = 0.0
    for d in np.arange(0.0, R * 1.2, R * 0.12):
        b = ball.copy()
        b.apply_translation([0, 0, -float(d)])
        peak = max(peak, abs(sock.intersection(b).volume))

    # 4. seated, the ball must turn. Two rotational degrees of freedom are the purpose of a ball joint
    swing = {}
    for deg in (15, 30, 45):
        worst = 0.0
        for az in range(0, 360, 45):
            T = (trimesh.transformations.rotation_matrix(np.radians(az), [0, 0, 1], [0, 0, c])
                 @ trimesh.transformations.rotation_matrix(np.radians(deg), [1, 0, 0], [0, 0, c]))
            b = ball.copy()
            b.apply_transform(T)
            worst = max(worst, abs(sock.intersection(b).volume))
        swing[deg] = worst
    free_to = max([d for d, v in swing.items() if v < 1.0], default=0)

    if verbose:
        print(f"  ball {size:.1f} mm, cup reaches {depth:.2f} mm past the equator")
        print(f"    socket is one sound solid          {'yes' if sound else 'NO'}"
              f"  ({len(solids)} solid, {len(voids)} sealed void)")
        print(f"    rim {rim:.3f} vs ball radius {R:.2f}    "
              f"{'grips by ' + format(R - rim, '.3f') + ' mm/side' if grips else 'DOES NOT GRIP'}")
        print(f"    resists being pulled out           peak {peak:.3f} mm3"
              f"  {'' if peak > 0.05 else '  <- FALLS OUT'}")
        for d, v in swing.items():
            print(f"    seated, tilted {d:2d} deg all round   clash {v:6.3f} mm3")
        print(f"    turns freely to at least           {free_to} deg")
    return {"sound": sound, "grips": grips, "retain_mm3": peak,
            "free_deg": free_to, "rim": rim, "ball_r": R,
            "ok": bool(sound and grips and peak > 0.05 and free_to >= 30)}


if __name__ == "__main__":
    print("ball and socket, as it would print and as it would be handled")
    allok = True
    for s in (3.0, 4.0, 5.0, 6.0):
        r = check(s)
        allok = allok and r["ok"]
        print()
    print("EVERY SIZE HOLDS AND TURNS" if allok else "SOME SIZE FAILS, see above")
