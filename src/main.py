from fastapi import FastAPI, HTTPException

from models import CarPayload
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
