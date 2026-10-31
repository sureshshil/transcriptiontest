import os
import json
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


def stream_multipart_logged(blob_client, boundary, definition_json, label):
    print(f"\n--- [{label}] Starting Streaming Generator ---")
    header_part = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="definition"\r\n'
        f"Content-Type: application/json\r\n\r\n{definition_json}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="audio.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8")
    yield header_part

    downloader = blob_client.download_blob()
    for i, chunk in enumerate(downloader.chunks()):
        cur, peak = tracemalloc.get_traced_memory()
        print(f"  Chunk #{i}: size={len(chunk)/1024/1024:.2f} MB | Current RAM={cur/1024/1024:.2f} MB | Peak RAM so far={peak/1024/1024:.2f} MB")
        yield chunk

    closing = f"\r\n--{boundary}--\r\n".encode("utf-8")
    yield closing


def trace_chunk_memory(chunk_size_mb):
    chunk_bytes = chunk_size_mb * 1024 * 1024
    service = BlobServiceClient.from_connection_string(
        conn_str, max_single_get_size=chunk_bytes, max_chunk_get_size=chunk_bytes
    )
    blob_client = service.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)

    url = f"{SPEECH_ENDPOINT}/speechtotext/transcriptions:transcribe?api-version=2025-10-15"
    boundary = f"boundary_{uuid.uuid4().hex}"
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    definition_json = json.dumps({"locales": ["en-US"]})

    tracemalloc.start()
    tracemalloc.reset_peak()
    
    resp = requests.post(
        url,
        headers=headers,
        data=stream_multipart_logged(blob_client, boundary, definition_json, f"{chunk_size_mb}MB"),
    )
    resp.raise_for_status()

    cur, peak = tracemalloc.get_traced_memory()
    print(f"[{chunk_size_mb}MB Stream End] Current RAM: {cur/1024/1024:.2f} MB | Final Peak RAM: {peak/1024/1024:.2f} MB")

    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics("lineno")
    print("\nTop 4 Memory Consuming Lines:")
    for stat in top_stats[:4]:
        print(f"  {stat}")
    tracemalloc.stop()


def main():
    print("=" * 70)
    print("DETAILED CHUNK-BY-CHUNK MEMORY TRACE ON AZURE VM")
    print("=" * 70)
    
    # Trace 4MB chunked streaming
    trace_chunk_memory(4)
    
    # Trace 16MB chunked streaming
    trace_chunk_memory(16)


if __name__ == "__main__":
    main()
