from sqlalchemy import Column, Integer, String, DateTime, ForeignKey, func
from sqlalchemy.orm import relationship
from database import Base


class Patient(Base):
    __tablename__ = "patient"

    patient_key = Column(Integer, primary_key=True, index=True)

    patient_id = Column(String, unique=True, index=True)
    patient_sex = Column(String, nullable=False)
    patient_birth_date = Column(String, nullable=False)
    patient_age = Column(String)
    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    studies = relationship("Study", back_populates="patient", cascade="all, delete-orphan")


class Study(Base):
    __tablename__ = "study"

    study_key = Column(Integer, primary_key=True, index=True)
    patient_key = Column(Integer, ForeignKey("patient.patient_key", ondelete="CASCADE"), nullable=False)

    study_id = Column(String, unique=True, index=True)
    study_uid = Column(String, unique=True, index=True)
    study_date = Column(String, nullable=False)
    result = Column(Integer)
    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    patient = relationship("Patient", back_populates="studies")
    images = relationship("Image", back_populates="study", cascade="all, delete-orphan")


class Image(Base):
    __tablename__ = "image"

    image_key = Column(Integer, primary_key=True, index=True)
    study_key = Column(Integer, ForeignKey("study.study_key", ondelete="CASCADE"), nullable=False)

    image_uid = Column(String, unique=True, index=True)
    laterality = Column(String)
    score = Column(Integer)
    image_path = Column(String)
    created_date = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    study = relationship("Study", back_populates="images")
