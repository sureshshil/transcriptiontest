import sys
import time
import tracemalloc
import requests
import json
import uuid
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionOptions
from azure.storage.blob import generate_blob_sas, BlobSasPermissions
from test_pure_stream_low_ram import (
    SPEECH_ENDPOINT,
    SPEECH_KEY,
    STORAGE_ACCOUNT,
    STORAGE_KEY,
    CONTAINER_NAME,
    BLOB_NAME,
    CHUNK_SIZE,
)

PLAIN_URL = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER_NAME}/{BLOB_NAME}"

# Read token passed as command line argument
STORAGE_TOKEN = sys.argv[1] if len(sys.argv) > 1 else ""


class ManagedIdentityAudioStream:
    def __init__(self, url, bearer_token, chunk_size=CHUNK_SIZE):
        headers = {
            "Authorization": f"Bearer {bearer_token}",
            "x-ms-version": "2021-08-06",
        }
        self.response = requests.get(url, headers=headers, stream=True)
        self.response.raise_for_status()
        self.chunk_iter = self.response.iter_content(chunk_size=chunk_size)

    def read(self, size=-1):
        try:
            return next(self.chunk_iter)
        except StopIteration:
            return b""


def test_sdk_managed_identity():
    client = TranscriptionClient(
        endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY)
    )

    tracemalloc.start()
    tracemalloc.reset_peak()
    t0 = time.perf_counter()

    stream = ManagedIdentityAudioStream(PLAIN_URL, STORAGE_TOKEN)
    res = client.transcribe(
        {
            "definition": TranscriptionOptions(locales=["en-US"]),
            "audio": ("audio.wav", stream, "audio/wav"),
        }
    )
    elapsed = time.perf_counter() - t0
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return elapsed, peak / 1024 / 1024, len(res.phrases)


def stream_pipe_clean(sas_url, boundary, definition_json):
    yield (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="definition"\r\n'
        f"Content-Type: application/json\r\n\r\n{definition_json}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="audio.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8")

    with requests.get(sas_url, stream=True) as storage_resp:
        storage_resp.raise_for_status()
        for chunk in storage_resp.iter_content(chunk_size=CHUNK_SIZE):
            yield chunk

    yield f"\r\n--{boundary}--\r\n".encode("utf-8")


def test_pure_rest_generator():
    import datetime

    sas_token = generate_blob_sas(
        account_name=STORAGE_ACCOUNT,
        container_name=CONTAINER_NAME,
        blob_name=BLOB_NAME,
        account_key=STORAGE_KEY,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.datetime.now(datetime.timezone.utc)
        + datetime.timedelta(hours=1),
    )
    sas_url = f"{PLAIN_URL}?{sas_token}"

    tracemalloc.start()
    tracemalloc.reset_peak()
    t0 = time.perf_counter()

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
    elapsed = time.perf_counter() - t0
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return elapsed, peak / 1024 / 1024, len(resp.json().get("phrases", []))


def main():
    print("=" * 70)
    print("HEAD-TO-HEAD BENCHMARK: SDK + PLAIN URL vs PURE REST GENERATOR")
    print("=" * 70)

    print("\n[*] Method 1: SDK Transcribe with Plain URL (Managed Identity)...")
    t_sdk, ram_sdk, phrases_sdk = test_sdk_managed_identity()
    print(f"    Elapsed: {t_sdk:.3f} s | Peak RAM: {ram_sdk:.2f} MB | Phrases: {phrases_sdk}")

    print("\n[*] Method 2: Pure REST Generator with SAS URL...")
    t_rest, ram_rest, phrases_rest = test_pure_rest_generator()
    print(f"    Elapsed: {t_rest:.3f} s | Peak RAM: {ram_rest:.2f} MB | Phrases: {phrases_rest}")

    print("\n" + "=" * 70)
    print("COMPARISON SUMMARY")
    print("=" * 70)
    print(f"{'Method':<42} | {'Latency':<12} | {'Peak RAM':<12}")
    print("-" * 70)
    print(f"{'1. SDK Transcribe + Plain URL (MI)':<42} | {t_sdk:.3f} s     | {ram_sdk:.2f} MB")
    print(f"{'2. Pure REST Generator + SAS URL':<42} | {t_rest:.3f} s     | {ram_rest:.2f} MB")
    diff = t_sdk - t_rest
    print("-" * 70)
    print(f"Difference: {'+' if diff >= 0 else ''}{diff:.3f} s ({abs(diff)/t_rest*100:.1f}%)")
    print("=" * 70)


if __name__ == "__main__":
    main()
