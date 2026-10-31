import time
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionOptions
from test_10min_spoken_real import (
    get_blob_client,
    SPEECH_ENDPOINT,
    SPEECH_KEY,
    StrictChunkedBlobStream,
)

blob_client = get_blob_client()
total_size = blob_client.get_blob_properties().size
print(f"Total audio file size: {total_size:,} bytes ({total_size/1024/1024:.2f} MB)")

client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))

# Test varying chunk sizes: 2MB, 4MB, 8MB, 16MB, 26MB (single full chunk)
chunk_sizes_mb = [2, 4, 8, 16, 26]
results = {}

for size_mb in chunk_sizes_mb:
    chunk_bytes = size_mb * 1024 * 1024
    stream = StrictChunkedBlobStream(blob_client, chunk_size=chunk_bytes)
    t0 = time.perf_counter()
    res = client.transcribe({
        "definition": TranscriptionOptions(locales=["en-US"]),
        "audio": ("audio.wav", stream, "audio/wav")
    })
    elapsed = time.perf_counter() - t0
    results[f"{size_mb} MB"] = elapsed
    print(f"Chunk Size: {size_mb:>2} MB | Elapsed: {elapsed:.3f} s | Phrases: {len(res.phrases)}")

print("\n" + "=" * 45)
print("CHUNK SIZE vs LATENCY BENCHMARK (10 min audio)")
print("=" * 45)
for k, v in results.items():
    print(f"Chunk Size: {k:<8} | Total Latency: {v:.2f} s")
print("=" * 45)
