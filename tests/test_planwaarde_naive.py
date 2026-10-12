#!/usr/bin/env python
"""The naive load forecast must be aligned on the time of day, whatever the moment it runs.

Since v0.18.5-planwaarde.1 the fork uses the upstream naive forecast (#1171,
``Forecast.get_naive_load_forecast``): the load at the same local wall-clock time on the
most recent calendar day where that time is in the history. The fork's own rule
(``history[L - 24 h]``, a6c29dad) is gone. These tests stay as a guard:

- ``TestNaiveTimeAligned``: run moments at the start, middle and end of a quarter, with and
  without the current, incomplete step in the history (the positional relabelling of
  v0.18.4 failed 4 of these). One-day horizon, as the add-on runs it.
- ``TestNaiveDstFallBack``: 25-10-2026, the clock goes from 03:00 CEST back to 02:00 CET.
  A rule that looks back 24 h absolute reads the history one hour shifted on that day;
  the forecast must keep the time of day.
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


def history(now, with_partial_step, days=2):
    """15-minute labels up to now; value = minutes since midnight 28-9 (unique)."""
    start = now.floor("15min") - pd.Timedelta(days=days)
    end = now.floor("15min") if with_partial_step else now.floor("15min") - STEP
    idx = pd.date_range(start, end, freq="15min", tz=TZ)
    base = pd.Timestamp("2026-09-28 00:00", tz=TZ)
    return pd.DataFrame({"load": [(t - base) / pd.Timedelta(minutes=1) for t in idx]}, index=idx)


def naive(now, df, days=1):
    with mock.patch.object(utils, "_get_now", return_value=now.tz_convert("UTC")):
        dates = utils.get_forecast_dates(15, days, TZ)
    # Forecast keeps its forecast_dates as a DatetimeIndex in the configured time zone
    dates = pd.DatetimeIndex(pd.to_datetime(dates, utc=True)).tz_convert(TZ)
    fake = types.SimpleNamespace(forecast_dates=dates, freq=STEP, logger=logging.getLogger("t"))
    with mock.patch("pandas.Timestamp.now", return_value=now):
        out = Forecast._get_load_forecast_naive(fake, df)
    return dates, out


class TestNaiveTimeAligned(unittest.TestCase):
    def check(self, now, with_partial_step):
        df = history(now, with_partial_step)
        dates, out = naive(now, df)
        base = pd.Timestamp("2026-09-28 00:00", tz=TZ)
        wrong = []
        for d, got in zip(dates, out["yhat"]):
            want = (pd.Timestamp(d) - pd.Timedelta(days=1) - base) / pd.Timedelta(minutes=1)
            if got != want:
                wrong.append((d, got, want))
        self.assertEqual(wrong[:3], [], f"{len(wrong)} of {len(dates)} steps misaligned")

    def test_on_the_quarter_with_partial(self):
        self.check(pd.Timestamp("2026-09-30 23:00:05", tz=TZ), True)

    def test_mid_quarter_with_partial(self):
        self.check(pd.Timestamp("2026-09-30 23:07:30", tz=TZ), True)

    def test_end_of_quarter_with_partial(self):
        self.check(pd.Timestamp("2026-09-30 23:14:50", tz=TZ), True)

    def test_without_partial_step(self):
        # null case: the positional rule of v0.18.4 also passed this one
        self.check(pd.Timestamp("2026-09-30 23:00:05", tz=TZ), False)


def wall_clock_history(now, days=3):
    """15-minute labels up to now; value encodes the LOCAL day and time of day of the label."""
    start = now.floor("15min") - pd.Timedelta(days=days)
    idx = pd.date_range(start, now.floor("15min"), freq="15min", tz=TZ)
    return pd.DataFrame({"load": [encode(t) for t in idx]}, index=idx)


def encode(t):
    return t.day * 10000 + t.hour * 100 + t.minute


class TestNaiveDstFallBack(unittest.TestCase):
    """25-10-2026 03:00 CEST -> 02:00 CET: same time of day, never one hour shifted."""

    def check(self, now):
        df = wall_clock_history(now)
        dates, out = naive(now, df)
        shifted, wrong = [], []
        for d, got in zip(dates, out["yhat"]):
            got = int(got)
            day, hhmm = divmod(got, 10000)
            if hhmm != d.hour * 100 + d.minute:
                shifted.append((d, got))
                continue
            # one calendar day back (not 24 h); a wall-clock time that occurs twice on 25-10
            # (02:00-02:45) is ambiguous there and may come from the day before
            local = d.tz_localize(None)
            back = {(local - pd.Timedelta(days=1)).day}
            if (local - pd.Timedelta(days=1)).day == 25 and d.hour == 2:
                back.add((local - pd.Timedelta(days=2)).day)
            if day not in back:
                wrong.append((d, got))
        self.assertEqual(shifted[:3], [], f"{len(shifted)} of {len(dates)} steps one hour shifted")
        self.assertEqual(wrong[:3], [], f"{len(wrong)} of {len(dates)} steps from the wrong day")

    def test_run_on_the_change_day(self):
        # targets on 25-10 after 03:00 read 24-10 (CEST): 24 h absolute lands an hour late
        self.check(pd.Timestamp("2026-10-25 10:20:00", tz=TZ))

    def test_run_the_evening_before(self):
        # targets in the night of the change read 24-10
        self.check(pd.Timestamp("2026-10-24 22:20:00", tz=TZ))

    def test_run_the_day_after(self):
        # targets on 26-10 before 03:00 read 25-10, partly in CEST
        self.check(pd.Timestamp("2026-10-26 00:20:00", tz=TZ))


if __name__ == "__main__":
    unittest.main()
