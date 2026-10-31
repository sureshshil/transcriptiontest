import os
import datetime
import json
import tracemalloc
import uuid
import requests
from azure.storage.blob import generate_blob_sas, BlobSasPermissions

SPEECH_ENDPOINT = "https://speech-poc-jp.cognitiveservices.azure.com"
SPEECH_KEY = os.getenv("SPEECH_KEY", "")
STORAGE_ACCOUNT = "fparecordingadls"
STORAGE_KEY = os.getenv("STORAGE_KEY", "")
CONTAINER_NAME = "fpa-recording"
BLOB_NAME = "wav/speech_10min_spoken.wav"

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB chunk


def stream_pipe_clean(sas_url, boundary, definition_json):
    yield (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="definition"\r\n'
        f"Content-Type: application/json\r\n\r\n{definition_json}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="audio.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8")

    # Pure raw stream from storage HTTP connection - NO Azure SDK buffering!
    with requests.get(sas_url, stream=True) as storage_resp:
        storage_resp.raise_for_status()
        for chunk_idx, chunk in enumerate(storage_resp.iter_content(chunk_size=CHUNK_SIZE)):
            cur, peak = tracemalloc.get_traced_memory()
            print(f"  Chunk #{chunk_idx}: len={len(chunk)/1024/1024:.2f}MB | Current RAM={cur/1024/1024:.2f}MB | Peak={peak/1024/1024:.2f}MB")
            yield chunk

    yield f"\r\n--{boundary}--\r\n".encode("utf-8")


def main():
    print("=" * 70)
    print("PURE HTTP PIPE STREAMING: ZERO SDK OVERHEAD MEMORY TRACE")
    print("=" * 70)

    # Generate internal SAS for raw streaming
    sas_token = generate_blob_sas(
        account_name=STORAGE_ACCOUNT,
        container_name=CONTAINER_NAME,
        blob_name=BLOB_NAME,
        account_key=STORAGE_KEY,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    )
    sas_url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER_NAME}/{BLOB_NAME}?{sas_token}"

    tracemalloc.start()
    tracemalloc.reset_peak()

    boundary = f"boundary_{uuid.uuid4().hex}"
    url = f"{SPEECH_ENDPOINT}/speechtotext/transcriptions:transcribe?api-version=2025-10-15"
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    definition_json = json.dumps({"locales": ["en-US"]})

    resp = requests.post(
        url,
        headers=headers,
        data=stream_pipe_clean(sas_url, boundary, definition_json),
    )
    resp.raise_for_status()
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print("=" * 70)
    print(f"FINAL RESULT:")
    print(f"  Active RAM at end:  {cur/1024/1024:.2f} MB")
    print(f"  ABSOLUTE PEAK RAM:  {peak/1024/1024:.2f} MB (Total process memory used)")
    print("=" * 70)


if __name__ == "__main__":
    main()
