from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ZoningLimitsRequest(BaseModel):
    model_config=ConfigDict(strict=True,extra='forbid',allow_inf_nan=False)
    zones:list[Annotated[str,Field(min_length=1,max_length=100)]]=Field(min_length=1,max_length=50)
    zone_areas:dict[str,Annotated[float,Field(gt=0,le=1e12)]]|None=None

    @model_validator(mode='after')
    def check_split(self):
        self.zones=[name.strip() for name in self.zones]
        if not all(self.zones) or len(set(self.zones))!=len(self.zones):
            raise ValueError('Zone names must be nonempty and unique')
        if self.zone_areas is not None and set(self.zone_areas)!=set(self.zones):
            raise ValueError('Area split must cover exactly the supplied zones')
        return self
