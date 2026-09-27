# EMHASS — `planwaarde` fork

> **Looking for EMHASS?** It lives here: **[davidusb-geek/emhass](https://github.com/davidusb-geek/emhass)**,
> with documentation at **[emhass.readthedocs.io](https://emhass.readthedocs.io/)** and the Home Assistant add-on at
> **[davidusb-geek/emhass-add-on](https://github.com/davidusb-geek/emhass-add-on)**. Use those unless you need
> exactly what is described below.

This fork tracks the official EMHASS releases and adds three optional parameters. Leave them out and it
computes the same results as the upstream release it is based on; see "How it is tested".

## Why a fork

We use EMHASS to run a home battery, solar panels and an electric car on dynamic quarter-hour prices. There
were two things we could not express with the configuration of EMHASS 0.18.3. We established both with
local runs on our own inputs, not just by reading the documentation.

1. **The battery ends every day-ahead plan at its starting state of charge.** Without `soc_final`, EMHASS
   falls back to `soc_init`, with a penalty of 100 × the highest import price per kWh of deviation. On paper
   that is a soft constraint; in practice it is a hard one. The planner cannot run the battery down, even
   when doing so would save money. A fixed `soc_final` does not solve this: any fixed value is wrong on
   most days.
2. **A kWh put into the car has no value to the planner.** The car is a deferrable load with a fixed energy
   requirement, so EMHASS charges exactly that amount and not one kWh more, even when cheap power is
   available. `deferrable_load_max_cost` is all-or-nothing, and a negative
   `cost_forecast_per_deferrable_load` replaces the tariff instead of adding to it.

Both are open upstream: [#1093](https://github.com/davidusb-geek/emhass/issues/1093) (it started as "battery
won't charge past ~50-60 %"; the discussion is about `soc_final` as a fixed end state) and
[#547](https://github.com/davidusb-geek/emhass/issues/547) (a reimbursement rate per kWh for an EV load). We made
our own fork because we need this now. The code may be offered upstream later; that is not a goal of this fork.

## What the fork adds

Three runtime parameters, also usable as config keys. All three are off by default.

| parameter | unit | what it does |
|---|---|---|
| `battery_terminal_value` | EUR/kWh (number, or list per battery) | No fixed end state: the energy left in the battery at the end of the horizon is worth `v` per kWh. `0` = free to go down to `battery_minimum_state_of_charge`. Omitted = upstream behaviour. |
| `deferrable_load_energy_max` | Wh per load | The energy requirement becomes a band, `requirement ≤ E ≤ max`, with the requirement (`operating_hours × nominal_power`) as the floor. If the requirement exceeds the maximum, the requirement wins. |
| `deferrable_load_value` | EUR/kWh per load | Every kWh into the load earns `v`. Above the floor, the load only charges in time steps where a kWh costs less than `v`. |

In addition, active only when one of the two load parameters is set:

- **No infeasible problem when the requirement cannot be met.** If the floor does not fit in the window,
  EMHASS charges what it can and reports the shortfall in column `deferrable<k>_tekort_wh` (*tekort* is
  Dutch for shortfall), with a warning in the log.
- **Cache-friendly.** The three parameters are `cp.Parameter`s and are listed among the runtime keys of
  `OptimizationCache`. A new value therefore gives a cache hit, and the next solve uses the new value.

Limitation: with `deferrable_load_max_cost` > 0 the requirement stays an equality; the fork then logs that
`deferrable_load_energy_max` is ignored.

### Example

```json
POST /action/dayahead-optim
{
  "load_cost_forecast": [...], "prod_price_forecast": [...], "soc_init": 0.62,
  "battery_terminal_value": 0.18,
  "nominal_power_of_deferrable_loads": [11000],
  "operating_hours_of_each_deferrable_load": [0.91],
  "end_timesteps_of_each_deferrable_load": [38],
  "deferrable_load_energy_max": [40000],
  "deferrable_load_value": [0.539],
  "treat_deferrable_load_as_semi_cont": [false],
  "minimum_power_of_deferrable_loads": [4100]
}
```

Here the car gets at least 10 kWh (0.91 h × 11 kW) before time step 38, and at most 40 kWh. Anything above
those 10 kWh is only charged where a kWh costs less than €0.539. The battery may end below its starting state
of charge if the energy in it is worth less than €0.18 per kWh.

## How it is tested

- `tests/test_planwaarde.py`: the break-even point of the terminal value in euros; floor/max/value under
  expensive, cheap and mixed prices; an unreachable requirement; min = max; requirement > max; negative
  prices; tie-break; 0 or ≥ 4.1 kW; a cache hit with changed values; and identical to upstream without the
  parameters. The tests have also been seen failing: on the upstream release and on deliberately broken
  variants of the patch.
- The upstream tests that cover the optimisation run as well.
- **Image:** a tag `v<upstream>-planwaarde.<n>` builds `ghcr.io/floor-is/emhass:<tag>` (aarch64 and amd64),
  along the same route as the official image. Nothing is pushed unless the tests pass on the source *and*
  inside the built image.
- **Upstream watch:** a daily workflow rebases the patch onto the latest upstream release and runs the tests.
  A conflict or a failing test turns the run red; green produces a branch `planwaarde-op-<tag>`. A new release
  never reaches the image by itself: that takes a new tag.

## Branches and tags

- `planwaarde` (default branch): the patch on the latest upstream release, currently v0.18.4.
- `v0.18.4-planwaarde.1`: current release. ⛔ `v0.18.3-planwaarde.1` is an intermediate step with an old
  parameter name (`battery_final_value`); do not use it.
- The other branches are copies of upstream branches that came along with the fork.

## Home Assistant add-on

[Floor-is/emhass-planwaarde-addon](https://github.com/Floor-is/emhass-planwaarde-addon) runs this fork. It is a
copy of the official add-on and can run alongside it: its own slug, port 5001, and no access to `/share`. If
you run it next to the official add-on, set `continual_publish: false` in its `config.json`. Otherwise both
publish under the same sensor names.

## Status

Not in production yet. The fork will first run in shadow next to the official add-on for a while.

## Licence and credits

MIT, like EMHASS. All credit for EMHASS itself goes to [David Hernandez](https://github.com/davidusb-geek) and the
[contributors to davidusb-geek/emhass](https://github.com/davidusb-geek/emhass/graphs/contributors). This fork only
adds the changes described above; they are separate commits on the `planwaarde` branch.
