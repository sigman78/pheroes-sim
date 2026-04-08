from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True, slots=True, order=True)
class HexCoord:
    q: int
    r: int

    def neighbors(self) -> tuple["HexCoord", ...]:
        return tuple(HexCoord(self.q + dq, self.r + dr) for dq, dr in _NEIGHBOR_OFFSETS)

    def distance_to(self, other: "HexCoord") -> int:
        dq = self.q - other.q
        dr = self.r - other.r
        ds = (-self.q - self.r) - (-other.q - other.r)
        return max(abs(dq), abs(dr), abs(ds))


_NEIGHBOR_OFFSETS = ((1, 0), (1, -1), (0, -1), (-1, 0), (-1, 1), (0, 1))


def in_bounds(coord: HexCoord, width: int, height: int) -> bool:
    return 0 <= coord.q < width and 0 <= coord.r < height


def hex_line_of_sight(
    origin: HexCoord,
    target: HexCoord,
    walls: frozenset[HexCoord],
    width: int,
    height: int,
) -> bool:
    """Return True if no wall hex lies on the straight path from origin to target."""
    n = origin.distance_to(target)
    if n == 0:
        return True
    oq = origin.q
    or_ = origin.r
    os = -oq - or_
    tq = target.q
    tr = target.r
    ts = -tq - tr
    for i in range(1, n):
        t = i / n
        cq = oq + (tq - oq) * t
        cr = or_ + (tr - or_) * t
        cs = os + (ts - os) * t
        rq, rr, rs = round(cq), round(cr), round(cs)
        dq = abs(rq - cq)
        dr = abs(rr - cr)
        ds = abs(rs - cs)
        if dq > dr and dq > ds:
            rq = -rr - rs
        elif dr > ds:
            rr = -rq - rs
        hex_ = HexCoord(rq, rr)
        if in_bounds(hex_, width, height) and hex_ in walls:
            return False
    return True


def reachable_hexes(
    start: HexCoord,
    width: int,
    height: int,
    move_range: int,
    blocked: set[HexCoord],
    *,
    flying: bool = False,
) -> set[HexCoord]:
    if move_range <= 0:
        return set()

    if flying:
        return {
            coord
            for q in range(width)
            for r in range(height)
            for coord in [HexCoord(q, r)]
            if coord != start and start.distance_to(coord) <= move_range and coord not in blocked
        }

    visited = {start}
    frontier: deque[tuple[HexCoord, int]] = deque([(start, 0)])
    reachable: set[HexCoord] = set()

    while frontier:
        coord, steps = frontier.popleft()
        if steps == move_range:
            continue
        for neighbor in coord.neighbors():
            if not in_bounds(neighbor, width, height):
                continue
            if neighbor in visited or neighbor in blocked:
                continue
            visited.add(neighbor)
            reachable.add(neighbor)
            frontier.append((neighbor, steps + 1))

    return reachable
