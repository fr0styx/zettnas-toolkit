"""SET-15 (Power B5): a UPS that reports a load but no capacity gets no invented watt figure."""

import inspect

from backend.hardware import ups


def test_no_generic_capacity_guess():
    src = inspect.getsource(ups)
    assert "nom_power = 900.0" not in src
    assert "effective_out_v <= 60.0" not in src
