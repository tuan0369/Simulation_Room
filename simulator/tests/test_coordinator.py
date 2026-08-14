from coordinator import RoomDemand, coordinate


def demand(room_id, request, occupancy, temp, setpoint=24.0, enabled=True):
    return RoomDemand(
        room_id=room_id,
        requested_airflow_m3_s=request,
        occupancy=occupancy,
        temperature_c=temp,
        setpoint_c=setpoint,
        enabled=enabled,
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


def test_hotter_occupied_room_wins_a_comfort_tie():
    result = coordinate(
        [
            demand("room1", 0.1, occupancy=4, temp=26.0),
            demand("room2", 0.1, occupancy=4, temp=28.0),
        ],
        available_airflow_m3_s=0.1,
    )
    room1, room2 = result.decisions
    assert room2.granted_airflow_m3_s == 0.1
    assert room1.granted_airflow_m3_s == 0.0


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
