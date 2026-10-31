# Azure Fast Transcription: 10-Minute Real Speech Master Benchmark (All 8 Options)

- **File**: `wav/speech_10min_spoken.wav` (10.0 minutes / 600.0 seconds, 22.05 kHz)
- **File Size**: `26,460,044` bytes (`25.23 MiB` / `26.46 MB`)
- **Content**: 1,313 spoken English words, 75 conversational phrases
- **Environment**: Azure VM `vm-b1ls` (`Standard_B1ls`, `0.5 GB RAM`) in `japaneast`

---

## 1. Consolidated Master Benchmark Comparison (All 8 Options)

| # | Method & Script | Blob Fetch Method | Speech API Call Method | Works w/ Strict Storage Firewall? | Returns SDK `TranscriptionResult`? | Needs SDK Patch? | Latency (10-min Audio) | Peak RAM (25.2 MB Audio) | Peak RAM (320 MB 2-Hr Audio) |
| :-: | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | **SAS URL (Server-to-Server)**<br>[`test_10min_spoken_real.py`](../test_10min_spoken_real.py) | None *(Speech fetches SAS URL directly)* | `speech_client.transcribe_from_url()` | Only if Trusted Azure Services enabled | Yes | No | **`3.44 s`** | **`0.22 MB`** | **`0.22 MB`** |
| **2** | **Default SDK (`64 MB` chunks)**<br>[`test_10min_spoken_real.py`](../test_10min_spoken_real.py) | `BlobClient` *(Default 64 MB)* | `speech_client.transcribe()` | Yes (Pod MI) | Yes | No | `5.04 s` | `236.12 MB` | `> 1,200 MB` *(OOM)* |
| **3** | **Tuned SDK (`4 MB` chunks)**<br>[`test_true_zero_buffer_stream.py`](../test_true_zero_buffer_stream.py) | `BlobClient` *(4 MB chunks)* | `speech_client.transcribe()` | Yes (Pod MI) | Yes | No | `4.54 s` | `56.21 MB` | `~645 MB` *(2x file)* |
| **4** | **`BlobMultipartBody` + `send_request` (Unpatched)**<br>[`test_sdk_send_request_streaming.py`](../test_sdk_send_request_streaming.py) | `BlobClient` *(4 MB chunks + MI)* | `speech_client.send_request()` | Yes (Pod MI) | Yes | No | `5.15 s` | **`40.48 MB`** | **`40.48 MB`** *(Constant)* |
| **5** | **`BlobMultipartBody` + `send_request` (Patched)**<br>[`test_sdk_send_request_streaming.py`](../test_sdk_send_request_streaming.py) | `BlobClient` *(4 MB chunks + MI)* | `speech_client.send_request()` | Yes (Pod MI) | Yes | Yes (`del __len__`) | **`4.71 s`** | **`12.47 MB`** | **`12.47 MB`** *(Constant)* |
| **6** | **HTTP Blob + SDK `send_request` (Recommended)**<br>[`test_http_blob_plus_sdk_send_request.py`](../test_http_blob_plus_sdk_send_request.py) | **`requests.get(stream=True)` + MI Token** | **`speech_client.send_request()`** | **Yes (Pod MI)** | **Yes** | **No** | **`~4.70 s`** | **`10.27 MB`** | **`10.27 MB`** *(Constant)* |
| **7** | **Pure HTTP Stream (No SDK)**<br>[`test_pure_stream_low_ram.py`](../test_pure_stream_low_ram.py) / [`run_clean_comparison.py`](../run_clean_comparison.py) | `requests.get(stream=True)` + MI Token | `requests.post(data=gen)` | Yes (Pod MI) | No *(Raw dict)* | No | **`4.65 s`** | **`4.06 – 4.77 MB`** | **`4.06 – 4.77 MB`** *(Constant)* |
| **8** | **Pod `/tmp` Temp File**<br>[`test_pod_temp_file.py`](../test_pod_temp_file.py) | `BlobClient.download_to_stream(file)` | `requests.post(data=gen)` | Yes (Pod MI) | No *(Raw dict)* | No | `6.14 s` *(Slower)* | `4.68 MB` *(+ Disk)* | `4.68 MB` *(+ 320 MB Disk)* |

---

## 2. Text Output Verification Across All Methods

| Method Category | Audio Duration Transcribed | Word Count | Phrase Count | Text Accuracy Match |
| :--- | :---: | :---: | :---: | :---: |
| **All 8 Options Above** | `600.0 s` (10.0 min) | `1,313` | `75` | **Exact 100% Match** |

---

## 3. Why Peak RAM Differs Across Options

1. **Options #2 & #3 (`speech_client.transcribe()`)**: Uses Python `requests` `files=`, which calls `fdata = fp.read()` (reading the entire file into RAM) and then copies `fdata` into `urllib3`'s `body = BytesIO()` ($2\times$ file size in memory).
2. **Option #4 (`BlobClient` + `speech_client.send_request()` Unpatched)**: Uses `content=BlobMultipartBody(...)` to stream `4 MB` chunks without `files=`. Peak RAM is `40.48 MB` because `StreamDownloadGenerator.__len__()` returns the chunk's HTTP `Content-Length` in bytes (`4,194,304`), causing `list(data)` in `azure/storage/blob/_download.py` to transiently allocate $4,194,304 \times 8\text{ B} = 32.00\text{ MB}$ of pointer array memory.
3. **Option #5 (`BlobClient` + `speech_client.send_request()` Patched)**: Removing `del StreamDownloadGenerator.__len__` eliminates the `32 MB` list pre-allocation, leaving $3 \times 4.00\text{ MB} + 0.47\text{ MB} = \mathbf{12.47\text{ MB}}$ (`Chunk #0` in `http.client`'s loop variable + `list(data)` 16 blocks + `b"".join()` contiguous `4 MB` bytes).
4. **Option #6 (HTTP Blob Fetch + `speech_client.send_request()`)**: Fetches the blob via `requests.get(plain_url, headers={"Authorization": f"Bearer {token}"}, stream=True)` and streams into `speech_client.send_request()`, avoiding `BlobClient`'s `b"".join(list(data))` completely and achieving **`10.27 MB` Peak RAM** out-of-the-box with no monkey-patching while still returning the SDK's `TranscriptionResult` object.
