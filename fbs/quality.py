"""Quality roll math (matches LuaQualityPrototype::get_roll_chances in 2.1)."""

from __future__ import annotations

QUALITIES = ["normal", "uncommon", "rare", "epic", "legendary"]


def roll(from_level: int, chance: float, levels: int = 5, next_probability: float = 0.1) -> list[float]:
    """Probability distribution of the result quality level.

    With probability ``chance`` the result is one level better; every further
    level is reached with ``next_probability`` (0.1). The top level absorbs
    the remainder.
    """
    out = [0.0] * levels
    if from_level >= levels - 1:
        out[levels - 1] = 1.0
        return out
    chance = max(0.0, min(1.0, chance))
    out[from_level] = 1.0 - chance
    p = chance
    for lvl in range(from_level + 1, levels):
        if lvl == levels - 1:
            out[lvl] += p
        else:
            out[lvl] += p * (1.0 - next_probability)
            p *= next_probability
    return out
