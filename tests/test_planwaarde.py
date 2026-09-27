#!/usr/bin/env python
"""Tests for the parameters added by the `planwaarde` fork.

- battery_terminal_value: a value for the end-of-horizon energy instead of a fixed end state.
- deferrable_load_value / deferrable_load_energy_max: requirement <= E <= max, value per kWh.

Synthetic and self-contained (same builder as test_multi_battery_optimization.py).
Expected numbers are derived beforehand, not copied from a run.
"""

import logging
import pathlib
import unittest

import pandas as pd

from emhass.command_line import OptimizationCache
from emhass.optimization import Optimization

TEST_ROOT = pathlib.Path(__file__).resolve().parents[1]
N = 48  # 24 hours in 30-minute steps
DT = 0.5  # hours per step
ETA_DIS, ETA_CHG, W_DIS = 0.939, 0.946, 0.064
CAP = 48000
SOC_MIN = 0.08


def build(optim_overrides=None, def_load=None):
    logger = logging.getLogger("planwaarde_test")
    logger.handlers = []
    logger.addHandler(logging.NullHandler())
    retrieve_hass_conf = {
        "optimization_time_step": pd.to_timedelta(30, "minutes"),
        "time_zone": "Europe/Amsterdam",
        "sensor_power_photovoltaics": "pv",
        "sensor_power_load_no_var_loads": "load",
    }
    optim_conf = {
        "delta_forecast_daily": pd.Timedelta(hours=24),
        "num_threads": 0,
        "set_use_battery": True,
        "set_use_pv": True,
        "set_total_pv_sell": False,
        "set_nocharge_from_grid": False,
        "set_nodischarge_to_grid": False,
        "set_battery_dynamic": False,
        "set_battery_first_priority": False,
        "battery_dynamic_max": 0.9,
        "battery_dynamic_min": -0.9,
        "weight_battery_discharge": W_DIS,
        "weight_battery_charge": 0.0,
        "battery_soc_deficit_threshold": 0.0,
        "battery_soc_deficit_cost": 0.0,
        "battery_soc_surplus_threshold": 1.0,
        "battery_soc_surplus_cost": 0.0,
        "number_of_deferrable_loads": 0,
        "nominal_power_of_deferrable_loads": [],
        "treat_deferrable_load_as_semi_cont": [],
        "set_deferrable_load_single_constant": [],
        "set_deferrable_startup_penalty": [],
        "operating_hours_of_each_deferrable_load": [],
        "start_timesteps_of_each_deferrable_load": [],
        "end_timesteps_of_each_deferrable_load": [],
        "lp_solver_timeout": 60,
        "lp_solver_mip_rel_gap": 0,
    }
    if def_load:
        optim_conf.update(
            {
                "number_of_deferrable_loads": 1,
                "nominal_power_of_deferrable_loads": [def_load["p"]],
                "treat_deferrable_load_as_semi_cont": [False],
                "set_deferrable_load_single_constant": [False],
                "set_deferrable_startup_penalty": [False],
                "operating_hours_of_each_deferrable_load": [def_load["hours"]],
                "start_timesteps_of_each_deferrable_load": [0],
                "end_timesteps_of_each_deferrable_load": [0],
            }
        )
    if optim_overrides:
        optim_conf.update(optim_overrides)
    plant_conf = {
        "inverter_is_hybrid": False,
        "compute_curtailment": False,
        "maximum_power_from_grid": 50000,
        "maximum_power_to_grid": 50000,
        "battery_discharge_power_max": 12000,
        "battery_charge_power_max": 12000,
        "battery_minimum_state_of_charge": SOC_MIN,
        "battery_maximum_state_of_charge": 1.0,
        "battery_target_state_of_charge": 0.5,
        "battery_nominal_energy_capacity": CAP,
        "battery_discharge_efficiency": ETA_DIS,
        "battery_charge_efficiency": ETA_CHG,
        "battery_stress_cost": 0.0,
        "battery_stress_segments": 10,
    }
    emhass_conf = {"root_path": TEST_ROOT / "src" / "emhass", "data_path": TEST_ROOT / "data"}
    return Optimization(
        retrieve_hass_conf,
        optim_conf,
        plant_conf,
        "unit_load_cost",
        "unit_prod_price",
        "profit",
        emhass_conf,
        logger,
    )


