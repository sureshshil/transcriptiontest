import inspect
from azure.ai.transcription import TranscriptionClient

# Inspect transcribe arguments
print("transcribe signature:", inspect.signature(TranscriptionClient.transcribe))
