"""Connected sets of BaseVolume placements - the mass model, done as CSG.

A solid in constructive solid geometry is an r-set: a bounded, closed, regular
semi-analytic subset of R^3. A CSG tree has primitive instances at its leaves
and *rigid motions plus regularized boolean operators* at its internal nodes
(Requicha). CGA shape, the standard for procedural building massing, calls the
same thing a scope: an oriented bounding box, which is exactly a Matrix4
placement of the canonical 1/1 UnitBox, and builds the mass model as set
operations over scopes (Mueller et al., SIGGRAPH 2006).

This project had the transform half and not the combining half. The compiler
implements regularized union, intersection and difference, and the hand-written
programs use them, but the *generator* only ever emitted a unary chain -
`_OPERATOR_KIND` in ``synthesis.py`` has carried no boolean operator since the
commit that introduced it. So the language could express a composed mass and
the supply could never produce one.

The one property a composition must have is that the regularized union is a
single r-set component: a mass in two disconnected pieces is not a building,
and the downstream gates reject it. That is decidable in closed form and does
not need a compile. Two axis-aligned boxes share volume exactly when their
intervals overlap on all three axes, so the scopes' intersection graph is
computable directly, and a set whose graph is connected has a connected union.

``sample_connected_scope_set`` therefore does not sample-and-reject. It grows a
spanning tree: every scope after the first is placed against an already-placed
one with a guaranteed overlap, so the intersection graph contains a spanning
tree by construction and connectivity is an invariant of the generator rather
than a property to be tested for afterwards. ``scope_set_is_connected`` states
the predicate independently, and the tests use it to check the guarantee.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScopePlacement:
    """One placement of the canonical UnitBox: a scale and an offset."""

    scale: tuple[float, float, float]
    offset: tuple[float, float, float]

    def interval(self, axis: int) -> tuple[float, float]:
        return self.offset[axis], self.offset[axis] + self.scale[axis]


def scopes_share_volume(left: ScopePlacement, right: ScopePlacement) -> bool:
    """Two axis-aligned scopes share volume iff they overlap on every axis."""

    for axis in range(3):
        low_a, high_a = left.interval(axis)
        low_b, high_b = right.interval(axis)
        if min(high_a, high_b) - max(low_a, low_b) <= 0.0:
            return False
    return True


def scope_set_is_connected(placements: tuple[ScopePlacement, ...]) -> bool:
    """Is the scopes' intersection graph connected?

    The regularized union of a set of solids is one component exactly when
    this graph is connected, so this is the predicate the generator must
    satisfy - checked here without compiling anything.
    """

    if len(placements) <= 1:
        return True
    reached = {0}
    frontier = [0]
    while frontier:
        index = frontier.pop()
        for other in range(len(placements)):
            if other in reached:
                continue
            if scopes_share_volume(placements[index], placements[other]):
                reached.add(other)
                frontier.append(other)
    return len(reached) == len(placements)


def sample_connected_scope_set(
    count: int,
    base_scale: tuple[float, float, float],
    sample,
    *,
    minimum_engagement: float = 0.18,
) -> tuple[ScopePlacement, ...]:
    """Grow ``count`` scopes whose union is provably one component.

    ``sample(index)`` returns a value in [0, 1); the caller supplies whatever
    low-discrepancy source it already uses, so this stays deterministic and
    carries no randomness of its own.

    Each new scope is placed against an existing one along a chosen axis. Its
    displacement on that axis is bounded by the parent's extent less a minimum
    engagement, and on the other two axes it is bounded so the intervals still
    overlap. Both bounds are strict, so every new scope shares volume with its
    parent and the intersection graph contains a spanning tree.
    """

    scopes = [ScopePlacement(
        scale=tuple(float(value) for value in base_scale),
        offset=(0.0, 0.0, 0.0),
    )]
    cursor = 0
    for index in range(1, max(1, int(count))):
        parent = scopes[int(sample(cursor) * len(scopes)) % len(scopes)]
        cursor += 1
        # Each level gives up some extent, which is what makes a stack read as
        # stacked rather than as one prism.
        shrink = 0.62 + 0.30 * sample(cursor)
        cursor += 1
        scale = (
            parent.scale[0] * shrink,
            parent.scale[1] * shrink,
            parent.scale[2],
        )
        primary = int(sample(cursor) * 3.0) % 3
        cursor += 1
        offset = list(parent.offset)
        for axis in range(3):
            # Overlap on `axis` needs the new interval to start before the
            # parent's end and to end after the parent's start:
            #   -(scale[axis] - e) <= d <= parent.scale[axis] - e
            # with e the minimum shared extent on that axis. Sampling strictly
            # inside that window is what makes the shared volume positive.
            engagement = minimum_engagement * min(scale[axis], parent.scale[axis])
            low = -(scale[axis] - engagement)
            high = parent.scale[axis] - engagement
            if high <= low:
                # Degenerate window: the only placement that overlaps is flush.
                offset[axis] = parent.offset[axis]
                continue
            unit = sample(cursor)
            cursor += 1
            if axis == primary:
                # On the chosen axis take the far end of the window, so the
                # move reads as a deliberate shift instead of a wobble.
                offset[axis] = parent.offset[axis] + (
                    high if unit >= 0.5 else low
                )
            else:
                offset[axis] = parent.offset[axis] + low + (high - low) * unit
        scopes.append(ScopePlacement(
            scale=scale,
            offset=(offset[0], offset[1], offset[2]),
        ))
    return tuple(scopes)


__all__ = [
    "ScopePlacement",
    "sample_connected_scope_set",
    "scope_set_is_connected",
    "scopes_share_volume",
]
