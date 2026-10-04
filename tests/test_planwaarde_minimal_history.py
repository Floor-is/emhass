#!/usr/bin/env python
"""The load-forecast history must be fetched without attributes.

On a load sensor with ~50k states/day, the full response (attributes per state) took 29-58 s for
the two days the naive forecast needs; minimal_response + no_attributes took 6-15 s with the same
15-minute means (measured 4-10-2026 against a live Home Assistant). Above the caller's HTTP
timeout the request was cancelled without an error in the log.
"""

import asyncio
import logging
import types
import unittest
from unittest import mock
from zoneinfo import ZoneInfo

import pandas as pd

from emhass.forecast import Forecast
from emhass.retrieve_hass import RetrieveHass


class TestMinimalHistory(unittest.TestCase):
    def rh(self):
        return RetrieveHass(
            "http://ha.local:8123/", "token", pd.Timedelta(minutes=15),
            ZoneInfo("Europe/Amsterdam"), "{}", {}, logging.getLogger("t"),
        )

    def test_minimal_url_drops_attributes(self):
        url = self.rh()._build_history_url(
            pd.Timestamp("2026-10-03", tz="UTC"), "sensor.load", "empty", True, False
        )
        self.assertIn("&minimal_response", url)
        self.assertIn("&no_attributes", url)

    def test_full_url_unchanged(self):
        # null case: without minimal_response the URL is the upstream one
        url = self.rh()._build_history_url(
            pd.Timestamp("2026-10-03", tz="UTC"), "sensor.load", "empty", False, False
        )
        self.assertEqual(
            url, "http://ha.local:8123/api/history/period/2026-10-03T00:00:00Z?filter_entity_id=sensor.load"
        )

    def test_load_forecast_asks_for_minimal_history(self):
        fake = types.SimpleNamespace(
            var_load="sensor.load", time_zone=ZoneInfo("Europe/Amsterdam"),
            retrieve_hass_conf={"hass_url": "http://ha.local:8123/", "long_lived_token": "t"},
            freq=pd.Timedelta(minutes=15), params="{}", emhass_conf={},
            logger=logging.getLogger("t"), get_data_from_file=False,
        )
        get_data = mock.AsyncMock(return_value=False)
        with mock.patch.object(RetrieveHass, "get_data", get_data):
            asyncio.run(Forecast._prepare_hass_load_data(fake, 1, "naive"))
        get_data.assert_awaited_once()
        self.assertTrue(get_data.await_args.kwargs.get("minimal_response"))


if __name__ == "__main__":
    unittest.main()
