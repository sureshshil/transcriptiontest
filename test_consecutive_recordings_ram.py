import os
import time
import tracemalloc
from azure.storage.blob import BlobServiceClient

STORAGE_ACCOUNT = "fparecordingadls"
STORAGE_KEY = os.getenv("STORAGE_KEY", "")
CONTAINER_NAME = "fpa-recording"
BLOB_NAME = "wav/speech_10min_spoken.wav"

conn_str = (
    f"DefaultEndpointsProtocol=https;AccountName={STORAGE_ACCOUNT};"
    f"AccountKey={STORAGE_KEY};EndpointSuffix=core.windows.net"
)


def run_consecutive_downloads_test():
    print("=" * 70)
    print("TESTING CONSECUTIVE RECORDING DOWNLOADS IN THE SAME PROCESS")
    print("=" * 70)

    # 1. Initialize client once
    service = BlobServiceClient.from_connection_string(
        conn_str, max_single_get_size=4 * 1024 * 1024, max_chunk_get_size=4 * 1024 * 1024
    )
    blob_client = service.get_blob_client(container=CONTAINER_NAME, blob=BLOB_NAME)

    tracemalloc.start()

    # Simulate 3 consecutive recordings processed sequentially
    for recording_num in range(1, 4):
        tracemalloc.reset_peak()
        t0 = time.perf_counter()

        downloader = blob_client.download_blob()
        chunk_count = 0
        for chunk in downloader.chunks():
            chunk_count += 1

        elapsed = time.perf_counter() - t0
        cur, peak = tracemalloc.get_traced_memory()
        print(f"Recording #{recording_num}:")
        print(f"  - Chunks processed:   {chunk_count}")
        print(f"  - Elapsed time:       {elapsed:.3f} s")
        print(f"  - Active RAM at end:  {cur / 1024 / 1024:.2f} MB")
        print(f"  - PEAK RAM consumed:  {peak / 1024 / 1024:.2f} MB")
        print("-" * 50)

    tracemalloc.stop()


if __name__ == "__main__":
    run_consecutive_downloads_test()
