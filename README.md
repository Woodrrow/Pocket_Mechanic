# Pocket_Mechanic

A FastAPI service that looks up UK vehicles by registration, keeps a garage of
them, and serves maintenance guides tailored to the car in question.

## Running it

```bash
pip install -r requirements.txt
cp .env.example .env        # then add your real Zyfy API key
cd src && uvicorn main:app --reload
```

## Maintenance guides

Guides are built in three layers so that a car we know nothing about still gets
a usable answer, and a car we know a lot about gets an accurate one.

| Layer | Lives in | What it holds | Status |
| --- | --- | --- | --- |
| 1. Generic procedure | `Data/guides/*.json` | Steps, tools, safety notes — identical for every car | Populated |
| 2. Attribute rules | `Data/guide_rules.json` | Conditional edits keyed on vehicle *attributes*, not model names | Populated |
| 2a. Trait lookup | `Data/vehicle_traits.json` | Which attributes a given car has | **Not present — needs sourced data** |
| 3. Per-car specs | `Data/vehicle_specs.json` | Torque figures, part numbers, capacities | **Not present — needs sourced data** |

Layer 2 is what makes this tractable. Rules fire on traits (`epb`,
`rear_piston_type`, `start_stop`, `dpf`, …) rather than on make and model, so a
few dozen rules cover the whole fleet.

Anything we cannot establish resolves to `"unknown"`, never to a guess — an
unknown trait produces a "check before you start" warning, and a missing spec
renders as *not on file* rather than a number someone might torque to. A wrong
`"no electric parking brake"` destroys a caliper; an honest `"unknown"` does not.

**Both lookup files are optional and currently absent**, so every trait resolves
to `"unknown"` and every spec to *not on file*. The API works fully in this
state — it simply gives cautious answers. Add the files only with figures
verified against a workshop manual or a licensed data source (HaynesPro,
Autodata, Alldata); a plausible-looking guess is worse than no entry at all,
because it silences the warning that would otherwise tell someone to check.

#### Schema for the two lookup files

Both match on `make` + optional `models` + optional `year_from`/`year_to`, and
the most specific match wins.

```jsonc
// Data/vehicle_traits.json
{
  "traits": [
    {
      "make": "Vauxhall",
      "models": ["Astra"],          // omit to match the whole make
      "year_from": 2009,
      "year_to": 2015,              // omit for open-ended
      "set": {                      // omit any key you cannot verify
        "epb": false,
        "rear_brake_type": "disc",  // disc | drum
        "rear_piston_type": "screw" // push | screw | none
      }
    }
  ]
}
```

Recognised trait keys: `epb`, `rear_brake_type`, `rear_piston_type`,
`wear_sensor`, `start_stop`, `bms_registration`, `battery_location`,
`has_dipstick`. Omitting a key is always safe; guessing one is not.

```jsonc
// Data/vehicle_specs.json
{
  "specs": [
    {
      "make": "Vauxhall",
      "models": ["Astra"],
      "year_from": 2009,
      "source": "Haynes 5578, table 2.1",   // cite it, it is shown in the API response
      "jobs": {
        "brake-pads": { "wheel_nut_torque_nm": 110 }
      }
    }
  ]
}
```

Spec keys come from the `specs` block of each guide in `Data/guides/`.

Before populating either file, read
[`docs/REQUIREMENTS.md`](docs/REQUIREMENTS.md) — it carries the acceptance
criteria for sourcing this data and two lessons from the first attempt.

### Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/guides` | List all guides |
| `GET` | `/guides/{job_id}` | One guide, untailored |
| `GET` | `/garage/{registration}/guides` | Guides ranked against that car's MOT failure and advisory history |
| `GET` | `/garage/{registration}/guides/{job_id}` | One guide, tailored to that car |

Jobs that vary by axle take `?axle=front` or `?axle=rear`:

```
GET /garage/AB18XYZ/guides/brake-pads?axle=rear
```

Each response carries `applied_rules` and a `because_of` field on every injected
step, tool and warning, so it is always clear why the guide says what it says.

### Adding a guide

Drop a JSON file in `Data/guides/`. The `id` is taken from the file's `id`
field, `mot_clusters` ties it to MOT categories for ranking, and any `specs` it
declares are looked up per-vehicle automatically. Add rules only where cars
genuinely diverge.