def inputs(lc, pp, pv=0.0, load=0.0):
    index = pd.date_range("2026-09-28", periods=N, freq="30min", tz="Europe/Amsterdam")
    as_list = lambda x: x if isinstance(x, list) else [x] * N  # noqa: E731
    df = pd.DataFrame(index=index)
    df["unit_load_cost"] = as_list(lc)
    df["unit_prod_price"] = as_list(pp)
    return df, pd.Series(as_list(pv), index=index), pd.Series(as_list(load), index=index)


def solve(opt, df, p_pv, p_load, soc_init):
    res = opt.perform_dayahead_forecast_optim(df, p_pv, p_load, soc_init=soc_init)
    assert opt.optim_status in ("Optimal", "Optimal (Relaxed)"), opt.optim_status
    return res


def ev_kwh(res):
    return float(res["P_deferrable0"].sum()) * DT / 1000


class TestTerminalValue(unittest.TestCase):
    """battery_terminal_value. Flat prices: import 0.40, export 0.35, no PV/load, battery full.
    One AC kWh exported earns 0.35 - W_DIS and costs v/ETA_DIS of terminal value.
    Break-even v* = (0.35 - 0.064) * 0.939 = 0.2686."""

    V_STAR = (0.35 - W_DIS) * ETA_DIS

    def end_soc(self, overrides):
        df, pv, load = inputs(0.40, 0.35)
        res = solve(build(overrides), df, pv, load, soc_init=0.995)
        return float(res["SOC_opt"].iloc[-1])

    def test_without_parameter_ends_at_soc_init(self):
        # Upstream behaviour: soc_final falls back to soc_init (100x penalty).
        self.assertAlmostEqual(self.end_soc(None), 0.995, delta=0.005)

    def test_break_even(self):
        self.assertAlmostEqual(self.V_STAR, 0.2686, delta=0.0005)
        self.assertLess(self.end_soc({"battery_terminal_value": 0.26}), SOC_MIN + 0.01)
        self.assertGreater(self.end_soc({"battery_terminal_value": 0.28}), 0.99)

    def test_zero_means_down_to_the_minimum(self):
        self.assertLess(self.end_soc({"battery_terminal_value": 0.0}), SOC_MIN + 0.01)

    def test_list_per_battery(self):
        self.assertLess(self.end_soc({"battery_terminal_value": [0.26]}), SOC_MIN + 0.01)


class TestLoadValue(unittest.TestCase):
    """deferrable_load_value + deferrable_load_energy_max. Load 11 kW, floor 10 kWh,
    max 40 kWh, value 0.54. Battery at its minimum and terminal value 0, so it can only
    contribute through cheap imports; export price 0.05."""

    P = 11000
    FLOOR, MAX, V = 10.0, 40.0, 0.54

    def kwh(self, lc, **extra):
        df, pv, load = inputs(lc, 0.05, load=300.0)
        conf = {
            "battery_terminal_value": 0.0,
            "deferrable_load_value": [self.V],
            "deferrable_load_energy_max": [self.MAX * 1000],
        }
        conf.update(extra)
        opt = build(conf, def_load={"p": self.P, "hours": self.FLOOR * 1000 / self.P})
        return ev_kwh(solve(opt, df, pv, load, soc_init=SOC_MIN))

    def test_expensive_only_the_floor(self):
        self.assertAlmostEqual(self.kwh(0.60), self.FLOOR, delta=0.1)

    def test_cheap_up_to_the_maximum(self):
        self.assertAlmostEqual(self.kwh(0.30), self.MAX, delta=0.1)

    def test_mixed_floor_plus_cheap_steps(self):
        # 4 steps of 30 min at 0.30 => 4 * 11 * 0.5 = 22 kWh directly; the battery can also
        # charge there for later (0.30/(0.946*0.939) + 0.064 ~= 0.40 < 0.54).
        lc = [0.30 if 20 <= i < 24 else 0.60 for i in range(N)]
        e = self.kwh(lc)
        self.assertGreater(e, 22.0 - 0.1)
        self.assertLessEqual(e, self.MAX + 0.1)

    def test_without_value_the_requirement_is_enough(self):
        # energy_max without a value: the floor suffices, anything more only costs money.
        self.assertAlmostEqual(self.kwh(0.30, deferrable_load_value=[0.0]), self.FLOOR, delta=0.1)


