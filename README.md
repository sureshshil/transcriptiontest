# Azure Speech Fast Transcription + ADLS Gen2 Streaming & Memory Benchmark POC

This repository contains all benchmark scripts, memory profiling tools, and architectural findings for streaming audio from **Azure Data Lake Storage Gen2 (ADLS Gen2)** to **Azure AI Speech Fast Transcription (`2025-10-15`)** with **Managed Identity** and **$O(1)$ constant memory** in enterprise Kubernetes (AKS) / VM environments.

---

## 1. Consolidated Master Benchmark Comparison

Tested on **10-minute real spoken English audio (`25.23 MB`, 600s, 75 phrases, 1,313 words)** stored in ADLS Gen2 (`japaneast`) from an Azure Linux VM (`Standard_B1ls`, `0.5 GB RAM`, `japaneast`), and projected to a **2-hour recording (`320 MB`)**:

| # | Method & Script | Blob Fetch Method | Speech API Call Method | Works w/ Strict Storage Firewall? | Returns SDK `TranscriptionResult`? | Needs SDK Patch? | Latency (10-min Audio) | Peak RAM (25.2 MB Audio) | Peak RAM (320 MB 2-Hr Audio) |
| :-: | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | **SAS URL (Server-to-Server)**<br>[`test_10min_spoken_real.py`](test_10min_spoken_real.py) | None *(Speech fetches SAS URL directly)* | `speech_client.transcribe_from_url()` | Only if Trusted Azure Services enabled | Yes | No | **`3.44 s`** | **`0.22 MB`** | **`0.22 MB`** |
| **2** | **Default SDK (`64 MB` chunks)**<br>[`test_10min_spoken_real.py`](test_10min_spoken_real.py) | `BlobClient` *(Default 64 MB)* | `speech_client.transcribe()` | Yes (Pod MI) | Yes | No | `5.04 s` | `236.12 MB` | `> 1,200 MB` *(OOM)* |
| **3** | **Tuned SDK (`4 MB` chunks)**<br>[`test_true_zero_buffer_stream.py`](test_true_zero_buffer_stream.py) | `BlobClient` *(4 MB chunks)* | `speech_client.transcribe()` | Yes (Pod MI) | Yes | No | `4.54 s` | `56.21 MB` | `~645 MB` *(2x file)* |
| **4** | **`BlobMultipartBody` + `send_request` (Unpatched)**<br>[`test_sdk_send_request_streaming.py`](test_sdk_send_request_streaming.py) | `BlobClient` *(4 MB chunks + MI)* | `speech_client.send_request()` | Yes (Pod MI) | Yes | No | `5.15 s` | **`40.48 MB`** | **`40.48 MB`** *(Constant)* |
| **5** | **`BlobMultipartBody` + `send_request` (Patched)**<br>[`test_sdk_send_request_streaming.py`](test_sdk_send_request_streaming.py) | `BlobClient` *(4 MB chunks + MI)* | `speech_client.send_request()` | Yes (Pod MI) | Yes | Yes (`del __len__`) | **`4.71 s`** | **`12.47 MB`** | **`12.47 MB`** *(Constant)* |
| **6** | **HTTP Blob + SDK `send_request` (Recommended)**<br>[`test_http_blob_plus_sdk_send_request.py`](test_http_blob_plus_sdk_send_request.py) | **`requests.get(stream=True)` + MI Token** | **`speech_client.send_request()`** | **Yes (Pod MI)** | **Yes** | **No** | **`~4.70 s`** | **`10.27 MB`** | **`10.27 MB`** *(Constant)* |
| **7** | **Pure HTTP Stream (No SDK)**<br>[`test_pure_stream_low_ram.py`](test_pure_stream_low_ram.py) / [`run_clean_comparison.py`](run_clean_comparison.py) | `requests.get(stream=True)` + MI Token | `requests.post(data=gen)` | Yes (Pod MI) | No *(Raw dict)* | No | **`4.65 s`** | **`4.06 – 4.77 MB`** | **`4.06 – 4.77 MB`** *(Constant)* |
| **8** | **Pod `/tmp` Temp File**<br>[`test_pod_temp_file.py`](test_pod_temp_file.py) | `BlobClient.download_to_stream(file)` | `requests.post(data=gen)` | Yes (Pod MI) | No *(Raw dict)* | No | `6.14 s` *(Slower)* | `4.68 MB` *(+ Disk)* | `4.68 MB` *(+ 320 MB Disk)* |

