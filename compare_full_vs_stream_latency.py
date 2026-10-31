import os
import json
import time
import tracemalloc
import uuid
import requests
from azure.storage.blob import BlobServiceClient
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionOptions

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


def stream_multipart_generator(blob_client, boundary, definition_json):
    yield (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="definition"\r\n'
        f"Content-Type: application/json\r\n\r\n{definition_json}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="audio.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8")

    downloader = blob_client.download_blob()
    for chunk in downloader.chunks():
        yield chunk

    yield f"\r\n--{boundary}--\r\n".encode("utf-8")


def run_benchmark():
    print("=" * 70)
    print("HEAD-TO-HEAD LATENCY COMPARISON ON AZURE VM (10-MIN AUDIO, 25.23 MB)")
    print("=" * 70)

    url = f"{SPEECH_ENDPOINT}/speechtotext/transcriptions:transcribe?api-version=2025-10-15"
    definition_json = json.dumps({"locales": ["en-US"]})

    # -------------------------------------------------------------
    # METHOD A: Full Audio Download At Once (Single Shot)
    # -------------------------------------------------------------
    service_full = BlobServiceClient.from_connection_string(conn_str)
    blob_client_full = service_full.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)

    tracemalloc.start()
    t0 = time.perf_counter()
    
    t_down_start = time.perf_counter()
    audio_bytes = blob_client_full.download_blob(max_concurrency=4).readall()
    t_down = time.perf_counter() - t_down_start

    t_up_start = time.perf_counter()
    boundary_a = f"boundary_{uuid.uuid4().hex}"
    body_a = (
        f"--{boundary_a}\r\n"
        f'Content-Disposition: form-data; name="definition"\r\n'
        f"Content-Type: application/json\r\n\r\n{definition_json}\r\n"
        f"--{boundary_a}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="audio.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8") + audio_bytes + f"\r\n--{boundary_a}--\r\n".encode("utf-8")

    headers_a = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": f"multipart/form-data; boundary={boundary_a}",
    }
    resp_a = requests.post(url, headers=headers_a, data=body_a)
    resp_a.raise_for_status()
    t_up_and_transcribe = time.perf_counter() - t_up_start
    t_total_a = time.perf_counter() - t0
    _, peak_ram_a = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\n[A] Full Download at Once:")
    print(f"    - Download time from ADLS:       {t_down:.3f} s")
    print(f"    - Upload + Transcription time:   {t_up_and_transcribe:.3f} s")
    print(f"    - TOTAL LATENCY:                 {t_total_a:.3f} s")
    print(f"    - Peak RAM Allocated:            {peak_ram_a / 1024 / 1024:.2f} MB")

    # -------------------------------------------------------------
    # METHOD B: True Chunked Streaming (4MB Chunks)
    # -------------------------------------------------------------
    service_4mb = BlobServiceClient.from_connection_string(
        conn_str, max_single_get_size=4 * 1024 * 1024, max_chunk_get_size=4 * 1024 * 1024
    )
    blob_client_4mb = service_4mb.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)

    tracemalloc.start()
    t0 = time.perf_counter()
    boundary_b = f"boundary_{uuid.uuid4().hex}"
    headers_b = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": f"multipart/form-data; boundary={boundary_b}",
    }
    resp_b = requests.post(
        url,
        headers=headers_b,
        data=stream_multipart_generator(blob_client_4mb, boundary_b, definition_json),
    )
    resp_b.raise_for_status()
    t_total_b = time.perf_counter() - t0
    _, peak_ram_b = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\n[B] True Chunked Streaming (4MB Chunks):")
    print(f"    - Download & Upload:             Pipelined concurrently on socket")
    print(f"    - TOTAL LATENCY:                 {t_total_b:.3f} s")
    print(f"    - Peak RAM Allocated:            {peak_ram_b / 1024 / 1024:.2f} MB")

    # -------------------------------------------------------------
    # METHOD C: True Chunked Streaming (16MB Chunks)
    # -------------------------------------------------------------
    service_16mb = BlobServiceClient.from_connection_string(
        conn_str, max_single_get_size=16 * 1024 * 1024, max_chunk_get_size=16 * 1024 * 1024
    )
    blob_client_16mb = service_16mb.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)

    tracemalloc.start()
    t0 = time.perf_counter()
    boundary_c = f"boundary_{uuid.uuid4().hex}"
    headers_c = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": f"multipart/form-data; boundary={boundary_c}",
    }
    resp_c = requests.post(
        url,
        headers=headers_c,
        data=stream_multipart_generator(blob_client_16mb, boundary_c, definition_json),
    )
    resp_c.raise_for_status()
    t_total_c = time.perf_counter() - t0
    _, peak_ram_c = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"\n[C] True Chunked Streaming (16MB Chunks):")
    print(f"    - Download & Upload:             Pipelined concurrently on socket")
    print(f"    - TOTAL LATENCY:                 {t_total_c:.3f} s")
    print(f"    - Peak RAM Allocated:            {peak_ram_c / 1024 / 1024:.2f} MB")

    print("\n" + "=" * 70)
    print("SUMMARY COMPARISON TABLE")
    print("=" * 70)
    print(f"{'Method':<35} | {'Total Latency':<15} | {'Peak RAM':<12}")
    print("-" * 70)
    print(f"{'[A] Full Download at Once':<35} | {t_total_a:.3f} s         | {peak_ram_a / 1024 / 1024:.2f} MB")
    print(f"{'[B] True Chunked Streaming (4MB)':<35} | {t_total_b:.3f} s         | {peak_ram_b / 1024 / 1024:.2f} MB")
    print(f"{'[C] True Chunked Streaming (16MB)':<35} | {t_total_c:.3f} s         | {peak_ram_c / 1024 / 1024:.2f} MB")
    diff_b = t_total_b - t_total_a
    diff_c = t_total_c - t_total_a
    print("-" * 70)
    print(f"Latency delta vs Full Download:")
    print(f"  - 4MB Streaming is:  {'+' if diff_b >= 0 else ''}{diff_b:.3f} s ({'+' if diff_b >= 0 else ''}{diff_b/t_total_a*100:.1f}%)")
    print(f"  - 16MB Streaming is: {'+' if diff_c >= 0 else ''}{diff_c:.3f} s ({'+' if diff_c >= 0 else ''}{diff_c/t_total_a*100:.1f}%)")
    print("=" * 70)


if __name__ == "__main__":
    run_benchmark()
