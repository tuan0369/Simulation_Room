import pytest

from coordinator import MAX_COMFORT_DEBT_C_S, RoomDemand, coordinate, update_comfort_debt


def demand(
    room_id,
    request,
    occupancy,
    temp,
    setpoint=24.0,
    enabled=True,
    comfort_debt=0.0,
    limited_service=0.0,
):
    return RoomDemand(
        room_id=room_id,
        requested_airflow_m3_s=request,
        occupancy=occupancy,
        temperature_c=temp,
        setpoint_c=setpoint,
        enabled=enabled,
        comfort_debt_c_s=comfort_debt,
        limited_service_s=limited_service,
    )


def test_occupied_room_is_prioritized_when_capacity_is_constrained():
    result = coordinate(
        [
            demand("room1", 0.12, occupancy=18, temp=27.0),
            demand("room2", 0.12, occupancy=0, temp=27.0),
        ],
        available_airflow_m3_s=0.12,
    )
    first, second = result.decisions
    assert first.granted_airflow_m3_s == 0.12
    assert second.granted_airflow_m3_s == 0.0
    assert "occupied" in first.reason_codes
    assert "capacity_limited" in second.reason_codes


def test_hotter_occupied_room_wins_before_debt_recovery():
    result = coordinate(
        [
            demand("room1", 0.1, occupancy=4, temp=26.0, comfort_debt=100.0),
            demand("room2", 0.1, occupancy=4, temp=28.0),
        ],
        available_airflow_m3_s=0.1,
    )
    room1, room2 = result.decisions
    assert room2.granted_airflow_m3_s == 0.1
    assert room1.granted_airflow_m3_s == 0.0


def test_symmetric_contention_deterministically_avoids_persistent_starvation():
    rooms = [
        demand("room1", 0.1, occupancy=4, temp=28.0),
        demand("room2", 0.1, occupancy=4, temp=28.0),
    ]
    served = {"room1": 0, "room2": 0}

    for _ in range(6):
        result = coordinate(rooms, available_airflow_m3_s=0.1)
        grants = {item.room_id: item.granted_airflow_m3_s for item in result.decisions}
        served[max(grants, key=grants.get)] += 1
        rooms = [
            demand(
                room.room_id,
                room.requested_airflow_m3_s,
                room.occupancy,
                room.temperature_c,
                room.setpoint_c,
                room.enabled,
                *update_comfort_debt(room, grants[room.room_id], dt=10.0),
            )
            for room in rooms
        ]

    assert served == {"room1": 3, "room2": 3}


def test_full_requests_are_granted_without_contention():
    result = coordinate(
        [
            demand("room1", 0.05, occupancy=4, temp=26.0),
            demand("room2", 0.04, occupancy=1, temp=25.0),
        ],
        available_airflow_m3_s=0.2,
    )
    assert result.constrained is False
    assert sum(item.granted_airflow_m3_s for item in result.decisions) == 0.09
    assert all("full_request_granted" in item.reason_codes for item in result.decisions)


def test_disabled_room_receives_no_airflow():
    result = coordinate(
        [demand("room1", 0.12, occupancy=10, temp=27.0, enabled=False)],
        available_airflow_m3_s=0.2,
    )
    decision = result.decisions[0]
    assert decision.granted_airflow_m3_s == 0.0
    assert "zone_disabled" in decision.reason_codes


def test_comfort_debt_breaks_equal_room_tie_without_breaking_capacity():
    result = coordinate(
        [
            demand("room1", 0.12, occupancy=4, temp=27.0),
            demand("room2", 0.12, occupancy=4, temp=27.0, comfort_debt=30.0),
        ],
        available_airflow_m3_s=0.12,
    )
    room1, room2 = result.decisions
    assert room2.granted_airflow_m3_s == pytest.approx(0.12)
    assert room1.granted_airflow_m3_s == 0.0
    assert "comfort_debt_priority" in room2.reason_codes
    assert sum(item.granted_airflow_m3_s for item in result.decisions) <= 0.12


def test_comfort_debt_accumulates_is_bounded_and_recovers():
    room = demand("room1", 0.1, occupancy=4, temp=28.0)
    debt, limited = update_comfort_debt(room, granted_airflow_m3_s=0.0, dt=10.0)
    assert debt > 0.0
    assert limited == 10.0

    saturated = demand(
        "room1",
        0.1,
        occupancy=4,
        temp=28.0,
        comfort_debt=MAX_COMFORT_DEBT_C_S,
        limited_service=limited,
    )
    bounded, _ = update_comfort_debt(saturated, granted_airflow_m3_s=0.0, dt=10.0)
    assert bounded == MAX_COMFORT_DEBT_C_S
    recovered, limited = update_comfort_debt(
        saturated, granted_airflow_m3_s=0.1, dt=10.0
    )
    assert recovered < MAX_COMFORT_DEBT_C_S
    assert limited == 0.0


def test_nonfinite_coordinator_input_is_rejected():
    with pytest.raises(ValueError):
        coordinate([demand("room1", float("nan"), 1, 26.0)], 0.1)
