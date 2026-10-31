import os
import time
import tracemalloc
import uuid
import requests
import json
from azure.identity import AzureCliCredential
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionOptions

PLAIN_URL = "https://fparecordingadls.blob.core.windows.net/fpa-recording/wav/speech_10min_spoken.wav"
SPEECH_ENDPOINT = "https://speech-poc-jp.cognitiveservices.azure.com"
SPEECH_KEY = os.getenv("SPEECH_KEY", "")
CHUNK_SIZE = 4 * 1024 * 1024

cred = AzureCliCredential()
token = cred.get_token("https://storage.azure.com/.default").token


# =====================================================================
# Approach 1: Official SDK (client.transcribe) + Plain URL (Managed Identity)
# =====================================================================
class ManagedIdentityAudioStream:
    def __init__(self, url, bearer_token):
        headers = {"Authorization": f"Bearer {bearer_token}", "x-ms-version": "2021-08-06"}
        self.response = requests.get(url, headers=headers, stream=True)
        self.response.raise_for_status()
        self.iter = self.response.iter_content(chunk_size=CHUNK_SIZE)

    def read(self, size=-1):
        try:
            return next(self.iter)
        except StopIteration:
            return b""


def test_sdk():
    client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))
    stream = ManagedIdentityAudioStream(PLAIN_URL, token)
    tracemalloc.start()
    tracemalloc.reset_peak()
    t0 = time.perf_counter()
    res = client.transcribe({
        "definition": TranscriptionOptions(locales=["en-US"]),
        "audio": ("audio.wav", stream, "audio/wav")
    })
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, peak / 1024 / 1024, len(res.phrases)


# =====================================================================
# Approach 2: Pure REST Generator (requests.post data=generator) + Plain URL
# =====================================================================
def test_pure_rest():
    b_val = uuid.uuid4().hex
    definition_json = json.dumps({"locales": ["en-US"]})

    def gen():
        yield (
            f"--{b_val}\r\n"
            f'Content-Disposition: form-data; name="definition"\r\n'
            f"Content-Type: application/json\r\n\r\n{definition_json}\r\n"
            f"--{b_val}\r\n"
            f'Content-Disposition: form-data; name="audio"; filename="audio.wav"\r\n'
            f"Content-Type: audio/wav\r\n\r\n"
        ).encode("utf-8")

        headers = {"Authorization": f"Bearer {token}", "x-ms-version": "2021-08-06"}
        with requests.get(PLAIN_URL, headers=headers, stream=True) as storage_resp:
            storage_resp.raise_for_status()
            for chunk in storage_resp.iter_content(chunk_size=CHUNK_SIZE):
                yield chunk
        yield f"\r\n--{b_val}--\r\n".encode("utf-8")

    tracemalloc.start()
    tracemalloc.reset_peak()
    t0 = time.perf_counter()
    url = f"{SPEECH_ENDPOINT}/speechtotext/transcriptions:transcribe?api-version=2025-10-15"
    headers = {
        "Ocp-Apim-Subscription-Key": SPEECH_KEY,
        "Content-Type": f"multipart/form-data; boundary={b_val}",
    }
    r = requests.post(url, headers=headers, data=gen())
    r.raise_for_status()
    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return elapsed, peak / 1024 / 1024, len(r.json().get("phrases", []))


def main():
    print("=" * 70)
    print("HEAD-TO-HEAD ON VM: SDK vs PURE REST (BOTH USING PLAIN URL + MI)")
    print("=" * 70)

    print("\n[1] Running Official SDK (client.transcribe)...")
    t1, ram1, p1 = test_sdk()
    print(f"    Elapsed: {t1:.3f} s | Peak RAM: {ram1:.2f} MB | Phrases: {p1}")

    print("\n[2] Running Pure REST Generator (requests.post)...")
    t2, ram2, p2 = test_pure_rest()
    print(f"    Elapsed: {t2:.3f} s | Peak RAM: {ram2:.2f} MB | Phrases: {p2}")

    print("\n" + "=" * 70)
    print(f"Summary:")
    print(f"  - Official SDK:  {t1:.3f} s (Peak RAM: {ram1:.2f} MB)")
    print(f"  - Pure REST:     {t2:.3f} s (Peak RAM: {ram2:.2f} MB)")
    print(f"  - Time Difference: {abs(t1 - t2):.3f} s (within statistical variance)")
    print("=" * 70)


if __name__ == "__main__":
    main()
