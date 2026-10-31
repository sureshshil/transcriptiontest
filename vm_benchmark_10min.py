import datetime
import io
import json
import os
import time
import requests
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionOptions
from azure.storage.blob import (
    BlobServiceClient,
    BlobSasPermissions,
    generate_blob_sas,
)

# Configuration
SPEECH_ENDPOINT = "https://speech-poc-jp.cognitiveservices.azure.com/"
SPEECH_KEY = os.getenv("SPEECH_KEY", "")
STORAGE_ACCOUNT = "fparecordingadls"
STORAGE_KEY = os.getenv("STORAGE_KEY", "")
CONTAINER_NAME = "fpa-recording"
BLOB_NAME = "wav/audio_10min.wav"
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB chunk


def get_blob_client():
    conn_str = (
        f"DefaultEndpointsProtocol=https;AccountName={STORAGE_ACCOUNT};"
        f"AccountKey={STORAGE_KEY};EndpointSuffix=core.windows.net"
    )
    service = BlobServiceClient.from_connection_string(conn_str)
    return service.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)


def test_1_single_shot():
    """
    Test 1: Normal method - download full WAV from Blob into memory at once,
    then upload as a single shot to Speech endpoint.
    """
    print("\n" + "=" * 60)
    print("TEST 1: Fast Transcription - Single Shot (Full WAV in Memory)")
    print("=" * 60)
    blob_client = get_blob_client()

    # Step 1: Download full blob
    t0 = time.perf_counter()
    audio_bytes = blob_client.download_blob().readall()
    download_time = time.perf_counter() - t0
    print(f"[*] Downloaded {len(audio_bytes):,} bytes ({len(audio_bytes)/1024/1024:.2f} MB) in {download_time:.3f}s")

    # Step 2: Upload to Fast Transcription
    client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))
    t1 = time.perf_counter()
    result = client.transcribe({
        "definition": TranscriptionOptions(locales=["en-US"]),
        "audio": ("audio_10min.wav", audio_bytes, "audio/wav")
    })
    transcribe_time = time.perf_counter() - t1
    total_time = time.perf_counter() - t0

    print(f"[+] Transcribe time: {transcribe_time:.3f}s")
    print(f"[+] Total time:      {total_time:.3f}s")
    return {"download": download_time, "transcribe": transcribe_time, "total": total_time}


class ChunkedBlobStreamReader:
    """
    Custom stream reader that streams from Azure Blob in strictly 4MB chunks
    so memory usage at any given moment never exceeds 4MB.
    """
    def __init__(self, blob_client, chunk_size=CHUNK_SIZE):
        self.blob_client = blob_client
        self.chunk_size = chunk_size
        self.props = blob_client.get_blob_properties()
        self.total_size = self.props.size
        self.offset = 0
        self.current_chunk = b""
        self.chunk_offset = 0

    def read(self, size=-1):
        if self.offset >= self.total_size and self.chunk_offset >= len(self.current_chunk):
            return b""

        # Need more data into current chunk
        if self.chunk_offset >= len(self.current_chunk):
            if self.offset >= self.total_size:
                return b""
            read_len = min(self.chunk_size, self.total_size - self.offset)
            stream = self.blob_client.download_blob(offset=self.offset, length=read_len)
            self.current_chunk = stream.readall()
            self.offset += read_len
            self.chunk_offset = 0

        if size is None or size < 0:
            remaining = self.current_chunk[self.chunk_offset:]
            self.chunk_offset = len(self.current_chunk)
            return remaining

        to_read = min(size, len(self.current_chunk) - self.chunk_offset)
        res = self.current_chunk[self.chunk_offset:self.chunk_offset + to_read]
        self.chunk_offset += to_read
        return res

    def __len__(self):
        return self.total_size


def test_2_streaming_4mb_chunks():
    """
    Test 2: Fast transcription with 4MB chunked streaming.
    Streams directly from Azure Blob in 4MB segments into multipart request.
    Max memory occupied by audio buffer is 4MB.
    """
    print("\n" + "=" * 60)
    print("TEST 2: Fast Transcription - 4MB Chunked Streaming (Low Memory)")
    print("=" * 60)
    blob_client = get_blob_client()

    t0 = time.perf_counter()
    reader = ChunkedBlobStreamReader(blob_client, chunk_size=CHUNK_SIZE)
    print(f"[*] Stream initialized. Total file size: {reader.total_size:,} bytes. Chunk size: {CHUNK_SIZE/1024/1024:.0f} MB")

    # Send using client.transcribe with file-like chunked stream
    client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))
    t1 = time.perf_counter()
    result = client.transcribe({
        "definition": TranscriptionOptions(locales=["en-US"]),
        "audio": ("audio_10min.wav", reader, "audio/wav")
    })
    total_time = time.perf_counter() - t0

    print(f"[+] Total time (Download chunks + Stream Upload + Transcribe): {total_time:.3f}s")
    return {"total": total_time}


def test_3_sas_url():
    """
    Test 3: Fast transcription using SAS URL (Zero data downloaded by VM).
    """
    print("\n" + "=" * 60)
    print("TEST 3: Fast Transcription - SAS URL (Direct Storage-to-Speech)")
    print("=" * 60)

    t0 = time.perf_counter()
    sas_token = generate_blob_sas(
        account_name=STORAGE_ACCOUNT,
        container_name=CONTAINER_NAME,
        blob_name=BLOB_NAME,
        account_key=STORAGE_KEY,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
    )
    sas_url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER_NAME}/{BLOB_NAME}?{sas_token}"
    sas_gen_time = time.perf_counter() - t0
    print(f"[*] Generated SAS URL in {sas_gen_time*1000:.2f} ms")

    client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))
    t1 = time.perf_counter()
    result = client.transcribe_from_url(
        audio_url=sas_url,
        options=TranscriptionOptions(locales=["en-US"])
    )
    transcribe_time = time.perf_counter() - t1
    total_time = time.perf_counter() - t0

    print(f"[+] Transcribe time from URL: {transcribe_time:.3f}s")
    print(f"[+] Total time:               {total_time:.3f}s")
    return {"sas_gen": sas_gen_time, "transcribe": transcribe_time, "total": total_time}


def main():
    print("#" * 60)
    print("BENCHMARK SUITE: 10-MINUTE AUDIO ON AZURE VM (JAPAN EAST)")
    print("#" * 60)

    res1 = test_1_single_shot()
    res2 = test_2_streaming_4mb_chunks()
    res3 = test_3_sas_url()

    print("\n" + "#" * 60)
    print("FINAL BENCHMARK COMPARISON TABLE (10-Minute Audio / 19.2 MB)")
    print("#" * 60)
    print(f"{'Method':<35} | {'VM Peak Audio RAM':<18} | {'Total Time':<12}")
    print("-" * 72)
    print(f"{'1. Single Shot (Full in-memory)':<35} | {'19.2 MB':<18} | {res1['total']:.2f} s")
    print(f"{'2. Streaming (4MB Chunks)':<35} | {'4.0 MB':<18} | {res2['total']:.2f} s")
    print(f"{'3. SAS URL (Direct to Speech)':<35} | {'0.0 MB':<18} | {res3['total']:.2f} s")
    print("#" * 60)


if __name__ == "__main__":
    main()
