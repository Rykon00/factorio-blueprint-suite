"""Til's "City Block 2.0" grid (50x50 cells, roboports + star-shaped power).

Every larger design is placed inside one (or more) of these cells. The grid
blueprint uses absolute snapping 50x50 with position-relative-to-grid 25/25 and
puts a roboport on every cell corner, 4 medium poles around it and 4 big poles
9 tiles out along the axes. Designs keep those corner nodes free and normally
build in the interior tiles 3..46 of a cell.
"""

from __future__ import annotations

from dataclasses import dataclass

from .codec import decode
from .model import Blueprint

CITY_BLOCK_2 = (
    "0eNqtl11vmzAUhv9K5GtTYRvzkbttmvYDKu2mqioSvMwaAWacblXFf58/CFgtToLXq7zB5zx+Tc45gVewq0+sE7yRYPsKKtbvBe8kbxuwBd/RHdp8qipWbe5lKTb3P8tO6a8120vB92W9+SZ4BSDom7KLZBsd9FeF+Qu2NIbgRX8MEJS7vq1PkkU6ruPNAWylODEIurbneq9IsLqU/Jm9gWBqIJgqCN+3TQ+2D6+g54emrHVIUx6Z8inaXdu1QgId1lRMZw5wIXDHDxEb3UddWzMngwyPELBGKkPM7mO+vDw1p+OOCbBF0I+ZjzI6t6ePikH7eAPCa0D0EolMpCOr+Ol4DRbhO3tHtVgCJiuB13h0JS/JrgDTlUB6zWG25seICsOKl0A5fFeOnqrQLSHY7xPr5dMPXksmer3eq635ucbHokTD49JexRrTFzyjeA0oQRdI6Ibj0486P1rXQpfuQHALeeoJhbaQjxfcQj5gcAv5gNn6wbg4zVAeMBiXScV6SwlanNVxgCcPCoWWmv5JF4k4sNa8QBJabF5iElptXiINmNh0sflxevPMpv8/tHC2fmp7fOcBY9uDKm6f2x9wD0gcMLiXnZPgdqKeQUZC28kLDG4nLzG4nbxEun5U0uWH0TRgVGqUeu7+w4V56H5AkEIC6SM0KjEKK0UnlRpFplWtskkhm6yWYDEpZCPplK2VevaZpKWnWuJZ2thsphZzWjFj9ZUzQqefExFxYoy2NlHiaOrEG51bnTraOLCn0Zcgthb0Jaj+VGZtvetliImjx9uInBij6ayJ5ehliLNZkzGeOByj81mTcS99LhI7eoynDj9zcjOHn88cjTjnEjTHWG09E+xo4sQbPZZIctaqwLhkR12Y08suBHW5Y+rlEHxRRbz5XLf7Xxt8F6uFZzXXTKHSFBc0wUmRF7Qg+TD8A5ntwdA="
)
CELL = 50
INTERIOR = (3, 46)  # first and last usable tile (inclusive) inside a cell, both axes


@dataclass
class Cell:
    cx: int  # cell index (0 = the cell whose top-left roboport sits at (0, 0))
    cy: int

    @property
    def x0(self) -> int:
        return self.cx * CELL

    @property
    def y0(self) -> int:
        return self.cy * CELL

    def interior(self) -> tuple[int, int, int, int]:
        """(x_min, y_min, x_max, y_max) inclusive tile bounds of the usable interior."""
        return (self.x0 + INTERIOR[0], self.y0 + INTERIOR[0], self.x0 + INTERIOR[1], self.y0 + INTERIOR[1])


def grid_entities():
    return decode(CITY_BLOCK_2)["blueprint"]["entities"]


def add_grid(bp: Blueprint, cells: list[Cell], tag: str = "grid") -> list:
    """Add the grid's corner nodes for ``cells`` (shared corners are added once).

    Grid entities are tagged so a design can be exported with or without them;
    including them makes the design snap to the same 50x50 lattice. Copper wires
    are copied from the grid blueprint.
    """
    data = decode(CITY_BLOCK_2)["blueprint"]
    added: dict[tuple, object] = {}
    wires = set()
    for c in cells:
        local = {}
        for e in data["entities"]:
            x, y = e["position"]["x"] + c.x0, e["position"]["y"] + c.y0
            key = (e["name"], x, y)
            if key not in added:
                added[key] = bp.place_center(e["name"], x, y, e.get("direction", 0), tag=tag)
            local[e["entity_number"]] = added[key]
        for a, ca, b, cb in data.get("wires", []):
            ea, eb = local[a], local[b]
            k = tuple(sorted((ea.number, eb.number))) + (ca, cb)
            if k not in wires:
                wires.add(k)
                bp.wires.append([ea.number, ca, eb.number, cb])
    return list(added.values())


def snap_to_grid(bp: Blueprint) -> None:
    """Give the blueprint the grid's absolute snapping so it lines up with the placed grid."""
    bp.extra["snap-to-grid"] = {"x": CELL, "y": CELL}
    bp.extra["absolute-snapping"] = True
    bp.extra["position-relative-to-grid"] = {"x": CELL // 2, "y": CELL // 2}
