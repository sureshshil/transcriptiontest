import time
from test_10min_spoken_real import get_blob_client, SPEECH_ENDPOINT, SPEECH_KEY
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionOptions

blob_client = get_blob_client()
client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))

t0 = time.perf_counter()
t_down_start = time.perf_counter()
audio_bytes = blob_client.download_blob(max_concurrency=2).readall()
t_down = time.perf_counter() - t_down_start

t_upload_start = time.perf_counter()
res = client.transcribe({
    "definition": TranscriptionOptions(locales=["en-US"]),
    "audio": ("audio.wav", audio_bytes, "audio/wav")
})
t_upload = time.perf_counter() - t_upload_start
total = time.perf_counter() - t0

print("=" * 50)
print(f"Parallel Download (2 threads): {t_down:.3f} s")
print(f"Upload + Transcription Time:  {t_upload:.3f} s")
print(f"TOTAL LATENCY:                 {total:.3f} s")
print("=" * 50)