---

## 2. Architecture & Network/Auth Findings (`transcribe_from_url` vs. Streaming)

| Approach | How Audio Reaches Azure Speech | Works When Storage Firewall Blocks Public Access? | Why / Requirements |
| :--- | :--- | :---: | :--- |
| **A. Plain Blob URL (`transcribe_from_url`)** | Azure Speech backend tries to HTTP `GET` the URL directly | **No (`NoAuthenticationInformation`)** | Fast Transcription's `audioUrl` parameter only performs an unauthenticated HTTP `GET`. It **does not** automatically attach your Speech Service Managed Identity token to `audioUrl`. |
| **B. SAS URL (`transcribe_from_url`)** | Azure Speech backend HTTP `GET`s the SAS URL directly | **Only if Trusted Azure Services is enabled** | Works in **~3.4 s** with **`0 MB` pod RAM** *only* if your ADLS Gen2 firewall allows **"Azure services on the trusted services list"** (`--bypass AzureServices`) + a **Resource Instance rule** for your Speech resource. If storage completely blocks external access, it fails with `403 Forbidden`. |
| **C. Pod/VM Streaming (ADLS $\rightarrow$ Pod $\rightarrow$ Speech)** | Your AKS Pod / VM authenticates to ADLS via **Managed Identity** and streams bytes to Speech | **Yes (Always Works)** | Your pod sits inside your VNet/Private Endpoint boundary, reads ADLS Gen2 using `DefaultAzureCredential`, and streams the audio out to Azure Speech. |

---

## 3. Deep-Dive Memory Analysis: Why Standard SDK Calls Spike in RAM

When we profiled the standard Azure Python SDKs on our **10-minute real spoken audio (`25.23 MB`)** using `tracemalloc`, we uncovered three root causes of high memory consumption:

### Root Cause #1: Why `speech_client.transcribe(audio=...)` Uses `56.21 MB` ($2\times$ File Size)
When you call `speech_client.transcribe(audio=downloader)`, the Azure Speech SDK passes your `downloader` stream to Python's `requests` library using the `files=` parameter (`multipart/form-data`).
1. **Copy #1 (`25.23 MB`)**: Inside `requests.models.PreparedRequest._encode_files`, `requests` runs:
   ```python
   elif hasattr(fp, "read"):
       fdata = fp.read()   # <-- Calls .read() ONCE with NO chunk size!
   ```
   Because `requests` calls `.read()` with no `size` argument, `StorageStreamDownloader.read()` loops through all `4 MB` chunks and assembles the **entire `25.23 MB` file** into a single `bytes` object (`fdata`).
2. **Copy #2 (`25.23 MB`)**: Next, `urllib3.filepost.encode_multipart_formdata` allocates a **second** buffer (`body = io.BytesIO()`) and copies all `25.23 MB` of `fdata` into `body`:
   $$25.23\text{ MB (\texttt{fdata})} + 25.23\text{ MB (\texttt{body})} + 4.00\text{ MB (chunk buffer)} + 1.75\text{ MB (SDK overhead)} = \mathbf{56.21\text{ MB}}$$
   For a **2-hour `320 MB` WAV file**, `speech_client.transcribe()` consumes **`~645 MB` of RAM** per request!
3. **Important Warning on Custom `.read(size=-1)` Wrappers**: Because `requests` (`files=`) only calls `fp.read()` **once**, writing a custom `.read()` that returns only a single `4 MB` chunk causes `requests` to upload only the first `4 MB` of audio (13 phrases instead of 75). To stream chunk-by-chunk without buffering the full file, you **must** pass an iterable/generator via `content=` / `data=` (never `files=`).

---

### Root Cause #2: Why `StreamDownloadGenerator.__len__()` in `azure-core` Adds `32.00 MB` (or `201 MB` by Default)
1. In `azure/storage/blob/_download.py` (line 83), `BlobClient` assembles each chunk by calling:
   ```python
   content = b"".join(list(data))
   ```
