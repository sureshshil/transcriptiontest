import time
from test_10min_spoken_real import (
    get_blob_client,
    SPEECH_ENDPOINT,
    SPEECH_KEY,
    StrictChunkedBlobStream,
)
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionOptions

blob_client = get_blob_client()
client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))

print("=" * 60)
print("HEAD-TO-HEAD COMPARISON: 16MB STREAM vs PRE-ALLOCATED BUFFER")
print("=" * 60)

# Run 1: 16MB Chunked Stream
t0 = time.perf_counter()
stream = StrictChunkedBlobStream(blob_client, chunk_size=16 * 1024 * 1024)
res1 = client.transcribe({
    "definition": TranscriptionOptions(locales=["en-US"]),
    "audio": ("audio.wav", stream, "audio/wav")
})
t_stream = time.perf_counter() - t0

# Run 2: Pre-allocated buffer
t0 = time.perf_counter()
audio_bytes = blob_client.download_blob(max_concurrency=2).readall()
res2 = client.transcribe({
    "definition": TranscriptionOptions(locales=["en-US"]),
    "audio": ("audio.wav", audio_bytes, "audio/wav")
})
t_buffer = time.perf_counter() - t0

print(f"1. 16MB Chunked Stream:       {t_stream:.3f} s  (RAM capped at 16MB)")
print(f"2. Pre-allocated Buffer:      {t_buffer:.3f} s  (RAM holds full file)")
diff = abs(t_stream - t_buffer)
print(f"Latency Difference:           {diff:.3f} s ({diff / t_stream * 100:.1f}%)")
print("=" * 60)
