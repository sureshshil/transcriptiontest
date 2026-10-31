import json
import os
import tempfile
import time
import tracemalloc
import requests
from azure.storage.blob import BlobServiceClient

SPEECH_ENDPOINT = "https://speech-poc-jp.cognitiveservices.azure.com"
SPEECH_KEY = os.getenv("SPEECH_KEY", "")
STORAGE_ACCOUNT = "fparecordingadls"
STORAGE_KEY = os.getenv("STORAGE_KEY", "")
CONTAINER_NAME = "fpa-recording"
BLOB_NAME = "wav/speech_10min_spoken.wav"

conn_str = (
    f"DefaultEndpointsProtocol=https;AccountName={STORAGE_ACCOUNT};"
    f"AccountKey={STORAGE_KEY};EndpointSuffix=core.windows.net"
)


def run_temp_file_test():
    print("=" * 70)
    print("BENCHMARK: USING DISK / TEMP FILE IN POD (/tmp)")
    print("=" * 70)

    service = BlobServiceClient.from_connection_string(conn_str)
    blob_client = service.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)

    tracemalloc.start()
    tracemalloc.reset_peak()
    t0 = time.perf_counter()

    # Step 1: Download directly to a temp file on disk (bypassing Python RAM!)
    t_down_start = time.perf_counter()
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
        tmp_path = tmp_file.name
        # Stream download directly into disk file descriptor
        downloader = blob_client.download_blob(max_concurrency=4)
        downloader.readinto(tmp_file)
    t_down = time.perf_counter() - t_down_start
    file_size_mb = os.path.getsize(tmp_path) / 1024 / 1024
    print(f"[*] Step 1: Downloaded to {tmp_path} ({file_size_mb:.2f} MB) in {t_down:.3f} s")

    # Step 2: Stream upload from disk using native file handle
    t_up_start = time.perf_counter()
    url = f"{SPEECH_ENDPOINT}/speechtotext/transcriptions:transcribe?api-version=2025-10-15"
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
    }
    definition_json = json.dumps({"locales": ["en-US"]})

    with open(tmp_path, "rb") as f_disk:
        files = {
            "definition": (None, definition_json, "application/json"),
            "audio": ("audio.wav", f_disk, "audio/wav"),
        }
        resp = requests.post(url, headers=headers, files=files)
        resp.raise_for_status()

    t_up = time.perf_counter() - t_up_start
    t_total = time.perf_counter() - t0
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Step 3: Clean up temp file
    if os.path.exists(tmp_path):
        os.remove(tmp_path)
    print(f"[*] Step 2: Upload + Transcribe completed in {t_up:.3f} s")
    print(f"[*] Step 3: Temp file cleaned up successfully.")
    print("-" * 70)
    print(f"TOTAL LATENCY:                 {t_total:.3f} s")
    print(f"PEAK PYTHON PROCESS RAM:       {peak / 1024 / 1024:.2f} MB")
    print("=" * 70)


if __name__ == "__main__":
    run_temp_file_test()
