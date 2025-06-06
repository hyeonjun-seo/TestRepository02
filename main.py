import io
import os
from contextlib import asynccontextmanager
from typing import List

import aiofiles
import httpx
import pydicom
from PIL import Image as PILImage
from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, Path
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
        await conn.run_sync(Base.metadata.create_all)
    print("Database tables checked/created.")
    yield
    print("Application shutdown: Cleaning up...")


app = FastAPI(lifespan=lifespan)

PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
STORAGE_DIR = os.path.join(os.path.dirname(PROJECT_ROOT), "storage")
DICOM_DIR = os.path.join(STORAGE_DIR, "dicom")
IMAGE_DIR = os.path.join(STORAGE_DIR, "image")

os.makedirs(DICOM_DIR, exist_ok=True)
os.makedirs(IMAGE_DIR, exist_ok=True)

SCORING_API_URL = "http://apitest.mediwhale.net/predict"


@app.post("/dicom-web/study/{study_id}")
async def store_study(
        study_id: str = Path(...,
                             description="The StudyID (0020,0010) that all DICOM files in this request must belong to"),
        files: List[UploadFile] = File(...),
        db: AsyncSession = Depends(get_db)
):
    stored_files_info = []

    for file in files:
        if file.content_type != "application/dicom":
            raise HTTPException(status_code=415,
                                detail=f"Unsupported Media Type for {file.filename}. Only application/dicom is accepted.")

        content = await file.read()

        try:
            dicom_file_like = io.BytesIO(content)
            ds = pydicom.dcmread(dicom_file_like, force=True)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid DICOM file {file.filename}: {str(e)}")

        dcm_study_id = ds.get("StudyID")

        if not dcm_study_id or dcm_study_id != study_id:
            raise HTTPException(status_code=400,
                                detail=f"Mismatched StudyID for file {file.filename}. Path parameter '{study_id}' does not match DICOM StudyID '{dcm_study_id}'. All files must belong to the specified study_id.")

        dcm_study_date = ds.get("StudyDate")
        dcm_patient_id = ds.get("PatientID")
        dcm_patient_birth_date = ds.get("PatientBirthDate")
        dcm_patient_sex = ds.get("PatientSex")
        dcm_laterality = ds.get("Laterality")

        if not dcm_study_date:
            raise HTTPException(status_code=400,
                                detail=f"DICOM file {file.filename} is missing StudyDate (0008, 0020).")
        if not dcm_patient_id:
            raise HTTPException(status_code=400,
                                detail=f"DICOM file {file.filename} is missing PatientID (0010,0020).")
        if not dcm_patient_birth_date:
            raise HTTPException(status_code=400,
                                detail=f"DICOM file {file.filename} is missing PatientBirthDate (0010,0030).")
        if not dcm_patient_sex:
            raise HTTPException(status_code=400,
                                detail=f"DICOM file {file.filename} is missing PatientSex (0010,0040).")
        if not dcm_laterality:
            raise HTTPException(status_code=400,
                                detail=f"DICOM file {file.filename} is missing Laterality (0020,0060).")

        dcm_image_uid = ds.get("SOPInstanceUID")
        filename = f"{dcm_image_uid}.dcm"
        filepath = os.path.join(DICOM_DIR, filename)
        absolute_filepath = os.path.abspath(filepath)

        if os.path.exists(absolute_filepath):
            print(
                f"Warning: File {filename} (SOPInstanceUID: {dcm_image_uid}) already exists. Skipping write to disk, but processing DB.")
        else:
            async with aiofiles.open(absolute_filepath, 'wb') as out_file:
                await out_file.write(content)

        extracted_image_bytes = None
        extracted_image_filename = None

        if "PixelData" in ds:
            try:
                pixel_array = ds.pixel_array
                if pixel_array.dtype != 'uint8':
                    pixel_array = (pixel_array - pixel_array.min()) / (pixel_array.max() - pixel_array.min())
                    pixel_array = (pixel_array * 255).astype('uint8')

                pil_image = PILImage.fromarray(pixel_array)

                extracted_image_filename = f"{dcm_image_uid}.png"
                extracted_image_filepath = os.path.join(IMAGE_DIR, extracted_image_filename)
                absolute_extracted_image_filepath = os.path.abspath(extracted_image_filepath)

                pil_image.save(absolute_extracted_image_filepath, format="PNG")
                print(f"Pixel data extracted and saved as {extracted_image_filename}.")

                img_byte_arr = io.BytesIO()
                pil_image.save(img_byte_arr, format="PNG")
                extracted_image_bytes = img_byte_arr.getvalue()

            except Exception as e:
                print(f"Error extracting and saving pixel data for {file.filename}: {str(e)}")
        else:
            print(f"No pixel data found in DICOM file {file.filename}. Skipping image extraction and scoring.")

        image_score = None
        if extracted_image_bytes and extracted_image_filename:
            try:
                async with httpx.AsyncClient() as client:
                    files_to_predict = {
                        'file': (extracted_image_filename, extracted_image_bytes, 'image/png')
                    }
                    response = await client.post(
                        SCORING_API_URL,
                        files=files_to_predict
                    )
                    response.raise_for_status()
                    scoring_result = response.json()
                    image_score = scoring_result.get("score")

                    if image_score is None:
                        print(
                            f"Warning: Scoring API did not return a 'score' for {dcm_image_uid}. Response: {scoring_result}")
                        image_score = 0.0
                    else:
                        print(f"Received score for {dcm_image_uid}: {image_score}")

            except httpx.RequestError as e:
                print(f"Error making request to scoring API for {file.filename}: {e}")
                image_score = 0.0
            except Exception as e:
                print(f"Error processing scoring API response for {file.filename}: {e}")
                image_score = 0.0
        else:
            print(f"No extracted image data to send to scoring API for {file.filename}.")
            image_score = 0.0

        # Patient
        patient = (await db.execute(select(Patient).where(Patient.patient_id == dcm_patient_id))).scalars().first()
        if not patient:
            patient = Patient(
                patient_id=dcm_patient_id,
                patient_sex=dcm_patient_sex,
                patient_birth_date=dcm_patient_birth_date,
                patient_age=ds.get("PatientAge")
            )
            db.add(patient)
            await db.flush()
            print(f"New Patient '{dcm_patient_id}' created.")

        # Study
        study = (await db.execute(select(Study).where(Study.study_id == study_id))).scalars().first()
        if not study:
            study = Study(
                patient_key=patient.patient_key,
                study_id=study_id,
                study_uid=ds.get("StudyInstanceUID"),
                study_date=dcm_study_date,
                result=0
            )
            db.add(study)
            await db.flush()
            print(f"New Study '{study_id}' created with patient data.")

        # Image
        image = (await db.execute(select(Image).where(
            Image.image_uid == dcm_image_uid
        ))).scalars().first()

        if image:
            image_key_to_return = image.image_key
            image.score = image_score
            db.add(image)
            await db.flush()
            print(f"Updated Image '{dcm_image_uid}' with new paths and score.")
        else:
            image = Image(
                study_key=study.study_key,
                image_uid=dcm_image_uid,
                laterality=dcm_laterality,
                score=image_score,
                image_path=absolute_filepath
            )
            db.add(image)
            await db.flush()
            print(f"New Image '{dcm_image_uid}' created for Study '{study_id}' with score: {image_score}.")
            image_key_to_return = image.image_key

        # Commit inside the loop is less efficient but ensures partial data if a file fails later.
        # For better performance with multiple files, consider committing outside the loop
        # and rolling back all if any file fails, but that requires more complex error handling.
        await db.commit()

        stored_files_info.append({
            "image_key": image_key_to_return,
            "file_name": filename,
            "score": image_score
        })

    return JSONResponse(content={"stored_files": stored_files_info})


@app.get("/dicom-web/study", response_model=List[StudySchema])
async def query_studies(db: AsyncSession = Depends(get_db)):
    query = select(Study).options(
        selectinload(Study.patient),
        selectinload(Study.images)
    )

    try:
        studies = (await db.execute(query)).scalars().all()
        return [StudySchema.model_validate(study) for study in studies]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database Error: {str(e)}")


@app.get("/dicom-web/study/{study_id}", response_model=StudySchema)
async def query_study(study_id: str = Path(..., description="The ID of the study to retrieve"),
                      db: AsyncSession = Depends(get_db)):
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
