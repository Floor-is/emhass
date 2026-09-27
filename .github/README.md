# EMHASS — fork `planwaarde`

> **Op zoek naar EMHASS?** Die staat hier: **[davidusb-geek/emhass](https://github.com/davidusb-geek/emhass)**,
> met de documentatie op **[emhass.readthedocs.io](https://emhass.readthedocs.io/)** en de Home Assistant-add-on in
> **[davidusb-geek/emhass-add-on](https://github.com/davidusb-geek/emhass-add-on)**. Gebruik die, tenzij je precies
> nodig hebt wat hieronder staat.
>
> *English: this is a small, private-use fork of EMHASS that adds a terminal value for the battery and a value per
> kWh for a deferrable load. For EMHASS itself, go to the links above.*

Deze fork volgt de officiële EMHASS-releases en voegt drie optionele parameters toe. Laat je ze weg, dan
rekent hij hetzelfde als de upstream-versie waarop hij gebaseerd is; zie "Zo wordt hij getoetst".

## Waarom een fork

Wij sturen met EMHASS een thuisbatterij, zonnepanelen en een elektrische auto op dynamische
kwartierprijzen. Twee dingen konden we met de configuratie van EMHASS 0.18.3 niet uitdrukken. We hebben
dat met lokale runs op onze eigen invoer vastgesteld, niet alleen uit de documentatie afgeleid.

1. **De accu eindigt elk dayahead-plan op zijn beginstand.** Zonder `soc_final` valt EMHASS terug op
   `soc_init`, met een boete van 100 × de duurste inkoopprijs per kWh afwijking. Op papier is dat een
   zachte eis, in de praktijk een harde. De planner mag de accu daardoor niet leegmaken, ook niet
   wanneer dat geld oplevert. Een vaste `soc_final` lost dat niet op: elke vaste waarde is op de meeste
   dagen verkeerd.
2. **Een kWh in de auto heeft geen waarde voor de planner.** De auto is een deferrable load met een
   vaste energie-eis, dus EMHASS laadt precies die eis en geen kWh meer, ook als er goedkope stroom is.
   `deferrable_load_max_cost` werkt alles-of-niets, en een negatieve `cost_forecast_per_deferrable_load`
   vervangt het tarief in plaats van er iets bij op te tellen.

Beide punten staan ook upstream open: [#1093](https://github.com/davidusb-geek/emhass/issues/1093) (begon als
"accu laadt niet door"; de discussie gaat over `soc_final` als vaste eindstand) en
[#547](https://github.com/davidusb-geek/emhass/issues/547) (vergoeding per kWh voor een EV-load). We hebben
er zelf een fork van gemaakt omdat we het nu nodig hebben. De code kan later upstream worden aangeboden; dat
is geen doel van deze fork.

## Wat de fork toevoegt

Drie runtime-parameters, ook bruikbaar als config-sleutel. Alle drie staan standaard uit.

| parameter | eenheid | wat hij doet |
|---|---|---|
| `battery_terminal_value` | EUR/kWh (getal, of lijst per accu) | Geen vaste eindstand meer: de energie die aan het eind van de horizon in de accu zit, is `v` per kWh waard. `0` = vrij tot `battery_minimum_state_of_charge`. Weglaten = gedrag van upstream. |
| `deferrable_load_energy_max` | Wh per load | De energie-eis wordt een band: `eis ≤ E ≤ max`, met de eis (`operating_hours × nominal_power`) als vloer. Ligt de eis boven het maximum, dan wint de eis. |
| `deferrable_load_value` | EUR/kWh per load | Elke kWh in de load levert `v` op. Boven de vloer laadt de load alleen in kwartieren waar een kWh minder kost dan `v`. |

Daarnaast, alleen actief als een van de twee load-parameters gezet is:

- **Geen infeasible bij een onhaalbare eis.** Past de vloer niet in het venster, dan laadt EMHASS wat
  kan en zet het tekort in kolom `deferrable<k>_tekort_wh`, met een waarschuwing in de log.
- **Cache-vriendelijk.** De drie parameters zijn `cp.Parameter`s en staan bij de runtime-sleutels van
  `OptimizationCache`. Een nieuwe waarde geeft dus een cache-hit, en de volgende solve rekent met die
  nieuwe waarde.

Beperking: met `deferrable_load_max_cost` > 0 blijft de eis een gelijkheid; de fork logt dan dat
`deferrable_load_energy_max` genegeerd wordt.

### Voorbeeld

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

De auto krijgt hier minstens 10 kWh (0,91 u × 11 kW) vóór stap 38, en hoogstens 40 kWh. Alles boven die
10 kWh alleen waar een kWh minder kost dan €0,539. De accu mag onder zijn beginstand eindigen als de
energie daarin minder dan €0,18 per kWh waard is.

## Zo wordt hij getoetst

- `tests/test_planwaarde.py`: het omslagpunt van de eindwaarde in euro's, vloer/max/waarde bij dure, goedkope
  en gemengde prijzen, een onhaalbare eis, min = max, eis > max, negatieve prijzen, tie-break, 0 of ≥ 4,1 kW, een
  cache-hit met gewijzigde waarden, en zonder parameters hetzelfde als upstream. De tests zijn ook rood gezien:
  op de upstream-versie en op bewust kapotte varianten van de patch.
- De upstream-tests die de optimalisatie raken, draaien mee.
- **Image:** een tag `v<upstream>-planwaarde.<n>` bouwt `ghcr.io/floor-is/emhass:<tag>` (aarch64 en amd64),
  langs dezelfde route als de officiële image. Er wordt pas gepusht als de tests groen zijn op de broncode
  én in het gebouwde image.
- **Upstream-wacht:** dagelijks herbaseert een workflow de patch op de nieuwste upstream-release en draait de
  tests. Een conflict of een rode test maakt de run rood; groen levert tak `planwaarde-op-<tag>` op. Een nieuwe
  release komt nooit vanzelf in het image: dat vraagt een nieuwe tag.

## Takken en tags

- `planwaarde` (standaardtak): de patch op de laatste upstream-release, nu v0.18.4.
- `v0.18.4-planwaarde.1`: huidige release. ⛔ `v0.18.3-planwaarde.1` is een tussenstap met een oude
  parameternaam (`battery_final_value`); niet gebruiken.
- De overige takken zijn kopieën van upstream-takken, meegekomen bij het forken.

## Home Assistant-add-on

[Floor-is/emhass-planwaarde-addon](https://github.com/Floor-is/emhass-planwaarde-addon) draait deze fork. Hij
is een kopie van de officiële add-on en kan ernaast draaien: eigen slug, poort 5001, en geen toegang tot `/share`.
Draai je hem naast de officiële add-on, zet dan `continual_publish: false` in zijn `config.json`. Beide
publiceren anders onder dezelfde sensornamen.

## Status

Nog niet in productie. De fork draait eerst een tijd in schaduw naast de officiële add-on.

## Licentie en herkomst

MIT, zoals EMHASS. Alle eer voor EMHASS zelf gaat naar [David Hernandez](https://github.com/davidusb-geek) en de
bijdragers van [davidusb-geek/emhass](https://github.com/davidusb-geek/emhass/graphs/contributors). Deze fork
voegt alleen de wijzigingen hierboven toe; ze staan als losse commits op de tak `planwaarde`.