2. `data` is an `azure.core.pipeline.transport._requests_basic.StreamDownloadGenerator`, which defines:
   ```python
   def __len__(self):
       return self.content_length  # Returns HTTP Content-Length in BYTES (4,194,304)!
   ```
3. In CPython, calling `list(data)` uses `data.__len__()` as a length hint to pre-allocate the Python `list` pointer array. Because `__len__()` returns **`4,194,304` (bytes)** instead of **`16` (the number of 256 KB packets)**, CPython transiently allocates a list for **4,194,304 pointers** ($\times 8\text{ bytes on 64-bit Linux} = \mathbf{32.00\text{ MB}}$), puts 16 items into it, joins them, and frees the 32 MB list!
   * With the default `64 MB` `BlobClient` setting on a `25.23 MB` file, `list(data)` pre-allocates $26,460,044 \times 8\text{ B} = \mathbf{201.87\text{ MB}}$ just for an empty Python `list` (`236.12 MB` total Peak RAM)!
   * Removing that buggy length hint (`del StreamDownloadGenerator.__len__`) immediately drops Peak RAM from `40.48 MB` to **`12.47 MB`**.

---

### Root Cause #3: Why `BlobClient.download_blob().chunks()` Uses $3\times \text{Chunk Size}$ (`12.47 MB`)
When streaming `4 MB` chunks from `BlobClient.download_blob().chunks()` via `speech_client.send_request()`, three `4.00 MB` buffers exist simultaneously at the moment `Chunk #1` is assembled inside `b"".join(list(data))`:
1. **Buffer #1 (`4.00 MB` — Previous Chunk)**: Python's outer `for datablock in body:` loop inside `http.client` still holds a reference to `Chunk #0` until your generator's `yield` statement returns `Chunk #1`.
2. **Buffer #2 (`4.00 MB` — `list(data)` for `Chunk #1`)**: Sixteen `256 KB` network packets read from `urllib3`.
3. **Buffer #3 (`4.00 MB` — `b"".join(...)` for `Chunk #1`)**: The contiguous `4.00 MB` `bytes` object allocated before `list(data)` is freed.
   $$\text{Peak RAM} = 3 \times 4.00\text{ MB} + 0.47\text{ MB} = \mathbf{12.47\text{ MB}}$$

When using **HTTP Blob Fetch (`requests.get(stream=True)`) + `speech_client.send_request()`** ([`test_http_blob_plus_sdk_send_request.py`](test_http_blob_plus_sdk_send_request.py)), `b"".join(list(data))` is bypassed completely, dropping Peak RAM to **`10.27 MB`** with **no SDK monkey-patching needed**.

---

## 4. Recommended Production Implementations

### Option A (Best Overall — #6 in Table): HTTP Blob Fetch (MI) + `speech_client.send_request()` (`10.27 MB` Peak RAM)
See [`test_http_blob_plus_sdk_send_request.py`](test_http_blob_plus_sdk_send_request.py):
* Uses **Managed Identity (`DefaultAzureCredential`)** against a plain Blob URL (no SAS URLs).
* Uses **`speech_client.send_request()`** so you keep Azure Speech SDK auth, retry policies (`HttpBlobMultipartBody.__iter__` & `__deepcopy__`), error mapping, and the native `TranscriptionResult` return model.
* Needs **zero monkey-patching** and maintains a flat **`10.27 MB` Peak RAM** regardless of file size.

### Option B (#5 in Table): `BlobClient` SDK + `speech_client.send_request()` (`12.47 MB` / `40.48 MB` Peak RAM)
See [`test_sdk_send_request_streaming.py`](test_sdk_send_request_streaming.py):
* Uses `BlobClient(max_single_get_size=4*1024*1024, max_chunk_get_size=4*1024*1024)` + `BlobMultipartBody` + `speech_client.send_request()`.
* Achieves **`40.48 MB`** constant RAM out-of-the-box, or **`12.47 MB`** constant RAM with `del StreamDownloadGenerator.__len__`.

---

## 5. Audio Format & Compression Findings (PCM vs. WAV vs. Opus/Ogg)

