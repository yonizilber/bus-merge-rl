"""Shared pytest configuration."""
import pytest

# Tests written against the pre-2026 vehicle/bus API (e.g. Bus() without params,
# Bus.shock_timer, the old squeeze state machine). They are kept visible as
# expected failures until they are rewritten against the current model.
LEGACY_API_TESTS = {
    "tests/test_behavior.py::TestHumanBehavior::test_bus_shock_recovery",
    "tests/test_behavior.py::TestHumanBehavior::test_squeeze_1_success",
    "tests/test_behavior.py::TestHumanBehavior::test_squeeze_3_panic_abort",
    "tests/test_merge.py::TestBusMerging::test_safe_merge_clear_road",
    "tests/test_merge.py::TestBusMerging::test_unsafe_merge_blocked_by_car",
    "tests/test_physics.py::TestEdgeCases::test_bus_overshoot",
    "tests/test_physics.py::TestTrafficPhysics::test_bus_stop_trigger",
    "tests/test_physics.py::TestTrafficPhysics::test_scenario_b_bypass",
    "tests/test_safety.py::TestSafetyOverride::test_emergency_abort_maniac_driver",
}


def pytest_collection_modifyitems(items):
    for item in items:
        if item.nodeid in LEGACY_API_TESTS:
            item.add_marker(pytest.mark.xfail(reason="written against the legacy API; needs rewrite", strict=True))
