"""Building layout: the facility description every twin reads from.

`data/building_layout.json` is the single source of truth for the 2-floor,
6-room facility. The simulator, the Streamlit dashboard and the Three.js view
all load it, so room geometry cannot drift from room physics.

Invariants are locked by tests/test_building.py — notably that `f1/lab-a`
keeps the exact constants Project 1 was calibrated against.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# data/ sits beside simulator/ at the repo root
DEFAULT_LAYOUT_PATH = Path(__file__).resolve().parent.parent / "data" / "building_layout.json"

HEAT_PER_PERSON_W = 100.0  # matches physics.HEAT_PER_PERSON_W


@dataclass(frozen=True)
class RoomConfig:
    """Static description of one room twin. Immutable: it is configuration,
    not state — a room's dimensions never change at runtime."""

    twin_id: str
    floor: str
    room_id: str
    name: str
    area_m2: float
    height_m: float
    max_occupancy: int
    heat_capacity: float          # J/°C
    base_equipment_w: float       # constant internal load (IT gear, benches)
    insulation_k: float           # W/°C through the envelope
    hvac_max_power_w: float
    base_rpm: float               # nominal fan speed with a clean filter
    occupancy_profile: str        # class_schedule | steady_daytime | bursty | unoccupied
    always_on: bool               # true = AC ignores the "empty room -> off" rule
    solar_gain: float             # inherited from the floor
    neighbours: tuple[str, ...] = ()
    furniture: str = "desks"      # read by the 3D view
    # Per-unit wear character, so rooms fail in DIFFERENT ways. See
    # hvac_health.HVACHealth for what each multiplier does.
    wear: tuple = ()

    @property
    def volume_m3(self) -> float:
        return self.area_m2 * self.height_m

    @property
    def wear_factors(self) -> dict:
        """Wear multipliers as a mapping. Stored as a tuple of pairs so the
        config stays immutable and comparable."""
        return dict(self.wear)

    @property
    def peak_internal_load_w(self) -> float:
        """Worst-case internal heat gain: a full room plus its equipment."""
        return self.max_occupancy * HEAT_PER_PERSON_W + self.base_equipment_w


@dataclass(frozen=True)
class FloorConfig:
    floor_id: str
    name: str
    power_budget_kw: float
    solar_gain: float
    corridor_id: str
    corridor_name: str
    corridor_connects: tuple[str, ...]
    rooms: tuple[RoomConfig, ...]


@dataclass
class BuildingConfig:
    name: str
    power_budget_kw: float
    outdoor_profile: dict
    floors: tuple[FloorConfig, ...]
    _index: dict[str, RoomConfig] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self._index = {r.twin_id: r for f in self.floors for r in f.rooms}

    def room(self, twin_id: str) -> RoomConfig:
        """Look up a room twin. Raises KeyError on an unknown id rather than
        returning None — a typo'd twin_id should fail loudly, not silently
        disable a room."""
        try:
            return self._index[twin_id]
        except KeyError:
            raise KeyError(
                f"unknown twin_id {twin_id!r}; known: {sorted(self._index)}"
            ) from None

    def all_rooms(self) -> list[RoomConfig]:
        """Every room twin, in layout order (floor 1 first)."""
        return [r for f in self.floors for r in f.rooms]

    def floor(self, floor_id: str) -> FloorConfig:
        for f in self.floors:
            if f.floor_id == floor_id:
                return f
        raise KeyError(f"unknown floor_id {floor_id!r}")

    @property
    def corridor_ids(self) -> set[str]:
        return {f.corridor_id for f in self.floors}


def _room_from_json(raw: dict, floor_id: str, solar_gain: float) -> RoomConfig:
    hvac = raw["hvac"]
    return RoomConfig(
        twin_id=f"{floor_id}/{raw['room_id']}",
        floor=floor_id,
        room_id=raw["room_id"],
        name=raw["name"],
        area_m2=float(raw["area_m2"]),
        height_m=float(raw["height_m"]),
        max_occupancy=int(raw["max_occupancy"]),
        heat_capacity=float(raw["heat_capacity_j_per_c"]),
        base_equipment_w=float(raw["base_equipment_w"]),
        insulation_k=float(raw["insulation_k"]),
        hvac_max_power_w=float(hvac["max_power_w"]),
        base_rpm=float(hvac["base_rpm"]),
        occupancy_profile=raw["occupancy_profile"],
        always_on=bool(raw["always_on"]),
        solar_gain=solar_gain,
        neighbours=tuple(raw["neighbours"]),
        furniture=raw.get("furniture", "desks"),
        wear=tuple(sorted(raw.get("wear", {}).items())),
    )


def _validate(building: BuildingConfig) -> None:
    """Fail fast on a malformed layout.

    A dangling or one-way adjacency would silently break thermal coupling
    (heat flowing one direction only) and strand rooms for the occupancy twin,
    so catch it at load time rather than as mystery physics later.
    """
    rooms = building.all_rooms()
    room_ids = {r.twin_id for r in rooms}
    known = room_ids | building.corridor_ids

    if len(room_ids) != len(rooms):
        raise ValueError("duplicate twin_id in layout")

    for room in rooms:
        for neighbour in room.neighbours:
            if neighbour not in known:
                raise ValueError(
                    f"{room.twin_id} lists unknown neighbour {neighbour!r}"
                )
            if neighbour in room_ids:
                back = building.room(neighbour).neighbours
                if room.twin_id not in back:
                    raise ValueError(
                        f"asymmetric adjacency: {room.twin_id} -> {neighbour} "
                        f"is not mirrored back"
                    )
        if f"{room.floor}/corridor" not in room.neighbours:
            raise ValueError(f"{room.twin_id} has no corridor access")


def load_building(path: str | Path | None = None) -> BuildingConfig:
    """Load and validate the facility description."""
    path = Path(path) if path is not None else DEFAULT_LAYOUT_PATH
    with open(path, encoding="utf-8") as fh:
        raw = json.load(fh)

    floors = []
    for f in raw["floors"]:
        corridor = f["corridor"]
        floors.append(
            FloorConfig(
                floor_id=f["floor_id"],
                name=f["name"],
                power_budget_kw=float(f["power_budget_kw"]),
                solar_gain=float(f["solar_gain"]),
                corridor_id=corridor["node_id"],
                corridor_name=corridor["name"],
                corridor_connects=tuple(corridor.get("connects", ())),
                rooms=tuple(
                    _room_from_json(r, f["floor_id"], float(f["solar_gain"]))
                    for r in f["rooms"]
                ),
            )
        )

    b = raw["building"]
    building = BuildingConfig(
        name=b["name"],
        power_budget_kw=float(b["power_budget_kw"]),
        outdoor_profile=b["outdoor"],
        floors=tuple(floors),
    )
    _validate(building)
    return building


# Lets tests and the dashboard find the layout file without duplicating the path.
load_building.default_path = lambda: DEFAULT_LAYOUT_PATH
