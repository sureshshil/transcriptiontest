import json
import time
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionOptions
from vm_benchmark_10min import (
    get_blob_client,
    ChunkedBlobStreamReader,
    CHUNK_SIZE,
    SPEECH_ENDPOINT,
    SPEECH_KEY,
    STORAGE_ACCOUNT,
    STORAGE_KEY,
    CONTAINER_NAME,
    BLOB_NAME,
)
from azure.storage.blob import generate_blob_sas, BlobSasPermissions
import datetime

client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))
blob_client = get_blob_client()

print("=" * 60)
print("COMPARING OUTPUTS: METHOD 1 vs METHOD 2 vs METHOD 3")
print("=" * 60)

# Method 1
print("[*] Running Method 1 (Single Shot)...")
audio_bytes = blob_client.download_blob().readall()
res1 = client.transcribe({
    "definition": TranscriptionOptions(locales=["en-US"]),
    "audio": ("audio_10min.wav", audio_bytes, "audio/wav")
})

# Method 2
print("[*] Running Method 2 (Chunked Stream)...")
reader = ChunkedBlobStreamReader(blob_client, chunk_size=CHUNK_SIZE)
res2 = client.transcribe({
    "definition": TranscriptionOptions(locales=["en-US"]),
    "audio": ("audio_10min.wav", reader, "audio/wav")
})

# Method 3
print("[*] Running Method 3 (SAS URL)...")
sas_token = generate_blob_sas(
    account_name=STORAGE_ACCOUNT,
    container_name=CONTAINER_NAME,
    blob_name=BLOB_NAME,
    account_key=STORAGE_KEY,
    permission=BlobSasPermissions(read=True),
    expiry=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=1),
)
sas_url = f"https://{STORAGE_ACCOUNT}.blob.core.windows.net/{CONTAINER_NAME}/{BLOB_NAME}?{sas_token}"
res3 = client.transcribe_from_url(audio_url=sas_url, options=TranscriptionOptions(locales=["en-US"]))

def inspect_res(name, res):
    text = res.combined_phrases[0].text if res.combined_phrases else "(Empty/Silence)"
    duration_ms = getattr(res, "duration_milliseconds", "N/A")
    print(f"\n--- {name} ---")
    print(f"Duration reported: {duration_ms} ms")
    print(f"Combined phrases count: {len(res.combined_phrases)}")
    print(f"Total detailed phrases: {len(res.phrases)}")
    print(f"Sample Text: '{text[:120]}...'")

inspect_res("Method 1 (Single Shot)", res1)
inspect_res("Method 2 (Chunked Stream)", res2)
inspect_res("Method 3 (SAS URL)", res3)

# Check text equality
text1 = [p.text for p in res1.phrases]
text2 = [p.text for p in res2.phrases]
text3 = [p.text for p in res3.phrases]

print("\n" + "=" * 60)
print(f"Method 1 == Method 2 text? {text1 == text2}")
print(f"Method 1 == Method 3 text? {text1 == text3}")
print(f"Method 2 == Method 3 text? {text2 == text3}")
print("=" * 60)
