"""Building blocks shared by several designs."""

from __future__ import annotations

from ..geometry import Direction
from ..model import Blueprint
from ..quality import QUALITIES

N, E, S, W = Direction.NORTH, Direction.EAST, Direction.SOUTH, Direction.WEST
PAIR_SIZE = (7, 9)  # width, height; the pair occupies x..x+6, y..y+8


def recycler_pair(bp: Blueprint, x: int, y: int, item: str, modules: list[str], inserter: str = "bulk-inserter",
                  request_amount: int = 100, tag: str | None = None) -> None:
    """Self-recycling loop for one item that needs no logistic robots inside the loop.

    A requester feeds recycler A; A drops into a chest, an inserter passes the
    non-legendary items on to recycler B, B drops into a second chest and an
    inserter hands them back to A. Items bounce until they turn legendary
    (filter inserters pull them out into passive providers) or are used up
    (each pass keeps 25 %). Only the input and the legendary output use robots.

    Layout (relative to x, y)::

        . . . . . P .      P = passive provider (legendary out)
        . . . i D . .      D = chest, i = inserter D -> A
        R i A A B B .      R = requester, A/B = recyclers (2x4)
        . . A A B B .
        . . A A B B .
        . . A C i B .      C = chest, i = inserter C -> B
        . . . i . . .
        . . . P . . .
    """
    y += 1  # row 0 holds the top legendary output chest
    non_leg = [f"{item}@{q}" for q in QUALITIES[:-1]]
    leg = [f"{item}@{QUALITIES[-1]}"]
    bp.place("requester-chest", x, y + 2, requests=[(f"{item}@{q}", request_amount if q == "normal" else 10) for q in QUALITIES[:-1]], tag=tag)
    bp.place(inserter, x + 1, y + 2, W)                                   # requester -> A
    bp.place("recycler", x + 2, y + 1, S, modules=modules)               # A, drops at (x+3, y+5)
    bp.place("steel-chest", x + 3, y + 5)                                  # C
    bp.place(inserter, x + 4, y + 5, W, filters=non_leg)                  # C -> B
    bp.place("recycler", x + 5, y + 2, N, modules=modules)               # B, drops at (x+5, y+1)
    bp.place("steel-chest", x + 5, y + 1)                                  # D
    bp.place(inserter, x + 4, y + 1, E, filters=non_leg)                  # D -> A
    bp.place(inserter, x + 3, y + 6, N, filters=leg)                      # legendary out of C
    bp.place("passive-provider-chest", x + 3, y + 7, tag=tag)
    bp.place(inserter, x + 5, y, S, filters=leg)                          # legendary out of D
    bp.place("passive-provider-chest", x + 5, y - 1, tag=tag)


def input_station(bp: Blueprint, cell, items: dict[str, int], inserter: str = "bulk-inserter", tag: str = "input",
                  from_bottom: bool = False) -> int:
    """Belt-fed input chests on the right edge of a grid cell.

    The player runs a belt down column ``x1 + 2`` (cell-relative x = 48, free in
    the grid) carrying the raw materials, mixed or not. For every item, ``n``
    filter inserters pull that item (all qualities below legendary) into passive
    providers at ``x1`` so robots only fly short distances. The test variant puts
    an infinity chest on the belt tile instead. Returns the number of rows used.
    """
    x0, y0, x1, y1 = cell.interior()
    row = 0
    for item, n in items.items():
        flt = [f"{item}@{q}" for q in QUALITIES[:-1]]
        for _ in range(n):
            y = (y1 - row) if from_bottom else (y0 + row)
            bp.place("passive-provider-chest", x1, y, tag=tag)
            bp.place(inserter, x1 + 1, y, E, filters=flt, tag=tag)
            bp.place("infinity-chest", x1 + 2, y, tag="test", infinity_items=[(item, 100)])
            row += 1
    return row
