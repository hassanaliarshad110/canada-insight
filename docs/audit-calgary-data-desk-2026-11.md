# Audit of Calgary Data Desk (existing product)

Audit date: 5 November 2026. Auditor: Claude, for Hassan Ali.
Scope: repository `hassanaliarshad110/calgary-data-desk` at commit `6a28a51` (5 Nov 2026), the live website built
5 Nov 2026 02:12 (Calgary time), and the City of Calgary open data it reads.

The existing site is left unchanged. Everything recommended here is being built in the separate Canada Insight
repository.

## How the audit was done

- Read the full codebase (about 21,600 lines: 37 Python modules, the desktop/web UI, the build workflow).
- Downloaded the published dashboard data for all of Calgary (`data/city_actual/w0.json`, 5.3 MB) from the live site.
- Recalculated selected figures independently against the City's Socrata API (data.calgary.ca), using separate code
  written for this audit, not the product's own functions.
- Items marked **Verified** were recalculated. Items marked **Code review** are findings from reading the code and
  documentation only.

## Summary, by severity

| # | Severity | Finding | Module |
|---|---|---|---|
| 1 | Critical | The "Needs attention" ranking labels communities "Urgent" using amenities counted inside community boundaries per resident, which disagrees with actual walking access. **Verified** | Growth vs amenities |
| 2 | High | Open-request backlog figures are inflated by a retired request type ("311 Contact Us"): 24,928 of 75,371 open requests (33%), none created in the last 12 months. **Verified** | 311 |
| 3 | High | Every 311 record's location is the community centre point, not the request location (453,547 of 453,547 in the last 12 months). Any point map of 311 issues shows centroids. **Verified** | 311 |
| 4 | High | The Claude API key is published inside `data/genie.json`, encrypted only with the shared access code. Anyone can download the file and try codes offline; anyone given the code can recover the key. **Code review** | AI assistant |
| 5 | High | No automated tests. Methods are documented in prose (`methods.py`) but no test checks that code and prose agree. **Code review** | All |
| 6 | Medium | The default population denominator spreads about 129,000 residents (8.1% of the total) by assumption, and the 2026 figure it scales to is a forecast. **Verified** | Population, all rates |
| 7 | Medium | "Closed within 7 days" counts only requests already closed and mixes service types, so ward comparisons reflect service mix as much as speed. **Code review** (limitation partly disclosed) | 311 |
| 8 | Medium | Children by community are estimates built on estimates; child care spaces for children 0 to 14 mix age groups served by different programs. **Code review** | Schools and child care |
| 9 | Medium | The architecture is Calgary-specific throughout (dataset IDs, Ward 5 defaults, City population constants copied from a PDF), and the website is the desktop app's screens behind a bridge. Not reusable for another city. **Code review** | Architecture |
| 10 | Low | 6.4% of the last 12 months' 311 requests (31,280) have no community code and drop out of every area rate. Not disclosed on screen. **Verified** | 311 |
| 11 | Info | Ward attribution was checked and is sound: only 2 of 223 residential communities have more than 5% of their area outside their assigned ward (about 170 residents by area). **Verified** | Ward analytics |
| 12 | Info | The 12-month city-wide 311 count reconciles: 453,534 published against 453,547 recounted (13 records added after the build). **Verified** | 311 |

## Findings in detail

### 1. Growth vs amenities: "Needs attention" (Critical)

**What it does.** For each community it counts City assets inside the community boundary (playgrounds, benches,
picnic tables, basketball hoops, goal posts, fitness equipment, park bins, off-leash areas, neighbourhood park
hectares, public trees), divides by residents (children 0 to 14 for playgrounds), divides by Calgary's average,
caps each kind at 2.0, averages the kinds with equal weight into an "amenity level", applies a growth weight
(0.5 + growth% / 200) and assigns tiers: Urgent, High, Watch.

**Data.** City asset inventories (Parks Seating, Playground Equipment, Parks Sport Equipment, Parks Sites, Public
Trees and others), OpenStreetMap additions, the growth-model population.

**Is it defensible?** Not as a measure of need or access:

