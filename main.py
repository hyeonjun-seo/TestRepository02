import os
import io
from typing import List
from contextlib import asynccontextmanager

import aiofiles
import pydicom
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from database import get_db, engine, Base
from model import Patient, Study, Image
from schema import StudySchema


@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Application startup: Checking database tables...")
    async with engine.begin() as conn:
        # This will create tables if they do not exist.
        # It will NOT alter tables if your models change (for that, use Alembic).
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables checked/created.")
    yield
    # Shutdown logic (optional, for cleanup if needed)
    print("Application shutdown: Cleaning up...")
    # Add any cleanup code here if necessary, e.g., closing connections.


app = FastAPI(lifespan=lifespan)

UPLOAD_DIR = "dicom_storage"
os.makedirs(UPLOAD_DIR, exist_ok=True)


@app.post("/dicom-web/studies")
async def store_studies(files: List[UploadFile] = File(...), db: AsyncSession = Depends(get_db)):
    stored_files_info = []

    for file in files:
        if file.content_type != "application/dicom":
            raise HTTPException(status_code=415,
                                detail=f"Unsupported Media Type for {file.filename}. Only application/dicom is accepted.")

        content = await file.read()

        try:
            # Wrap the bytes content in a BytesIO object
            dicom_file_like = io.BytesIO(content)
            # Use pydicom.dcmread with a BytesIO object or from a byte string
            # to avoid writing to a temporary file just to read the UID.
            ds = pydicom.dcmread(dicom_file_like, force=True)  # force=True to handle some non-conformant files
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid DICOM file {file.filename}: {str(e)}")

        study_date = ds.get("StudyDate")
        patient_id = ds.get("PatientID")
        patient_birth_date = ds.get("PatientBirthDate")
        patient_sex = ds.get("PatientSex")
        study_id = ds.get("StudyID")
        laterality = ds.get("Laterality")

        if not study_date:
            raise HTTPException(status_code=400,
                                detail=f"DICOM file {file.filename} is missing StudyInstanceUID (0008, 0020).")
        if not patient_id:
            raise HTTPException(status_code=400,
                                detail=f"DICOM file {file.filename} is missing PatientID (0010,0020).")
        if not patient_birth_date:
            raise HTTPException(status_code=400,
                                detail=f"DICOM file {file.filename} is missing PatientBirthDate (0010,0030).")
        if not patient_sex:
            raise HTTPException(status_code=400,
                                detail=f"DICOM file {file.filename} is missing PatientSex (0010,0040).")
        if not study_id:
            raise HTTPException(status_code=400, detail=f"DICOM file {file.filename} is missing StudyID (0020,0010).")
        if not laterality:
            raise HTTPException(status_code=400,
                                detail=f"DICOM file {file.filename} is missing Laterality (0020,0060).")

        image_uid = ds.get("SOPInstanceUID")
        filename = f"{image_uid}.dcm"
        filepath = os.path.join(UPLOAD_DIR, filename)
        absolute_filepath = os.path.abspath(filepath)

        if os.path.exists(absolute_filepath):
            print(
                f"Warning: File {filename} (SOPInstanceUID: {image_uid}) already exists. Skipping write to disk, but processing DB.")
        else:
            async with aiofiles.open(absolute_filepath, 'wb') as out_file:
                await out_file.write(content)

        # Patient
        patient = (await db.execute(select(Patient).where(Patient.patient_id == patient_id))).scalars().first()
        if not patient:
            patient = Patient(
                patient_id=patient_id,
                patient_sex=patient_sex,
                patient_birth_date=patient_birth_date,
                patient_age=ds.get("PatientAge")
            )
            db.add(patient)
            await db.flush()
            print(f"New Patient '{patient_id}' created.")

        # Study
        study = (await db.execute(select(Study).where(Study.study_id == study_id))).scalars().first()
        if not study:
            study = Study(
                patient_key=patient.patient_key,
                study_id=study_id,
                study_uid=ds.get("StudyInstanceUID"),
                study_date=study_date,
                result=0
            )
            db.add(study)
            await db.flush()
            print(f"New Study '{study_id}' created with patient data.")

        # Image
        image = (await db.execute(select(Image).where(
            # Patient.patient_key == patient.patient_key,
            # Image.study_key == study.study_key,
            Image.image_uid == image_uid
        ))).scalars().first()

        if image:
            image_key_to_return = image.image_key
        else:
            image = Image(
                study_key=study.study_key,
                image_uid=image_uid,
                laterality=laterality,
                score=0,
                image_path=absolute_filepath
            )
            db.add(image)
            await db.flush()
            print(f"New Image '{image_uid}' created for Study '{study_id}'.")
            image_key_to_return = image.image_key

        await db.commit()

        stored_files_info.append({
            "image_key": image_key_to_return,
            "file_name": filename
        })

    return JSONResponse(content={"stored_files": stored_files_info})


@app.get("/dicom-web/studies", response_model=List[StudySchema])
async def query_all_study(db: AsyncSession = Depends(get_db)):
    query = select(Study).options(
        selectinload(Study.patient),
        selectinload(Study.images)
    )

    try:
        studies = (await db.execute(query)).scalars().all()
        return [StudySchema.model_validate(study) for study in studies]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database Error: {str(e)}")


@app.get("/dicom-web/studies/{study_id}", response_model=StudySchema)
async def query_one_study(study_id: str | None = None, db: AsyncSession = Depends(get_db)):
    query = select(Study).options(
        selectinload(Study.patient),
        selectinload(Study.images)
    ).where(Study.study_id == study_id)

    try:
        study = (await db.execute(query)).scalars().first()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database Error: {str(e)}")

    if not study:
        raise HTTPException(status_code=404, detail=f"Study with ID '{study_id}' not found.")

    return StudySchema.model_validate(study)
