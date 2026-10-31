import os
import json
import sys
import time
import tracemalloc
import uuid
from azure.identity import DefaultAzureCredential
from azure.core.credentials import AzureKeyCredential, AccessToken
from azure.storage.blob import BlobClient
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
ACCOUNT_URL = "https://fparecordingadls.blob.core.windows.net"
CONTAINER_NAME = "fpa-recording"
BLOB_NAME = "wav/speech_10min_spoken.wav"
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB


class StaticTokenCredential:
    def __init__(self, token: str):
        self._token = AccessToken(token, int(time.time()) + 3600)

    def get_token(self, *scopes, **kwargs) -> AccessToken:
        return self._token


def stream_from_blob_client(blob_client: BlobClient, boundary: str):
    definition_json = json.dumps({"locales": ["en-US"]})
    yield (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="definition"\r\n'
        f"Content-Type: application/json\r\n\r\n{definition_json}\r\n"
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="audio"; filename="audio.wav"\r\n'
        f"Content-Type: audio/wav\r\n\r\n"
    ).encode("utf-8")

    for idx, chunk in enumerate(blob_client.download_blob().chunks()):
        cur, peak = tracemalloc.get_traced_memory()
        print(
            f"  [Chunk #{idx}] size={len(chunk)/1024/1024:.2f} MB | "
            f"Current RAM={cur/1024/1024:.2f} MB | Peak RAM={peak/1024/1024:.2f} MB"
        )
        yield chunk

    yield f"\r\n--{boundary}--\r\n".encode("utf-8")


class BlobMultipartBody:
    """Each iteration restarts the blob download, so a retry resends the full body."""

    def __init__(self, blob_client, boundary):
        self.blob_client, self.boundary = blob_client, boundary

    def __iter__(self):
        return stream_from_blob_client(self.blob_client, self.boundary)

    def __deepcopy__(self, memo):
        return self  # send_request() deep-copies the request; don't copy the BlobClient


ERROR_MAP = {
    401: ClientAuthenticationError,
    404: ResourceNotFoundError,
    409: ResourceExistsError,
    304: ResourceNotModifiedError,
}


def transcribe_streaming(speech_client: TranscriptionClient, blob_client: BlobClient, boundary: str) -> TranscriptionResult:
    request = HttpRequest(
        method="POST",
        url="/transcriptions:transcribe",
        params={"api-version": "2025-10-15"},
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Accept": "application/json",
        },
        content=BlobMultipartBody(blob_client, boundary),
    )
    response = speech_client.send_request(request)  # SDK retry, auth and logging run here
    if response.status_code != 200:
        map_error(status_code=response.status_code, response=response, error_map=ERROR_MAP)
        raise HttpResponseError(response=response)  # same exception as transcribe()
    return TranscriptionResult(response.json())


def main():
    print("=" * 75)
    print("TESTING BlobMultipartBody + speech_client.send_request() + BlobClient (MI)")
    print("=" * 75)

    if len(sys.argv) > 1:
        credential = StaticTokenCredential(sys.argv[1])
    else:
        credential = DefaultAzureCredential()
        credential.get_token("https://storage.azure.com/.default")

    blob_client = BlobClient(
        account_url=ACCOUNT_URL,
        container_name=CONTAINER_NAME,
        blob_name=BLOB_NAME,
        credential=credential,
        max_single_get_size=CHUNK_SIZE,
        max_chunk_get_size=CHUNK_SIZE,
    )

    speech_client = TranscriptionClient(
        endpoint=SPEECH_ENDPOINT,
        credential=AzureKeyCredential(SPEECH_KEY),
    )

    boundary = f"boundary_{uuid.uuid4().hex}"

    tracemalloc.start()
    tracemalloc.reset_peak()
    t0 = time.perf_counter()

    result = transcribe_streaming(speech_client, blob_client, boundary)

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
