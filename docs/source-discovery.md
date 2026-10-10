# GUS source discovery and data contract

The accepted scope is **169 full municipalities in Dolnośląskie, 2023–2025**.
The public snapshot `bdl-dolnoslaskie-2023-2025-20261010` was obtained from live
official GUS BDL API responses on 10 October 2026. It contains **3,549 observations**
for seven source variables. Three locally derived metrics bring the profile
dictionary to ten described features. Source identifiers are never assigned to
locally derived metrics.

## Evidence and access

The [official API portal](https://api.stat.gov.pl/home/bdlapi) describes the resource
hierarchy, year and municipality filters, the `X-ClientId` header, request limits
and CC BY 4.0 reuse. Browser-style fetches and the initial restricted PowerShell
request failed; an approved read of the public API succeeded with HTTP 200. This
was an environment network restriction, not evidence that GUS was unavailable.
No credentials or API key were required for the acquisition.

The investigation actually read `subjects`, `variables`, `units`, `levels`,
`aggregates`, `attributes`, `measures`, and both data access routes. The small JSON
responses are stored in `data/sample/source_responses`. Every successfully retained
response has a `.meta.json` sidecar containing its URL, structured query parameters,
UTC retrieval time, HTTP status, content type and SHA-256. The completed manifest
lists all 21 regional data pages and expected/received counts. The response bodies
are original UTF-8 JSON; Polish names are preserved.

A catalog request for the first page of all P3447 candidates timed out later during
exploration. Its result is not used as accepted evidence. Individual metadata for
every accepted variable and all required regional pages were successfully obtained.
Failure of that optional catalog request does not make the accepted snapshot partial.

The anonymous limits displayed by the official API portal are 5 requests/second,
100/15 minutes, 1,000/12 hours and 10,000/7 days. Registered limits are respectively
10, 500, 5,000 and 50,000. The acquisition used sequential regional requests with
spacing and remained below the anonymous 15-minute budget. Live refresh uses the
package client, persistent cache and its conservative multi-window limiter.

## Territory, historical units and identifiers

The live `units/030200000000` response identifies Dolnośląskie at level 2, under
macroregion `030000000000`. The accepted municipality level is **6**, confirmed by
the actual `levels` dictionary. The request

```text
/api/v1/units?parent-id=030200000000&level=6&format=json&page-size=100&page=0
```

has 294 records over three pages. This list contains current units, historical
records and parts of urban-rural municipalities. The actual `aggregates` dictionary
explains that full municipalities are kinds **1, 2 and 3**; kinds **4 and 5** are
the urban and rural parts of kind 3. Including all five kinds would double count.

Sixteen individual unit metadata responses were inspected to resolve historical
records. The current sample includes **35 urban, 76 rural and 58 urban-rural**
municipalities. **116 parts and nine historical records** are excluded. Historical
unit IDs are listed in the manifest with original metadata retained. Examples:

| Unit history | Accepted interpretation |
|---|---|
| Miękinia `030210418032` / `030210418033` | Rural code ends in 2022; urban-rural code starts in 2023. Only the latter enters all selected years. |
| Pieszyce `030210302031` / `030210302033` | Urban record ends in 2015; urban-rural record starts in 2016. |
| Wałbrzych `030210321091`, `030210363011`, `030210365011` | Only the municipality record valid from 2013 enters the cohort. The county record is not counted as another municipality. |
| Miejska strefa usług publicznych `030210216001` | Although `hasDescription=false`, individual metadata gives only 1998–1999; it is excluded. |

Each regional data variable independently returns **285 unit records**, exactly
169 full municipalities plus 116 parts. All accepted municipality IDs occur for
all three years in every variable. The data and dictionary checks therefore agree
on the accepted territory. There is no merge by name.

`bdl_unit_id` remains a separate 12-character string. `teryt` is NULL because an
independent TERYT crosswalk was not acquired; a substring of the BDL identifier
is not presented as verified TERYT. For described units, validity comes from the
individual metadata's `years`. For units without an individual history, 2023–2025
is recorded as verified snapshot coverage, explicitly distinguished by
`validity_basis`; it is not a claim about their foundation date.

## Accepted source indicators

The complete machine-readable contract is in `config/indicators.yml` and its
immutable snapshot copy `data/sample/configuration.json`. It preserves original
dimensions/names, topic path, definition version, units, age and facility scope,
reference period, source years and URLs, attribute rules and selection rationale.

| GUS ID | Metric alias | Verified selection and purpose |
|---|---|---|
| 453371 | `population_total` | P3447; all ages, both sexes, total location; residents, persons. Demographic context and share denominator. |
| 453372 | `children_0_2` | P3447; age group **0–2**, both sexes, total location; residents, persons. Excludes age 3. |
| 1649554 | `care_places` | P3219; places overall including children's clubs; places, measure 64. Capacity profile and ratio numerator. |
| 1649557 | `children_in_care` | P3219; children overall including clubs **as of 31 December**, persons. Overall attendees, not a count restricted to resident children 0–2. |
| 377234 | `nurseries` | P3219; nurseries, objects, measure 35. Facility profile. |
| 377225 | `child_clubs` | P3219; children's clubs, objects, measure 35. Facility profile. |
| 1649860 | `gus_places_per_1000` | P3227; nursery/club places per 1,000 children below age 3. Independent published check of the local ratio. Original unit is `-`, measure 1; displayed meaning is retained. |

The demographic path is `K3 → G7 → P3447`. Childcare counts use
`K22 → G266 → P3219`; the published ratio uses `P3227`. Every accepted source
variable's own live metadata includes **2023, 2024 and 2025** and level 6; availability
was not inferred from the current calendar year. Demographic metadata was updated
on 6 May 2026; childcare source metadata on 26–27 August 2026.

Year-end childcare stocks are also consistent with the official
[2025 childcare release](https://stat.gov.pl/obszary-tematyczne/dzieci-i-rodzina/dzieci/opieka-nad-dziecmi-w-wieku-do-lat-3-w-2025-r-%2C3%2C13.html).
Care counts refer to **location of the facility**, while population refers to
residents. Numerators are overall nursery/club capacity, without assuming an exact
age restriction on all attendees. Day carers, nannies, nursery wards, prices and
queues are outside these capacity counts.

## Derived indicators

| Local metric ID | Formula and source inputs | Interpretation |
|---|---|---|
| `children_share_pct` | `100 × 453372 / 453371` | Percentage of residents aged 0–2; separate demographic signal. |
| `care_facilities` | `377234 + 377225` | Number of nurseries and children's clubs, not capacity or enrolment. |
| `places_per_1000` | `1000 × 1649554 / 453372` | Overall institutional capacity relative to resident children 0–2; not the percentage of those children receiving care. |

All required inputs must be semantically valid. A zero numerator and positive
denominator gives a true zero. Missing input remains missing; nonpositive
denominator gives an unavailable ratio with a reason. Ratios above 1,000 are
preserved. No GUS identifier is invented for any of these metrics.

## Age and ratio cross-checks

Individual P1341 variables **71, 72 and 73** were retrieved with their metadata;
their dimensions are both sexes and exact ages 0, 1 and 2. Real by-unit responses
for Wrocław (`030210564011`, kind 1), Kobierzyce (`030210423052`, kind 2) and
Siechnice (`030210423083`, kind 3) contain these variables and 453372.
**All nine unit-year sums exactly equal the P3447 0–2 group.** This supports using
the directly provided grouped measure and avoids adding three separate source
features merely to inflate the profile.

The local capacity ratio was checked for **all 507 municipality-years** against
1649860. All pass an absolute tolerance of **0.500000001 places per 1,000 children**.
The published series has integer display values; half one display unit is the
rounding tolerance, with a small floating-point allowance. The largest difference
is **0.49769585253454807**. No values were altered to force agreement. For example,
Kobierzyce in 2025 has 359 places and 618 children aged 0–2, giving 580.906149;
GUS publishes 581. The local value is retained at full calculation precision.

All cross-check inputs, results and regional control totals are saved in
`data/sample/source-verification.json`. In 2023 one municipal ratio exceeds 1,000;
this is retained and is consistent with the interpretation of capacity and
cross-boundary attendance. It does not imply erroneous or negative demand.

## Comparable years and rejected candidates

The actual `subjects/G266` and `subjects/K22` descriptions explicitly document the
**2023 change from OD-1 to MRPiPS administrative RKZ 4G data**. The K3 description
states that population from 2020 onwards was recalculated using the NSP 2021
base. The selected 2023–2025 window is wholly after both boundaries. The selected
variables have stable dimension names and units over the window, and observations
contain no methodology flags. No earlier series is spliced into this snapshot.

The P3227 subgroup description contains historical language about nursery wards;
its own text also documents their removal from the 2022 register. The **individual
1649860 definition**, the post-2022 period and the 507 numerical cross-checks
support its use with nursery/club-only counts. Broad subgroup prose is not treated
as permission to merge incompatible variable IDs.

Rejected or deliberately unused candidates:

- 377236/377237 and old pre-2022 ward-inclusive series: different facility scope
  and availability ending in 2021.
- 1649555, children staying during the year: flow measure, only 2022 in the verified
  current source listing; incompatible with the selected stock measure and period.
- 1649859, children per 1,000: metadata was checked, but it duplicates the care
  attendance signal and adds no distinct score component.
- Exact-age source 71/72/73: useful verification inputs, while grouped 453372 is
  the simpler accepted feature; no automatic partial sums are used.
- 2022: available for some selected childcare IDs, but lies before the explicitly
  documented 2023 source change. The MVP already has three comparable later years.
- Extra unrelated indicators, inferred demand, deprivation proxies and forecasts:
  outside the specified topic and unsupported by this data.

The source periods support descriptive comparison, not a claim that administrative
systems can never be revised. Future refreshes must compare definition versions,
unit histories and attributes before extending the window.

## Attribute semantics and quality

The live attribute dictionary has **18 entries**. The interpreter acts on the
value–attribute pair, not the numeric value alone. All actual selected observations
use only 0 or 1, with no flagged unavailable values. **2,484 valid nonzero values**
and **1,065 true zeros** are retained. Complete source acquisition and meaningful
source missingness are separate properties.

| Attribute IDs | GUS meaning | Analytical policy |
|---|---|---|
| 0, 1 | Plain zero / plain value; blank symbol and description | Preserve numeric value. Zero is `true_zero`; other values `valid`. |
| 94 | Significant zero resulting from balanced nonzero inputs | Preserve the genuine zero, with its source attribute. |
| 4, 91 | Combined lack of information / confidentiality / impossible or inapplicable entry | NULL; broad unavailable reason. Do not claim a cell specifically represents secrecy. |
| 7 | Value below presentation precision | NULL; below-precision reason, not an exact zero. |
| 3 | Aggregate may be incomplete | Exclude from the required score cohort. |
| 9 | Preliminary estimates | Retain a flagged source value; conservative baseline does not accept it for scoring. |
| 11, 13, 14, 17, 98 | Methodology change, sometimes combined with other restrictions | Preserve flag; block comparable scoring and trend connection. |
| 15 | Presentation level, territorial list or feature list changed | Missing/incompatible scope; no invented detailed cause. |
| 20, 21 | Low precision | Preserve flagged raw evidence; exclude from baseline score. |
| 50 | Not yet available | NULL; unavailable, distinct from unrequested/unreceived pages. |
| 97 | Combined county and city on county rights | Territorial scope incompatible with an individual municipality score. |
| Unknown or absent attribute | Unverified semantics | Block validity; never assume an ordinary value. |

No `fillna(0)`, interpolation or silent aggregation of missing parts is permitted.
The accepted baseline cohort can admit only valid observations and verified true
zeros. A methodology or precision flag matters even when its numeric value is
nonzero. The source snapshot currently has no genuine missing required metric;
the UI's clearly separate missing-data scenario cannot remove real municipal data.

## Control totals and reuse

| Year | Gminy | Children 0–2 | Nursery/club places | Children in care at 31 December | Gminy with zero places |
|---|---:|---:|---:|---:|---:|
| 2023 | 169 | 66,865 | 22,389 | 18,959 | 54 |
| 2024 | 169 | 60,143 | 22,467 | 17,809 | 55 |
| 2025 | 169 | 54,869 | 23,472 | 17,001 | 47 |

These are direct sums of the accepted full municipality rows, not sums including
parts or historical codes. They are reproducible from the CSV and recorded in
the verification JSON. The official [attribute page](https://bdl.stat.gov.pl/bdl/metadane/atrybut)
and [API portal](https://api.stat.gov.pl/home/bdlapi) identify CC BY 4.0 reuse.
Data attribution is supplied in `data/sample/README.md`, the manifest and exports;
MIT applies to project code. The original source values and attribution must travel
with redistributed exports, while local calculations remain clearly marked.