class TestMaximumOnly(unittest.TestCase):
    """A load without a requirement (hours 0) but with energy_max stays active."""

    def kwh(self, v):
        df, pv, load = inputs(0.30, 0.05)
        opt = build(
            {
                "battery_terminal_value": 0.0,
                "deferrable_load_value": [v],
                "deferrable_load_energy_max": [30000],
            },
            def_load={"p": 11000, "hours": 0},
        )
        return ev_kwh(solve(opt, df, pv, load, soc_init=SOC_MIN))

    def test_value_above_price_fills_to_max(self):
        self.assertAlmostEqual(self.kwh(0.60), 30.0, delta=0.1)

    def test_value_below_price_charges_nothing(self):
        self.assertLess(self.kwh(0.20), 0.1)


class TestWithoutParameters(unittest.TestCase):
    """Without the new keys the requirement is an equality, as upstream."""

    def test_requirement_is_equality(self):
        df, pv, load = inputs(0.30, 0.05)
        opt = build(None, def_load={"p": 11000, "hours": 1.0})
        self.assertAlmostEqual(ev_kwh(solve(opt, df, pv, load, soc_init=0.5)), 11.0, delta=0.1)


class TestCache(unittest.TestCase):
    """The new parameters are runtime keys: a different value gives a cache HIT, and the
    second solve on the same object uses the new value (as command_line.py does:
    replace opt.optim_conf and solve again)."""

    def test_cache_hit_with_new_values(self):
        df, pv, load = inputs(0.40, 0.35)
        opt = build({"battery_terminal_value": 0.28})
        first = float(solve(opt, df, pv, load, 0.995)["SOC_opt"].iloc[-1])
        conf2 = dict(opt.optim_conf, battery_terminal_value=0.26)
        k1 = OptimizationCache._compute_cache_key(
            opt.optim_conf, opt.plant_conf, "profit", opt.retrieve_hass_conf, N
        )
        k2 = OptimizationCache._compute_cache_key(
            conf2, opt.plant_conf, "profit", opt.retrieve_hass_conf, N
        )
        self.assertEqual(k1, k2, "a different parameter value must not change the cache key")
        opt.optim_conf = conf2
        second = float(solve(opt, df, pv, load, 0.995)["SOC_opt"].iloc[-1])
        self.assertGreater(first, 0.99)
        self.assertLess(second, SOC_MIN + 0.01)
        # and back to upstream on the same object: key removed => end state = soc_init
        opt.optim_conf = {k: v for k, v in conf2.items() if k != "battery_terminal_value"}
        third = float(solve(opt, df, pv, load, 0.995)["SOC_opt"].iloc[-1])
        self.assertAlmostEqual(third, 0.995, delta=0.005)

    def test_cache_hit_load_parameters(self):
        df, pv, load = inputs(0.30, 0.05)
        opt = build(
            {
                "battery_terminal_value": 0.0,
                "deferrable_load_value": [0.60],
                "deferrable_load_energy_max": [30000],
            },
            def_load={"p": 11000, "hours": 0},
        )
        self.assertAlmostEqual(ev_kwh(solve(opt, df, pv, load, SOC_MIN)), 30.0, delta=0.1)
        opt.optim_conf = dict(opt.optim_conf, deferrable_load_value=[0.20])
        self.assertLess(ev_kwh(solve(opt, df, pv, load, SOC_MIN)), 0.1)
        opt.optim_conf = dict(
            opt.optim_conf, deferrable_load_value=[0.60], deferrable_load_energy_max=[20000]
        )
        self.assertAlmostEqual(ev_kwh(solve(opt, df, pv, load, SOC_MIN)), 20.0, delta=0.1)


