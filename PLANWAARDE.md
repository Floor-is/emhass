# PLANWAARDE-fork van EMHASS

Fork van [davidusb-geek/emhass](https://github.com/davidusb-geek/emhass) met drie extra knoppen. Zonder
die knoppen gedraagt hij zich als de upstream-release waarop de tak `planwaarde` staat.

| sleutel | eenheid | wat |
|---|---|---|
| `battery_final_value` | EUR/kWh (getal of lijst per accu) | geen vaste eindstand; de energie aan het eind van de horizon is `v` per kWh waard. De accu mag tot `battery_minimum_state_of_charge`. |
| `deferrable_load_energy_max` | Wh per load | de eis wordt `eis <= E <= max`. De eis (`operating_hours × nominal_power`) is de vloer. |
| `deferrable_load_value` | EUR/kWh per load | elke kWh in de load levert `v` op. Boven de vloer laadt de load alleen waar een kWh minder kost dan `v`. |

Alle drie zijn runtime-parameters (zoals `soc_init`) en config-sleutels. Beperking: met
`deferrable_load_max_cost` > 0 blijft de eis een gelijkheid; de fork logt dan een waarschuwing.

## Releases

- Tak `planwaarde`: de patch als losse commits op een upstream-tag.
- Tag `v<upstream>-planwaarde.<n>` bouwt `ghcr.io/floor-is/emhass:<tag>` (workflow `PLANWAARDE image`).
  Er wordt alleen gepusht als `tests/test_planwaarde.py` en de upstream-optimalisatietests groen zijn,
  en de planwaarde-tests ook in het gebouwde image groen zijn.
- Workflow `PLANWAARDE upstream-wacht` herbaseert dagelijks op de nieuwste upstream-release. Een conflict
  of een rode test maakt de run rood. Groen levert tak `planwaarde-op-<tag>` op, zonder tag en zonder image.

Add-on: [Floor-is/emhass-planwaarde-addon](https://github.com/Floor-is/emhass-planwaarde-addon).
