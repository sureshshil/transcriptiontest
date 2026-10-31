import os
import json
import sys
import time
import tracemalloc
import uuid
import requests
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionResult
from azure.core.rest import HttpRequest
from azure.core.exceptions import (
    HttpResponseError,
    map_error,
    ClientAuthenticationError,
    ResourceNotFoundError,
    ResourceExistsError,
    ResourceNotModifiedError,
)

SPEECH_ENDPOINT = "https://speech-poc-jp.cognitiveservices.azure.com"
SPEECH_KEY = os.getenv("SPEECH_KEY", "")
PLAIN_URL = "https://fparecordingadls.blob.core.windows.net/fpa-recording/wav/speech_10min_spoken.wav"
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB


def stream_from_http_blob(plain_url: str, bearer_token: str, boundary: str):
    definition_json = json.dumps({"locales": ["en-US"]})
    yield (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="definition"\r\n'
        f"Content-Type: application/json\r\n\r\n{definition_json}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="audio.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "x-ms-version": "2021-08-06",
    }
    with requests.get(plain_url, headers=headers, stream=True) as storage_resp:
        storage_resp.raise_for_status()
        for idx, chunk in enumerate(storage_resp.iter_content(chunk_size=CHUNK_SIZE)):
            cur, peak = tracemalloc.get_traced_memory()
            print(
                f"  [Chunk #{idx}] size={len(chunk)/1024/1024:.2f} MB | "
                f"Current RAM={cur/1024/1024:.2f} MB | Peak RAM={peak/1024/1024:.2f} MB"
            )
            yield chunk

    yield f"\r\n--{boundary}--\r\n".encode("utf-8")


class HttpBlobMultipartBody:
    """Each iteration restarts the HTTP GET stream, so SDK retries resend the full body."""

    def __init__(self, plain_url: str, bearer_token: str, boundary: str):
        self.plain_url = plain_url
        self.bearer_token = bearer_token
        self.boundary = boundary

    def __iter__(self):
        return stream_from_http_blob(self.plain_url, self.bearer_token, self.boundary)

    def __deepcopy__(self, memo):
        return self


ERROR_MAP = {
    401: ClientAuthenticationError,
    404: ResourceNotFoundError,
    409: ResourceExistsError,
    304: ResourceNotModifiedError,
}


def transcribe_streaming(speech_client: TranscriptionClient, plain_url: str, bearer_token: str, boundary: str) -> TranscriptionResult:
    request = HttpRequest(
        method="POST",
        url="/transcriptions:transcribe",
        params={"api-version": "2025-10-15"},
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        content=HttpBlobMultipartBody(plain_url, bearer_token, boundary),
    )
    response = speech_client.send_request(request)
    if response.status_code != 200:
        map_error(status_code=response.status_code, response=response, error_map=ERROR_MAP)
        raise HttpResponseError(response=response)
    return TranscriptionResult(response.json())


def main():
    print("=" * 75)
    print("TESTING HTTP Blob Fetch (MI) + speech_client.send_request() (SDK)")
    print("=" * 75)

    if len(sys.argv) > 1:
        bearer_token = sys.argv[1]
    else:
        bearer_token = DefaultAzureCredential().get_token("https://storage.azure.com/.default").token

    speech_client = TranscriptionClient(
        endpoint=SPEECH_ENDPOINT,
        credential=AzureKeyCredential(SPEECH_KEY),
    )

    boundary = f"boundary_{uuid.uuid4().hex}"

    tracemalloc.start()
    tracemalloc.reset_peak()
    t0 = time.perf_counter()

    result = transcribe_streaming(speech_client, PLAIN_URL, bearer_token, boundary)

    elapsed = time.perf_counter() - t0
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print("=" * 75)
    print(f"Return Type:       {type(result)}")
    print(f"Elapsed Time:      {elapsed:.3f} s")
    print(f"Audio Duration:    {result.duration_milliseconds / 1000:.1f} s")
    print(f"Phrases Count:     {len(result.phrases)}")
    print(f"Active RAM (End):  {cur / 1024 / 1024:.2f} MB")
    print(f"ABSOLUTE PEAK RAM: {peak / 1024 / 1024:.2f} MB")
    print(f"Sample Transcript: {result.combined_phrases[0].text[:90]}...")
    print("=" * 75)


if __name__ == "__main__":
    main()
