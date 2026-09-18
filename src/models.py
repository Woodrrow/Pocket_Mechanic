from typing import Optional
from pydantic import BaseModel

class CarPayload(BaseModel):
    car_id: Optional[int]
    car_name: str
    year: int