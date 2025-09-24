import os
import csv
from google.cloud import firestore, storage

def gcs_to_firestore(event, context):
    bucket_name = event['bucket']
    file_name = event['name']

    if not file_name.startswith("csv/"):
        return

    storage_client = storage.Client()
    bucket = storage_client.bucket(bucket_name)
    blob = bucket.blob(file_name)
    data = blob.download_as_text().splitlines()

    reader = csv.DictReader(data)
    db = firestore.Client()

    for row in reader:
        # Simpan ke Firestore dengan auto ID
        db.collection("landslide_reports").add({
            "date": row.get("date"),
            "location": row.get("location"),
            "description": row.get("description"),
            "photo_url": row.get("photo_url"),
            "uploaded_at": firestore.SERVER_TIMESTAMP
        })
