import time
from test_10min_spoken_real import get_blob_client

blob_client = get_blob_client()
size = blob_client.get_blob_properties().size

concurrencies = [1, 2, 4, 8]
print(f"BENCHMARKING PARALLEL BLOB DOWNLOAD ({size/1024/1024:.2f} MB):")
for c in concurrencies:
    t0 = time.perf_counter()
    data = blob_client.download_blob(max_concurrency=c).readall()
    elapsed = time.perf_counter() - t0
    speed_mb_s = (len(data) / 1024 / 1024) / elapsed
    print(f"Concurrency: {c} threads | Download Time: {elapsed:.4f} s | Throughput: {speed_mb_s:.1f} MB/s")
