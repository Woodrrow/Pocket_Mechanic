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

| Layer | Lives in | What it holds |
| --- | --- | --- |
| 1. Generic procedure | `Data/guides/*.json` | Steps, tools, safety notes — identical for every car |
| 2. Attribute rules | `Data/guide_rules.json` | Conditional edits keyed on vehicle *attributes*, not model names |
| 3. Per-car specs | `Data/vehicle_specs.json` | Torque figures, part numbers, capacities |

Layer 2 is what makes this tractable. Rules fire on traits (`epb`,
`rear_piston_type`, `start_stop`, `dpf`, …) rather than on make and model, so a
few dozen rules cover the whole fleet. Traits themselves are resolved from
`Data/vehicle_traits.json`.

Anything we cannot establish resolves to `"unknown"`, never to a guess — an
unknown trait produces a "check before you start" warning, and a missing spec
renders as *not on file* rather than a number someone might torque to. A wrong
`"no electric parking brake"` destroys a caliper; an honest `"unknown"` does not.

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
