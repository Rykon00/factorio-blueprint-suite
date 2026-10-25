"""Directions and small vector helpers (Factorio 2.x uses 16 directions)."""

from __future__ import annotations


class Direction:
    NORTH = 0
    EAST = 4
    SOUTH = 8
    WEST = 12

    _VEC = {0: (0, -1), 4: (1, 0), 8: (0, 1), 12: (-1, 0)}
    _NAMES = {"north": 0, "n": 0, "east": 4, "e": 4, "south": 8, "s": 8, "west": 12, "w": 12}

    @classmethod
    def vector(cls, d: int) -> tuple[int, int]:
        try:
            return cls._VEC[d % 16]
        except KeyError:
            raise ValueError(f"only cardinal directions supported, got {d}") from None

    @classmethod
    def parse(cls, d: int | str) -> int:
        if isinstance(d, int):
            return d % 16
        return cls._NAMES[d.lower()]

    @staticmethod
    def opposite(d: int) -> int:
        return (d + 8) % 16

    @staticmethod
    def rotate(d: int, by: int) -> int:
        return (d + by) % 16

    @staticmethod
    def name(d: int) -> str:
        return {0: "north", 4: "east", 8: "south", 12: "west"}.get(d % 16, str(d))


def rotate_vec(v: tuple[float, float], direction: int) -> tuple[float, float]:
    """Rotate a vector given for a north-facing entity to ``direction`` (clockwise)."""
    x, y = v
    steps = (direction % 16) // 4
    for _ in range(steps):
        x, y = -y, x
    return (x + 0.0, y + 0.0)
