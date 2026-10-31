import os
import json
import time
import tracemalloc
import uuid
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


def stream_multipart_from_blob(blob_client, boundary, definition_json):
    """
    True zero-buffering multipart/form-data generator.
    Yields multipart headers, then yields raw chunks directly from Azure Blob Storage's
    native `.chunks()` iterator onto the HTTP socket, then yields the closing boundary.
    """
    # Part 1: definition JSON
    yield (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="definition"\r\n'
        f"Content-Type: application/json\r\n\r\n"
        f"{definition_json}\r\n"
    ).encode("utf-8")

    # Part 2: audio file header
    yield (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="audio.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8")

    # Stream chunks directly from Azure Storage downloader onto the wire!
    downloader = blob_client.download_blob()
    for chunk in downloader.chunks():
        yield chunk

    # Closing boundary
    yield f"\r\n--{boundary}--\r\n".encode("utf-8")


def run_benchmark():
    print("=" * 70)
    print("TRUE ZERO-BUFFER STREAMING vs SDK MULTIPART BUFFERING (WITH RAM TRACE)")
    print("=" * 70)

    # 1. Test what the SDK (`files=`) actually does to RAM
    from azure.core.credentials import AzureKeyCredential
    from azure.ai.transcription import TranscriptionClient
    from azure.ai.transcription.models import TranscriptionOptions, TranscriptionContent

    service_4mb = BlobServiceClient.from_connection_string(
        conn_str, max_single_get_size=4 * 1024 * 1024, max_chunk_get_size=4 * 1024 * 1024
    )
    blob_client_4mb = service_4mb.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)
    speech_client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))

    tracemalloc.start()
    t0 = time.perf_counter()
    res_sdk = speech_client.transcribe(
        TranscriptionContent(
            definition=TranscriptionOptions(locales=["en-US"]),
            audio=blob_client_4mb.download_blob(),
        )
    )
    t_sdk = time.perf_counter() - t0
    _, peak_sdk = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"1. SDK `client.transcribe` (urllib3 files=): {t_sdk:.3f} s | Peak Python RAM: {peak_sdk / 1024 / 1024:.2f} MB")

    # 2. Test TRUE Zero-Buffer Streaming Generator (`data=generator`) with 4MB chunks
    tracemalloc.start()
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
        data=stream_multipart_from_blob(blob_client_4mb, boundary, definition_json),
    )
    resp.raise_for_status()
    res_true_stream = resp.json()
    t_true_4mb = time.perf_counter() - t0
    _, peak_true_4mb = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"2. True Chunked Generator (4MB chunks):      {t_true_4mb:.3f} s | Peak Python RAM: {peak_true_4mb / 1024 / 1024:.2f} MB")

    # 3. Test TRUE Zero-Buffer Streaming Generator (`data=generator`) with 16MB chunks
    service_16mb = BlobServiceClient.from_connection_string(
        conn_str, max_single_get_size=16 * 1024 * 1024, max_chunk_get_size=16 * 1024 * 1024
    )
    blob_client_16mb = service_16mb.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)

    tracemalloc.start()
    t0 = time.perf_counter()
    boundary = f"boundary_{uuid.uuid4().hex}"
    headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
    resp = requests.post(
        url,
        headers=headers,
        data=stream_multipart_from_blob(blob_client_16mb, boundary, definition_json),
    )
    resp.raise_for_status()
    t_true_16mb = time.perf_counter() - t0
    _, peak_true_16mb = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(f"3. True Chunked Generator (16MB chunks):     {t_true_16mb:.3f} s | Peak Python RAM: {peak_true_16mb / 1024 / 1024:.2f} MB")
    print("=" * 70)


if __name__ == "__main__":
    run_benchmark()