- *Boundary counting is not access.* Residents use the playground across the street even when it sits in the next
  community. Recalculation on 502,008 residential property records and 1,115 active City playgrounds (straight-line
  distance from each home to the nearest playground, any community):

  | Community (tier) | Playground level used by the ranking | Homes within 400 m of a playground |
  |---|---|---|
  | Medicine Hill (Urgent) | 0.28 of Calgary | 99% |
  | South Calgary (Urgent) | 0.28 | 85% |
  | Homestead (Urgent) | 0.45 | 67% |
  | Glacier Ridge (Urgent) | 0.59 | 69% |
  | Beltline (Urgent) | 0.19 | 22% |
  | Calgary as a whole | 1.00 | 73.2% |

  Across 215 communities, the rank correlation between the two measures is 0.45. Seven communities sit below half the
  "Calgary level" while having better-than-average walking access (for example North Haven Upper 0 / 96%, Currie
  Barracks 0.47 / 99%); four are above the Calgary level with poor access (Eau Claire 6.53 / 25%).
- *Equal weights across unlike things.* A park bench, a garbage bin and a hectare of park count the same. No
  justification or sensitivity analysis is given.
- *The growth weight and tier cut-offs are arbitrary* (0.50 / 0.75 / 20%), and the "Urgent" label reads as a
  measured finding.
- *The yardstick is the city average*, so about half of communities are always "below Calgary" by construction.
- *Inventory lag.* In new communities, developer-built parks and playgrounds may not yet be in the City's asset
  inventory. New communities are the ones most often flagged.

**Currency.** Asset datasets updated 1 November 2026; current.

**What could mislead.** A councillor or journalist reading "Urgent" would conclude these communities lack
playgrounds and parks. For several, the data says the opposite. A published video brief (5 Nov 2026) presents this
analysis.

**Recommended fix.** Measure access directly: the share of homes within a stated walking distance of each kind of
amenity, separately for homes built since the 2021 Census and homes built before, with no composite score. Report
distance thresholds, sensitivity at a second threshold, and an "inventory may lag" caution where many homes are new.
This is the first module built in Canada Insight.

### 2. Open 311 requests and the backlog (High)

**What it does.** Counts requests with status "Open" now, and those open more than 90 days, per community and ward.

**Verified.** 75,371 requests are open city-wide. 24,928 (33%) are "311 Contact Us", a type with no new requests in
the last 12 months. Open requests by year made: 2019: 2,579; 2020: 5,610; 2021: 4,328; 2022: 8,995; 2023: 7,969;
2024: 10,695; 2025: 10,112; 2026: 25,072. Many multi-year "open" records are likely administrative rather than
unresolved service problems.

**Misleading risk.** The "open more than 90 days" figure (62,122 city-wide in the published build) reads as a
service backlog. Ward comparisons partly reflect how many legacy records each area holds.

**Fix.** Exclude retired types, report open requests by service type with age bands, and compare each type against
its own city median rather than one pooled figure.

### 3. 311 locations are community centroids (High)

All 453,547 requests with a community in the last 12 months have `location_type = Community Centrepoint`. The
public dataset carries no request-level location. Maps that plot 311 issues as points (the product's "interactive map
of issues" and the open-issue details panel) show the community's middle point, not where the problem is. The
product should present 311 at community level only and say why.

### 4. AI key exposure (High)

`web/build_site.py` encrypts the owner's Claude API key with the access code (PBKDF2, 600,000 iterations, AES-GCM)
and publishes it as `data/genie.json`. The README discloses that anyone with the code can read the key. In addition,
anyone can download the file and test codes offline, without rate limits. Fix: keep the key on a server (a small
serverless function) with per-user rate limits and a spend cap; the browser never receives it.

### 5. No automated tests (High)

There are no unit tests or reconciliation tests. Methods are prose in `methods.py`. Fix: a test suite for every
indicator formula, geometry routine and data-quality rule, run on every change.

### 6. Population denominators (Medium)

The default ("City's total, shared by actual growth") gives 1,598,075 residents for 5 November 2026: the growth
model's 1,468,721 plus a uniform factor (1.1004 on each community's 2021 count) that brings the total to the City's
Spring 2026 forecast. The 2021 Census household population is 1,288,995. About 129,000 residents (8.1%) are placed
by assumption, and the 2026 figure is a forecast. Every per-1,000 rate depends on this choice. The product does
disclose the four methods; it should also show the spread between them as an uncertainty range on each rate, and
switch to 2026 Census counts when Statistics Canada releases them (scheduled for 10 February 2027).

