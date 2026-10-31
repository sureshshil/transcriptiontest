import os
import time
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionOptions, TranscriptionContent
from azure.storage.blob import BlobServiceClient

SPEECH_ENDPOINT = "https://speech-poc-jp.cognitiveservices.azure.com/"
SPEECH_KEY = os.getenv("SPEECH_KEY", "")
STORAGE_ACCOUNT = "fparecordingadls"
STORAGE_KEY = os.getenv("STORAGE_KEY", "")
CONTAINER_NAME = "fpa-recording"
BLOB_NAME = "wav/speech_10min_spoken.wav"

conn_str = (
    f"DefaultEndpointsProtocol=https;AccountName={STORAGE_ACCOUNT};"
    f"AccountKey={STORAGE_KEY};EndpointSuffix=core.windows.net"
)

# Native Azure SDK way: configure max_single_get_size / max_chunk_get_size on the client
service = BlobServiceClient.from_connection_string(
    conn_str,
    max_single_get_size=16 * 1024 * 1024,
    max_chunk_get_size=16 * 1024 * 1024,
)
blob_client = service.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)
speech_client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))

print("=" * 65)
print("TESTING NATIVE 1-LINE STREAMING (NO CUSTOM WRAPPER CLASS!)")
print("=" * 65)

t0 = time.perf_counter()
# 1. Get native stream downloader from Azure Blob SDK
blob_stream = blob_client.download_blob()

# 2. Pass blob_stream directly to TranscriptionContent!
content = TranscriptionContent(
    definition=TranscriptionOptions(locales=["en-US"]),
    audio=blob_stream,
)
result = speech_client.transcribe(content)
elapsed = time.perf_counter() - t0

print(f"Elapsed Time: {elapsed:.3f} s")
print(f"Duration:     {result.duration_milliseconds / 1000:.1f} s")
print(f"Phrases:      {len(result.phrases)}")
print(f"Sample Text:  {result.combined_phrases[0].text[:100]}...")
print("=" * 65)
