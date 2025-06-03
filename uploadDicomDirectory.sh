#!/bin/bash

DICOM_DIR="modified_dicom"
API_URL="http://localhost:8000/dicom-web/studies"

CURL_COMMAND="curl -X POST \"$API_URL\" -H \"Content-Type: multipart/form-data\""

for dicom_file in "$DICOM_DIR"/*.dcm; do
    if [ -f "$dicom_file" ]; then
        CURL_COMMAND+=" -F \"files=@$dicom_file;type=application/dicom\""
    fi
done

echo "Executing: $CURL_COMMAND"
eval "$CURL_COMMAND"