class TestBounds(unittest.TestCase):
    """Floor = requirement (operating_hours * P), max = energy_max, value = value."""

    def kwh(self, lc, req_kwh, emax_kwh, v, window_hours=None, extra=None):
        df, pv, load = inputs(lc, 0.05)
        conf = {
            "battery_terminal_value": 0.0,
            "deferrable_load_value": [v],
            "deferrable_load_energy_max": [emax_kwh * 1000],
        }
        if window_hours:
            conf["end_timesteps_of_each_deferrable_load"] = [int(window_hours / DT)]
        conf.update(extra or {})
        opt = build(conf, def_load={"p": 11000, "hours": req_kwh * 1000 / 11000})
        res = solve(opt, df, pv, load, SOC_MIN)
        return ev_kwh(res), res

    def test_min_equals_max_is_the_old_equality(self):
        e, _ = self.kwh(0.30, 15.0, 15.0, 0.60)
        self.assertAlmostEqual(e, 15.0, delta=0.1)

    def test_requirement_wins_when_above_the_maximum(self):
        # maximum = max(configured maximum, calendar requirement)
        e, _ = self.kwh(0.60, 30.0, 20.0, 0.54)
        self.assertAlmostEqual(e, 30.0, delta=0.1)

    def test_unreachable_requirement_gives_shortfall_not_infeasible(self):
        # 2 h * 11 kW = 22 kWh possible, 50 requested => 22 charged, 28 kWh shortfall reported.
        e, res = self.kwh(0.30, 50.0, 60.0, 0.54, window_hours=2)
        self.assertAlmostEqual(e, 22.0, delta=0.1)
        self.assertAlmostEqual(float(res["deferrable0_shortfall_wh"].iloc[0]), 28000, delta=100)

    def test_reachable_requirement_gives_no_shortfall(self):
        _, res = self.kwh(0.60, 10.0, 40.0, 0.54)
        self.assertEqual(float(res["deferrable0_shortfall_wh"].iloc[0]), 0.0)

    def test_without_parameters_no_shortfall_column(self):
        df, pv, load = inputs(0.30, 0.05)
        res = solve(build(None, def_load={"p": 11000, "hours": 1.0}), df, pv, load, 0.5)
        self.assertNotIn("deferrable0_shortfall_wh", res.columns)

    def test_price_equal_to_value_charges_only_the_floor(self):
        # tie-break via the value: v = 0.539 against an import price of exactly 0.54
        e, _ = self.kwh(0.54, 10.0, 40.0, 0.539)
        self.assertAlmostEqual(e, 10.0, delta=0.1)

    def test_negative_prices(self):
        lc = [-0.05 if 10 <= i < 14 else 0.60 for i in range(N)]
        e, res = self.kwh(lc, 10.0, 40.0, 0.54)
        self.assertGreaterEqual(e, 10.0 - 0.1)
        self.assertLessEqual(e, 40.0 + 0.1)
        self.assertEqual(float(res["deferrable0_shortfall_wh"].iloc[0]), 0.0)
        # full power during the negative-price steps
        self.assertTrue((res["P_deferrable0"].iloc[10:14] > 10999).all())

    def test_zero_or_at_least_4_1_kw(self):
        # Charging at 0 or 4.1-11 kW (minimum_power, semi_cont off).
        # Rising price, floor = max = 12 kWh: without a minimum that becomes 11 + 1 kWh,
        # i.e. 2 kW in the third step. With the minimum no step may lie between 0 and 4.1 kW.
        lc = [0.60 + 0.001 * i for i in range(N)]
        e, res = self.kwh(lc, 12.0, 12.0, 0.0, extra={"minimum_power_of_deferrable_loads": [4100]})
        p = res["P_deferrable0"]
        self.assertTrue(((p < 1) | (p > 4100 - 1)).all(), p[(p >= 1) & (p <= 4099)].tolist())
        self.assertAlmostEqual(e, 12.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
