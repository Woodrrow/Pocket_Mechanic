# Maintenance guides — requirements

Scope: the guides feature only (`Data/guides/`, `Data/guide_rules.json`,
`src/guides_store.py`). Prioritised MoSCoW. Items marked *Done* are implemented
and tested; the rest are outstanding.

---

## Must have

| # | Requirement | Status |
| --- | --- | --- |
| M1 | A generic, step-by-step procedure for each common job, usable without knowing anything about the car | Done |
| M2 | Guides tailored to a specific vehicle where data allows, via rules keyed on vehicle attributes rather than make/model | Done |
| M3 | Any attribute that cannot be established resolves to `"unknown"` and produces a "check before you start" warning — never a guess | Done |
| M4 | Any spec that is not on file renders as *not on file*, never as an inferred number | Done |
| M5 | Every tailored element carries a `because_of` naming the rule that produced it, so output is traceable | Done |
| M6 | A safety disclaimer on every guide response | Done |

## Should have

| # | Requirement | Status |
| --- | --- | --- |
| S1 | Verified trait data (`Data/vehicle_traits.json`) covering the most common UK models, so tailoring fires for most cars in a typical garage | Outstanding |
| S2 | Wider guide coverage: discs, spark plugs, cabin filter, wiper blades, bulbs, coolant | Outstanding |
| S3 | Guide ranking informed by fleet-wide MOT failure data (`Data/common_faults.py`), not only the individual car's own history | Outstanding |

## Could have

### C1 — Populate per-vehicle specs (`Data/vehicle_specs.json`)

Torque figures, part numbers and capacities, keyed by make/model/year range.
The loader and the rendering path already exist and are tested against an
absent file; this is a data-sourcing task, not an engineering one.

Deferred because it needs a real source. The first attempt was seeded from
recollection and removed in `47fb7d3` — see *Lessons* below, which are binding
acceptance criteria for this requirement, not background reading.

**Acceptance criteria**

- [ ] Every entry carries a `source` field citing where the figure came from,
      specific enough to re-check (e.g. `"Haynes 5578, table 2.1"`, not
      `"Haynes"`). The API surfaces this field, so an uncited figure is an
      anonymous one.
- [ ] No entry spans a make/model/year range wider than the range actually
      checked, end to end.
- [ ] Where a value is unverified, the key is **omitted** rather than
      estimated. A missing key is a supported state; a wrong one is not.
- [ ] Schema conforms to the definition in the README.

### C2 — Populate vehicle traits (`Data/vehicle_traits.json`)

Same shape, same acceptance criteria as C1. Higher risk than C1: traits drive
*safety warnings* rather than numbers a user might sanity-check, so a wrong
trait silently suppresses the warning that would otherwise have protected
someone.

## Won't have (this iteration)

| # | Item | Reason |
| --- | --- | --- |
| W1 | Scraping a commercial data provider | Licensing. HaynesPro, Autodata and Alldata are paid products and their terms prohibit it. |
| W2 | Torque figures or part numbers without a cited source | See C1. This is the specific failure this document exists to prevent. |
| W3 | Guides for jobs affecting airbags, fuel lines under pressure, or hybrid/EV high-voltage systems | Beyond safe DIY scope for a general-audience app. |

---

## Lessons

Two notes from the first, withdrawn attempt at C1/C2. Both are cheap to honour
up front and expensive to retrofit.

### 1. Cite the source per entry, not per file

The `source` field is returned in the API response. Filling it in per entry
makes a wrong figure traceable — you can go back to the table it came from and
see whether it was misread or the source itself was wrong. A file-level
"from Haynes" tells you nothing when one number in forty turns out wrong, and
gives every figure in the file the same unearned credibility.

### 2. Watch the variant split — the granularity trap

Brake hardware, and therefore most of what the rules key on, often differs
between trim levels of the *same model and year*. Rear disc vs drum, screw-in
vs push-in pistons, and electric vs cable parking brakes all commonly split
within a model range.

The concrete failure: a single entry claimed `rear_brake_type: "drum"` for every
Alfa Romeo MiTo from 2008–2018. Broadly right for the common 1.4 petrol cars,
and wrong for the disc-braked Cloverleaf/QV variants — but stated with enough
specificity that the guide confidently told those owners the brake-pad procedure
did not apply to their car.

So: `models: ["Mito"]` with a wide year range is the wrong granularity for
anything brake-related. Either split the entry by variant, or omit the key and
let it resolve to `"unknown"`. The fallback warning ("check whether your car has
an electric parking brake before starting") is a perfectly good answer. An
authoritative-sounding wrong answer is not.

**The general rule: the cost of `"unknown"` is a mildly less useful guide. The
cost of a wrong entry is someone trusting it.**