1. **Streaming Raw `.pcm` Files Without Converting in Memory**:
   * If ADLS Gen2 stores raw headerless PCM (`.pcm`), you do **not** need to load the file into memory to convert it to WAV.
   * Simply `yield` a **44-byte RIFF/WAV header** (constructed in memory using the blob's byte length) before yielding the raw `.pcm` chunks. Extra RAM required: **44 bytes** (tested in [`run_speech_fast_transcription_poc.py`](run_speech_fast_transcription_poc.py)).
2. **Pre-Compressing Audio to Opus/Ogg in the Frontend (Angular `MediaRecorder`)**:
   * Recording in `audio/webm;codecs=opus` or `audio/ogg;codecs=opus` at `24–32 kbps` shrinks a **2-hour `320 MB` WAV file down to `~22 MB`** ($10\times$ smaller) with **zero loss in Speech-to-Text accuracy**.

---

## 6. Repository Scripts Guide

| Script | Description |
| :--- | :--- |
| [`test_http_blob_plus_sdk_send_request.py`](test_http_blob_plus_sdk_send_request.py) | **Recommended (#6)**: Plain Blob URL + Managed Identity HTTP streaming (`requests.get(stream=True)`) piped into `speech_client.send_request()` returning `TranscriptionResult` (`10.27 MB` Peak RAM). |
| [`test_sdk_send_request_streaming.py`](test_sdk_send_request_streaming.py) | **Recommended w/ `BlobClient` (#4 & #5)**: Retry-safe `BlobMultipartBody` + `BlobClient.download_blob().chunks()` piped into `speech_client.send_request()` returning `TranscriptionResult` (`12.47 MB` / `40.48 MB` Peak RAM). |
| [`test_pure_stream_low_ram.py`](test_pure_stream_low_ram.py) | **Pure HTTP Stream (#7)**: Zero-SDK-overhead HTTP `GET` $\rightarrow$ HTTP `POST` chunked generator (`4.06 MB` Peak RAM). |
| [`run_clean_comparison.py`](run_clean_comparison.py) | Head-to-head comparison of Plain URL + Managed Identity Bearer token using `client.transcribe()` vs. Pure REST generator (`4.77 MB` Peak RAM). |
| [`test_true_zero_buffer_stream.py`](test_true_zero_buffer_stream.py) | Side-by-side RAM & latency benchmark of `speech_client.transcribe()` (`56.21 MB`) vs. chunked multipart generator (`4 MB` and `16 MB` chunks). |
| [`test_10min_spoken_real.py`](test_10min_spoken_real.py) | Generates the 10-minute real spoken English WAV (`25.23 MB`, 75 phrases), uploads to ADLS Gen2, and benchmarks SAS URL (`3.44 s`), Default SDK (`236 MB`), and chunked streaming. |
| [`test_native_stream.py`](test_native_stream.py) | Tests passing `blob_client.download_blob()` directly into `TranscriptionContent` with `speech_client.transcribe()`. |
| [`test_pod_temp_file.py`](test_pod_temp_file.py) | Benchmarks downloading the blob to a pod `/tmp` file first (`download_to_stream`) and then streaming from disk (`6.14 s`, `4.68 MB` RAM + disk space). |
| [`test_consecutive_recordings_ram.py`](test_consecutive_recordings_ram.py) | Runs 3 consecutive 10-minute transcriptions back-to-back to verify RAM returns to `0.01 MB` between recordings with zero memory leaks. |
| [`benchmark_chunk_sizes.py`](benchmark_chunk_sizes.py) | Benchmarks chunk sizes (`256 KB`, `1 MB`, `4 MB`, `8 MB`, `16 MB`) against ADLS Gen2 download latency. |
| [`compare_full_vs_stream_latency.py`](compare_full_vs_stream_latency.py) | Multi-run statistical comparison (5 iterations each) of full in-memory download vs. `4 MB` streaming vs. `16 MB` streaming. |
| [`trace_memory_detailed.py`](trace_memory_detailed.py) | Line-by-line `tracemalloc` profiler showing exact memory allocations per chunk. |
| [`run_speech_fast_transcription_poc.py`](run_speech_fast_transcription_poc.py) | Initial end-to-end POC testing WAV and raw `.pcm` (with 44-byte in-flight WAV header framing). |
