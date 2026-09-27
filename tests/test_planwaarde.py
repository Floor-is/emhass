#!/usr/bin/env python
"""Tests voor de PLANWAARDE-knoppen van deze fork.

- battery_final_value: waarde van de eindstand in plaats van een vaste eindstand.
- deferrable_load_value / deferrable_load_energy_max: eis <= E <= max, waarde per kWh.

Synthetisch en zelfstandig (zelfde bouwer als test_multi_battery_optimization.py).
Verwachte getallen zijn vooraf afgeleid, niet na afloop overgenomen.
"""

import logging
import pathlib
import unittest

import pandas as pd

from emhass.optimization import Optimization

TEST_ROOT = pathlib.Path(__file__).resolve().parents[1]
N = 48  # 24 uur in stappen van 30 minuten
DT = 0.5  # uur per stap
ETA_DIS, ETA_CHG, W_DIS = 0.939, 0.946, 0.064
CAP = 48000
SOC_MIN = 0.08


def bouw(optim_overrides=None, def_load=None):
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
                "operating_hours_of_each_deferrable_load": [def_load["uren"]],
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


def invoer(lc, pp, pv=0.0, load=0.0):
    index = pd.date_range("2026-09-28", periods=N, freq="30min", tz="Europe/Amsterdam")
    lijst = lambda x: x if isinstance(x, list) else [x] * N  # noqa: E731
    df = pd.DataFrame(index=index)
    df["unit_load_cost"] = lijst(lc)
    df["unit_prod_price"] = lijst(pp)
    return df, pd.Series(lijst(pv), index=index), pd.Series(lijst(load), index=index)


def draai(opt, df, p_pv, p_load, soc_init):
    res = opt.perform_dayahead_forecast_optim(df, p_pv, p_load, soc_init=soc_init)
    assert opt.optim_status in ("Optimal", "Optimal (Relaxed)"), opt.optim_status
    return res


def ev_kwh(res):
    return float(res["P_deferrable0"].sum()) * DT / 1000


class TestEindwaarde(unittest.TestCase):
    """battery_final_value. Vlak: inkoop 0,40, teruglever 0,35, geen PV/last, accu vol.
    Een AC-kWh naar het net levert 0,35 − W_DIS op en kost v/ETA_DIS aan eindwaarde.
    Omslag v* = (0,35 − 0,064) × 0,939 = 0,2686."""

    V_STER = (0.35 - W_DIS) * ETA_DIS

    def eind(self, overrides):
        df, pv, load = invoer(0.40, 0.35)
        res = draai(bouw(overrides), df, pv, load, soc_init=0.995)
        return float(res["SOC_opt"].iloc[-1])

    def test_zonder_knop_eindigt_op_soc_init(self):
        # Gedrag 0.18.3: soc_final valt terug op soc_init (boete 100x).
        self.assertAlmostEqual(self.eind(None), 0.995, delta=0.005)

    def test_omslagpunt(self):
        self.assertAlmostEqual(self.V_STER, 0.2686, delta=0.0005)
        self.assertLess(self.eind({"battery_final_value": 0.26}), SOC_MIN + 0.01)
        self.assertGreater(self.eind({"battery_final_value": 0.28}), 0.99)

    def test_nul_betekent_tot_de_vloer(self):
        self.assertLess(self.eind({"battery_final_value": 0.0}), SOC_MIN + 0.01)

    def test_lijst_per_accu(self):
        self.assertLess(self.eind({"battery_final_value": [0.26]}), SOC_MIN + 0.01)


class TestWaardeInDeLoad(unittest.TestCase):
    """deferrable_load_value + deferrable_load_energy_max. Load 11 kW, vloer 10 kWh,
    max 40 kWh, waarde 0,54. Accu op de vloer en eindwaarde 0, zodat hij alleen via
    goedkope inkoop kan bijdragen; teruglever 0,05."""

    P = 11000
    VLOER, MAX, V = 10.0, 40.0, 0.54

    def kwh(self, lc, **extra):
        df, pv, load = invoer(lc, 0.05, load=300.0)
        conf = {
            "battery_final_value": 0.0,
            "deferrable_load_value": [self.V],
            "deferrable_load_energy_max": [self.MAX * 1000],
        }
        conf.update(extra)
        opt = bouw(conf, def_load={"p": self.P, "uren": self.VLOER * 1000 / self.P})
        return ev_kwh(draai(opt, df, pv, load, soc_init=SOC_MIN))

    def test_duur_alleen_de_vloer(self):
        self.assertAlmostEqual(self.kwh(0.60), self.VLOER, delta=0.1)

    def test_goedkoop_tot_het_maximum(self):
        self.assertAlmostEqual(self.kwh(0.30), self.MAX, delta=0.1)

    def test_gemengd_vloer_plus_goedkope_stappen(self):
        # 4 stappen van 30 min op 0,30 ⇒ 4 × 11 × 0,5 = 22 kWh direct; de accu kan daar
        # ook laden voor later (0,30/(0,946·0,939) + 0,064 ≈ 0,40 < 0,54).
        lc = [0.30 if 20 <= i < 24 else 0.60 for i in range(N)]
        e = self.kwh(lc)
        self.assertGreater(e, 22.0 - 0.1)
        self.assertLessEqual(e, self.MAX + 0.1)

    def test_zonder_waarde_blijft_eis_een_gelijkheid(self):
        # energy_max zonder value: de vloer is genoeg, meer kost alleen geld.
        self.assertAlmostEqual(self.kwh(0.30, deferrable_load_value=[0.0]), self.VLOER, delta=0.1)


class TestAlleenMaximum(unittest.TestCase):
    """Een load zonder eis (uren 0) maar met energy_max blijft actief."""

    def kwh(self, v):
        df, pv, load = invoer(0.30, 0.05)
        opt = bouw(
            {
                "battery_final_value": 0.0,
                "deferrable_load_value": [v],
                "deferrable_load_energy_max": [30000],
            },
            def_load={"p": 11000, "uren": 0},
        )
        return ev_kwh(draai(opt, df, pv, load, soc_init=SOC_MIN))

    def test_waarde_boven_prijs_vult_tot_max(self):
        self.assertAlmostEqual(self.kwh(0.60), 30.0, delta=0.1)

    def test_waarde_onder_prijs_laadt_niets(self):
        self.assertLess(self.kwh(0.20), 0.1)


class TestZonderKnoppen(unittest.TestCase):
    """Zonder de nieuwe sleutels is de eis een gelijkheid, zoals in 0.18.3."""

    def test_eis_is_gelijkheid(self):
        df, pv, load = invoer(0.30, 0.05)
        opt = bouw(None, def_load={"p": 11000, "uren": 1.0})
        self.assertAlmostEqual(ev_kwh(draai(opt, df, pv, load, soc_init=0.5)), 11.0, delta=0.1)


if __name__ == "__main__":
    unittest.main()
