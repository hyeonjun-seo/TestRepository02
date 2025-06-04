from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


class PatientSchema(BaseModel):
    patient_key: int
    patient_id: str
    patient_sex: str
    patient_birth_date: str
    patient_age: Optional[str]
    created_date: datetime

    class Config:
        from_attributes = True


class ImageSchema(BaseModel):
    image_key: int
    image_uid: str
    laterality: str
    score: Optional[float]
    image_path: str
    created_date: datetime
    updated_date: datetime

    class Config:
        from_attributes = True


class StudySchema(BaseModel):
    study_key: int
    study_id: str
    study_uid: str
    study_date: str
    result: Optional[float]
    created_date: datetime
    updated_date: datetime

    patient: PatientSchema
    images: List[ImageSchema] = []

    class Config:
        from_attributes = True
