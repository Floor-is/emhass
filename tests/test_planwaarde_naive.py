#!/usr/bin/env python
"""The naive load forecast must be aligned on TIME, whatever the moment the optimisation runs.

Expected: yhat[L] = history[L - 24 h] (history labels are left-closed 15-minute means, as
RetrieveHass resamples them). Upstream relabelled the last N rows by position; when the
current, incomplete step was already in the history, the series came out one step early.
Each case varies the run moment and whether that incomplete step is present.
"""

import logging
import types
import unittest
from unittest import mock

import pandas as pd

from emhass import utils
from emhass.forecast import Forecast

TZ = "Europe/Amsterdam"
STEP = pd.Timedelta(minutes=15)


def history(now, with_partial_step):
    """Two days of 15-minute labels up to now; value = minutes since midnight 28-9 (unique)."""
    start = now.floor("15min") - pd.Timedelta(days=2)
    end = now.floor("15min") if with_partial_step else now.floor("15min") - STEP
    idx = pd.date_range(start, end, freq="15min", tz=TZ)
    base = pd.Timestamp("2026-09-28 00:00", tz=TZ)
    return pd.DataFrame({"load": [(t - base) / pd.Timedelta(minutes=1) for t in idx]}, index=idx)


def naive(now, df, days=1):
    with mock.patch.object(utils, "_get_now", return_value=now.tz_convert("UTC")):
        dates = utils.get_forecast_dates(15, days, TZ)
    fake = types.SimpleNamespace(forecast_dates=dates, freq=STEP, logger=logging.getLogger("t"))
    with mock.patch("pandas.Timestamp.now", return_value=now):
        out = Forecast._get_load_forecast_naive(fake, df)
    return dates, out


class TestNaiveTimeAligned(unittest.TestCase):
    def check(self, now, with_partial_step, days=1):
        df = history(now, with_partial_step)
        dates, out = naive(now, df, days)
        base = pd.Timestamp("2026-09-28 00:00", tz=TZ)
        last_complete = df.index[df.index + STEP <= now][-1]
        wrong = []
        for d, got in zip(dates, out["yhat"]):
            src = pd.Timestamp(d) - pd.Timedelta(days=1)
            while src > last_complete:
                src -= pd.Timedelta(days=1)
            want = (src - base) / pd.Timedelta(minutes=1)
            if got != want:
                wrong.append((d, got, want))
        self.assertEqual(wrong[:3], [], f"{len(wrong)} of {len(dates)} steps misaligned")

    # run moments at the start, middle and end of a quarter, with and without the
    # incomplete current step in the history
    def test_on_the_quarter_with_partial(self):
        self.check(pd.Timestamp("2026-09-30 23:00:05", tz=TZ), True)

    def test_mid_quarter_with_partial(self):
        self.check(pd.Timestamp("2026-09-30 23:07:30", tz=TZ), True)

    def test_end_of_quarter_with_partial(self):
        self.check(pd.Timestamp("2026-09-30 23:14:50", tz=TZ), True)

    def test_without_partial_step(self):
        # null case: upstream and the fork agree here
        self.check(pd.Timestamp("2026-09-30 23:00:05", tz=TZ), False)

    def test_two_day_horizon(self):
        self.check(pd.Timestamp("2026-09-30 10:20:00", tz=TZ), True, days=2)


if __name__ == "__main__":
    unittest.main()
