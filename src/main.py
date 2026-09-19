from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException
import json
from models import CarPayload
from pathlib import Path

from garage_store import add_vehicle, load_garage
from zyfy_client import ZyfyError, lookup_vehicle

app = FastAPI()
cars: dict[int, CarPayload] = {}


# Route to home page (home)
@app.get("/")
async def root():
    return {"message": "Hello World"}


# Route to add cars (add_car)
@app.post("/cars/{car_name}/{year}")
def create_car(car_name: str, year: int):
    if any(car.car_name == car_name and car.year == year for car in cars.values()):
        raise HTTPException(status_code=400, detail="Car already exists")
    else:
        car_id = len(cars) + 1
        car_payload = CarPayload(car_id=car_id, car_name=car_name, year=year)
        cars[car_id] = car_payload
        return {"message": "Car created successfully", "car": car_payload}


# Route to get cars (get_cars)
@app.get("/cars")
def get_cars():
    return {"cars": list(cars.values())}


# Route to add a car to the garage by registration, via the Zyfy Vehicle API (add_car_to_garage)
@app.post("/garage/{registration}")
def add_car_to_garage(registration: str):
    try:
        vehicle_data = lookup_vehicle(registration)
    except ZyfyError as exc:
        raise HTTPException(status_code=502, detail=str(exc))

    record = {
        "registration": vehicle_data.get("registration", registration.upper()),
        "added_at": datetime.now(timezone.utc).isoformat(),
        "vehicle": vehicle_data,
    }
    garage = add_vehicle(record)
    return {"message": "Vehicle added to garage", "car": record, "garage_size": len(garage)}


# Route to list all cars in the garage (get_garage)
@app.get("/garage")
def get_garage():
    return {"garage": load_garage()}
