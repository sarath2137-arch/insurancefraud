from datetime import date
from pydantic import BaseModel, Field, model_validator
class ClaimCreate(BaseModel):
    claim_id: str=Field(min_length=3,max_length=64); provider_id: str=Field(min_length=1,max_length=64, pattern=r'^\S+$'); patient_reference_id: str=Field(min_length=3,max_length=64); hospital: str=Field(min_length=2,max_length=150); patient_age:int=Field(ge=0,le=120); gender:str=Field(min_length=1,max_length=20); diagnosis:str=Field(min_length=2,max_length=200); treatment_type:str=Field(min_length=2,max_length=150); admission_date:date; discharge_date:date; claim_amount:float=Field(gt=0,le=100000000); previous_claims:int=Field(ge=0,le=1000); previous_claim_amount:float=Field(ge=0); provider_information:str=Field(min_length=2,max_length=300)
    @model_validator(mode='after')
    def dates(self):
        if self.discharge_date < self.admission_date: raise ValueError('Discharge date cannot precede admission date')
        return self
class StatusUpdate(BaseModel): status: str