### 7. "Closed within 7 days" (Medium)

Only requests already closed are counted (disclosed), so recent periods look faster. Service mix differs by ward
(snow and ice, potholes, bylaw), so pooled shares compare mix as much as performance. Fix: per service type,
median days to close with open requests treated as still running (survival method), compared with the same type
city-wide, and published service standards where they exist.

### 8. Children and child care (Medium)

Children by community after 2021 are estimated (2021 Census share plus a share for new residents). Licensed child
care spaces (which serve children 0 to 12 in different program types) are divided by estimated children 0 to 14.
Fix: match program type to age group, show estimates as estimates with ranges, and measure access with a capacity-
aware catchment method (licensed spaces within reach per child within reach).

### 9. Architecture (Medium)

Dataset IDs, ward numbers, the Ward 5 default and population constants are embedded across modules. The website
runs the desktop app's screens through a JavaScript bridge, and a full build takes about 58 minutes producing 5 MB
per ward per method. A second city would require a rewrite. Fix: the Canada Insight core with per-city
configuration (see `architecture.md`).

### 10. Requests with no community (Low)

31,280 of the last 12 months' requests (6.4%) have no community code; they are left out of every community and ward
rate without a note. Fix: report them as "not placed" beside every total.

### 11. Ward attribution (checked, sound)

Each community is assigned to the ward holding most of its area. Sampling every residential community on a 40 x 40
grid against the 2024 ward outlines: 2 of 223 have more than 5% of their area in another ward (Diamond Cove 92%,
Bonavista Downs 94%), none more than 20%. About 170 residents (by area) are placed in a neighbouring ward. No change
needed.

### 12. 311 totals reconcile

Requests (not duplicates) with a community, November 2025 to October 2026: 453,534 in the published build, 453,547
recounted on 5 November (records added after the build). Matches.

## Module-by-module notes

| Module | What it does | Data | Defensible? | Current? | Missing | Could mislead | Improve |
|---|---|---|---|---|---|---|---|
| Ward analytics | 14-ward comparison of 311, safety, growth, amenities | City open data, CPS | Ward mapping sound (finding 11); rates depend on modelled denominators | Daily build | Uncertainty ranges | Rank orders on modelled rates | Show ranges; rank only where differences exceed the range |
| Growth vs amenities | Amenity level and Needs attention tiers | City assets, OSM, growth model | No (finding 1) | Yes | Distance, capacity, inventory lag | "Urgent" labels | Distance-based access (built first) |
| 311 | Volumes, rates, open, 7-day closure, app share | 311 Service Requests | Volumes reconcile; open and closure metrics flawed | Daily | Service-mix control, request locations | Backlog, point maps | Findings 2, 3, 7, 10 |
| Crime | CPS crime and disorder by community and ward; CSI | CPS, Statistics Canada | Reasonable; quarterly data | Quarterly | Per-type rates with ranges | Small-number swings | Show counts beside rates; suppress small bases |
| Development permits | Homes in building permits, DP applications | City permits | Counts are counts | Daily | Completions vs permits | Applied ≠ built | Separate applied, issued, completed |
| Schools and child care | Enrolment, licensed spaces, inspections | Government of Alberta | Mixed age groups (finding 8) | Province's schedule | School capacity | Spaces per child | Capacity-aware access |
| Municipal budget | City budget and actuals by service; projects with cost | Calgary Open Budget | Correctly says budget is not by ward | Yearly | Actuals by project | Project cost read as spent | Label approved vs actual vs announced |
| Community needs / attention | Tiered list | As finding 1 | No | Yes | Needs indicators (income, age, Equity Index) | Composite reads as need | Separate needs from access; no composite |
| AI research and audit | Data Genie, Data Scientist reports, three-step audit | Claude API, platform data | Good intent (cites, re-runs figures) | n/a | Server-side key, tests | Key exposure (finding 4) | Server proxy; answers only from the indicator store |

## What could not be verified here

- The OpenStreetMap additions and the full population build-up were not recalculated.
- Crime figures were not recalculated against Calgary Police Service files.
- The daily scheduled refresh was not checked against GitHub Actions run history (the session had read-only access
  to the repository).
