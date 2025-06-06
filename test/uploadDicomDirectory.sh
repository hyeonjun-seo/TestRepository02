#!/bin/bash

DICOM_DIR=${1:-"modified_dicom"}
STUDY_ID=$(basename "$DICOM_DIR")
API_URL="http://localhost:18000/dicom-web/study/$STUDY_ID"
CURL_COMMAND="curl -X POST \"$API_URL\" -H \"Content-Type: multipart/form-data\""

for dicom_file in "$DICOM_DIR"/*.dcm; do
    if [ -f "$dicom_file" ]; then
        CURL_COMMAND+=" -F \"files=@$dicom_file;type=application/dicom\""
    fi
done

echo "Executing: $CURL_COMMAND"
eval "$CURL_COMMAND"