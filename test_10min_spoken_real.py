import os
import datetime
import io
import time
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionOptions
from azure.storage.blob import (
    BlobServiceClient,
    BlobSasPermissions,
    generate_blob_sas,
)

SPEECH_ENDPOINT = "https://speech-poc-jp.cognitiveservices.azure.com/"
SPEECH_KEY = os.getenv("SPEECH_KEY", "")
STORAGE_ACCOUNT = "fparecordingadls"
STORAGE_KEY = os.getenv("STORAGE_KEY", "")
CONTAINER_NAME = "fpa-recording"
BLOB_NAME = "wav/speech_10min_spoken.wav"
CHUNK_SIZE = 4 * 1024 * 1024


def get_blob_client():
    conn_str = (
        f"DefaultEndpointsProtocol=https;AccountName={STORAGE_ACCOUNT};"
        f"AccountKey={STORAGE_KEY};EndpointSuffix=core.windows.net"
    )
    service = BlobServiceClient.from_connection_string(conn_str)
    return service.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)


class StrictChunkedBlobStream(io.RawIOBase):
    """
    Standard Python RawIOBase stream that yields bytes in 4MB segments from Blob.
    Does not truncate headers or stream boundaries.
    """
    def __init__(self, blob_client, chunk_size=CHUNK_SIZE):
        super().__init__()
        self.blob_client = blob_client
        self.chunk_size = chunk_size
        self.total_size = blob_client.get_blob_properties().size
        self.position = 0
        self.downloader = blob_client.download_blob(max_concurrency=4)
        self.chunk_iter = self.downloader.chunks()
        self.current_chunk = b""
        self.chunk_pos = 0

    def readable(self):
        return True

    def seekable(self):
        return False

    def readinto(self, b):
        if self.position >= self.total_size and self.chunk_pos >= len(self.current_chunk):
            return 0

        if self.chunk_pos >= len(self.current_chunk):
            try:
                self.current_chunk = next(self.chunk_iter)
                self.chunk_pos = 0
            except StopIteration:
                return 0

        available = len(self.current_chunk) - self.chunk_pos
        to_copy = min(len(b), available)
        b[:to_copy] = self.current_chunk[self.chunk_pos:self.chunk_pos + to_copy]
        self.chunk_pos += to_copy
        self.position += to_copy
        return to_copy


def test_method_1():
    print("\n[*] Running Method 1: Single Shot (Download full 26.5 MB into RAM)...")
    blob_client = get_blob_client()
    t0 = time.perf_counter()
    data = blob_client.download_blob().readall()
    t_down = time.perf_counter() - t0

    client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))
    t1 = time.perf_counter()
    res = client.transcribe({
        "definition": TranscriptionOptions(locales=["en-US"]),
        "audio": ("audio.wav", data, "audio/wav")
    })
    total = time.perf_counter() - t0
    transcribe_time = time.perf_counter() - t1
    return res, t_down, transcribe_time, total


def test_method_2():
    print("\n[*] Running Method 2: Chunked 4MB Stream from Blob...")
    blob_client = get_blob_client()
    t0 = time.perf_counter()
    stream = StrictChunkedBlobStream(blob_client, chunk_size=CHUNK_SIZE)

    client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))
    res = client.transcribe({
        "definition": TranscriptionOptions(locales=["en-US"]),
        "audio": ("audio.wav", stream, "audio/wav")
    })
    total = time.perf_counter() - t0
    return res, total


def test_method_3():
    print("\n[*] Running Method 3: SAS URL (Direct Storage to Speech)...")
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
    client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))
    res = client.transcribe_from_url(audio_url=sas_url, options=TranscriptionOptions(locales=["en-US"]))
    total = time.perf_counter() - t0
    return res, total


def main():
    print("=" * 65)
    print("TESTING 10-MINUTE SPOKEN AUDIO (26,460,044 bytes = 26.46 MB)")
    print("=" * 65)

    res1, d1, tr1, t1 = test_method_1()
    res2, t2 = test_method_2()
    res3, t3 = test_method_3()

    text1 = res1.combined_phrases[0].text if res1.combined_phrases else ""
    text2 = res2.combined_phrases[0].text if res2.combined_phrases else ""
    text3 = res3.combined_phrases[0].text if res3.combined_phrases else ""

    print("\n" + "=" * 65)
    print("TEXT COMPARISON RESULTS")
    print("=" * 65)
    print(f"Method 1: Duration {res1.duration_milliseconds/1000:.1f}s | Words: {len(text1.split())} | Phrases: {len(res1.phrases)}")
    print(f"Method 2: Duration {res2.duration_milliseconds/1000:.1f}s | Words: {len(text2.split())} | Phrases: {len(res2.phrases)}")
    print(f"Method 3: Duration {res3.duration_milliseconds/1000:.1f}s | Words: {len(text3.split())} | Phrases: {len(res3.phrases)}")

    match_1_2 = (text1 == text2)
    match_1_3 = (text1 == text3)
    match_2_3 = (text2 == text3)
    print(f"\nAre transcribed texts 100% IDENTICAL?")
    print(f"  Method 1 vs Method 2: {match_1_2}")
    print(f"  Method 1 vs Method 3: {match_1_3}")
    print(f"  Method 2 vs Method 3: {match_2_3}")

    print("\nSample Transcribed Text:")
    print(f"\"{text1[:150]}...\"\n")

    print("=" * 65)
    print("ACCURATE TIMING BENCHMARK")
    print("=" * 65)
    print(f"{'Method':<35} | {'Duration':<10} | {'Total Time':<10}")
    print("-" * 65)
    print(f"{'1. Single Shot (Full RAM)':<35} | {res1.duration_milliseconds/1000:.0f}s       | {t1:.2f} s")
    print(f"{'2. Chunked Stream (4MB max)':<35} | {res2.duration_milliseconds/1000:.0f}s       | {t2:.2f} s")
    print(f"{'3. SAS URL (Direct Storage)':<35} | {res3.duration_milliseconds/1000:.0f}s       | {t3:.2f} s")
    print("=" * 65)


if __name__ == "__main__":
    main()
