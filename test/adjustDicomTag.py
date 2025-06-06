#!/usr/bin/env python3

import sys
import uuid
import os
import subprocess
from datetime import datetime


def get_patient_age(study_date_str, birth_date_str):
    fmt = "%Y%m%d"
    try:
        study_date = datetime.strptime(study_date_str, fmt)
        birth_date = datetime.strptime(birth_date_str, fmt)
    except ValueError:
        return "000Y"
    age = study_date.year - birth_date.year
    if (study_date.month, study_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    return f"{age:03d}Y"


def generate_uids():
    root = "2.25"
    study_uid = f"{root}.{uuid.uuid4().int}"
    sop_uid = f"{root}.{uuid.uuid4().int}"
    return study_uid, sop_uid


def get_dicom_tag(dcm_file, tag):
    try:
        result = subprocess.run(
            ["dcmdump", dcm_file],
            capture_output=True,
            text=True,
            check=True
        )
        for line in result.stdout.splitlines():
            if tag in line:
                start = line.find('[')
                end = line.find(']')
                if start != -1 and end != -1:
                    return line[start + 1:end]
        return None
    except subprocess.CalledProcessError as e:
        print(f"Error running dcmdump on {dcm_file}: {e.stderr.decode().strip()}")
        return None
    except FileNotFoundError:
        print(f"Error: 'dcmdump' command not found. Make sure DCMTK is installed and in your PATH.")
        sys.exit(1)


def update_dicom_file(input_file, output_dir, study_id, study_uid, sop_uid, patient_age):
    os.makedirs(output_dir, exist_ok=True)
    base_name = os.path.basename(input_file)
    output_file = os.path.join(output_dir, base_name)

    try:
        subprocess.run(["cp", input_file, output_file], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error copying {input_file} to {output_file}: {e}")
        return
    except FileNotFoundError:
        print(f"Error: 'cp' command not found. This should not happen on most systems.")
        sys.exit(1)

    dcmodify_cmd = [
        "dcmodify", "-nb",
        f"-i", f"0008,0018={sop_uid}",
        f"-i", f"0010,1010={patient_age}",
        f"-i", f"0020,0010={study_id}",
        f"-i", f"0020,000D={study_uid}",
        output_file
    ]

    try:
        subprocess.run(dcmodify_cmd, check=True, capture_output=True)
        print(f"Processed {base_name}")
        print(f"  StudyID: {study_id}")
        print(f"  StudyInstanceUID: {study_uid}")
        print(f"  SOPInstanceUID: {sop_uid}")
        print(f"  PatientAge: {patient_age}")
    except subprocess.CalledProcessError as e:
        print(f"Error modifying {base_name}: {e.stderr.decode().strip()}")
    except FileNotFoundError:
        print("Error: 'dcmodify' command not found. Make sure DCMTK is installed and in your PATH.")
        sys.exit(1)


def main():
    input_dir = sys.argv[1] if len(sys.argv) > 1 else "."
    base_output_dir = sys.argv[2] if len(sys.argv) > 2 else "modified_dicom"

    input_dir = os.path.abspath(input_dir)
    base_output_dir = os.path.abspath(base_output_dir)

    os.makedirs(base_output_dir, exist_ok=True)

    # Use a dictionary to cache study-level info (StudyID, StudyInstanceUID, PatientAge)
    study_level_info_cache = {}

    dicom_files = [f for f in os.listdir(input_dir) if f.endswith(".dcm")]

    if not dicom_files:
        print(f"No DICOM files found in '{input_dir}'")
        sys.exit(0)

    for file_name in dicom_files:
        full_path = os.path.join(input_dir, file_name)

        study_date = get_dicom_tag(full_path, "(0008,0020)")
        patient_id = get_dicom_tag(full_path, "(0010,0020)")
        birth_date = get_dicom_tag(full_path, "(0010,0030)")

        if not all([patient_id, birth_date, study_date]):
            print(f"Skipping {file_name} - missing PatientID, PatientBirthDate, or StudyDate")
            continue

        study_key = f"{patient_id}|{study_date}"

        if study_key in study_level_info_cache:
            study_data = study_level_info_cache[study_key]
        else:
            study_id = str(abs(hash(study_key)) % 900000 + 100000)
            study_uid, _ = generate_uids()
            patient_age = get_patient_age(study_date, birth_date)
            study_data = {
                "study_id": study_id,
                "study_uid": study_uid,
                "patient_age": patient_age
            }
            study_level_info_cache[study_key] = study_data

        _, new_sop_uid = generate_uids()

        output_dir = os.path.join(base_output_dir, study_data["study_id"])

        update_dicom_file(
            full_path,
            output_dir,
            study_data["study_id"],
            study_data["study_uid"],
            new_sop_uid,
            study_data["patient_age"]
        )

    print(f"\nDone. Modified files are in {os.path.abspath(output_dir)}")


if __name__ == "__main__":
    main()
