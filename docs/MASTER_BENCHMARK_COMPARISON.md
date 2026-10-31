# Azure Speech Fast Transcription + ADLS Gen2: Master Benchmark Comparison (All 8 Options)

- **Audio File**: `wav/speech_10min_spoken.wav` (`25.23 MB` / `26,460,044` bytes, `600.0 s` / 10.0 minutes)
- **Spoken Content**: 75 conversational English phrases, 1,313 words
- **Benchmark Environment**: Azure Linux VM `vm-b1ls` (`Standard_B1ls`, `0.5 GB RAM`, `japaneast`) $\rightarrow$ ADLS Gen2 (`fparecordingadls`, `japaneast`) $\rightarrow$ Azure AI Speech (`speech-poc-jp`, `japaneast`)

---

## 1. Consolidated Master Benchmark Table (All 8 Options)

| # | Method & Script | Blob Fetch Method | Speech API Call Method | Works w/ Strict Storage Firewall? | Returns SDK `TranscriptionResult`? | Needs SDK Patch? | Latency (10-min Audio) | Peak RAM (25.2 MB Audio) | Peak RAM (320 MB 2-Hr Audio) | Full Audio (75 Phrases)? |
| :-: | :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **1** | **SAS URL (Server-to-Server)**<br>[`test_10min_spoken_real.py`](../test_10min_spoken_real.py) | None *(Speech fetches SAS URL directly)* | `speech_client.transcribe_from_url()` | Only if Trusted Azure Services enabled | Yes | No | **`3.44 s`** | **`0.22 MB`** | **`0.22 MB`** | Yes (75) |
| **2** | **Default SDK (`64 MB` chunks)**<br>[`test_10min_spoken_real.py`](../test_10min_spoken_real.py) | `BlobClient` *(Default 64 MB)* | `speech_client.transcribe()` | Yes (Pod MI) | Yes | No | `5.04 s` | `236.12 MB` | `> 1,200 MB` *(OOM)* | Yes (75) |
| **3** | **Tuned SDK (`4 MB` chunks)**<br>[`test_true_zero_buffer_stream.py`](../test_true_zero_buffer_stream.py) | `BlobClient` *(4 MB chunks)* | `speech_client.transcribe()` | Yes (Pod MI) | Yes | No | `4.54 s` | `56.21 MB` | `~645 MB` *(2x file)* | Yes (75) |
| **4** | **`BlobMultipartBody` + `send_request` (Unpatched)**<br>[`test_sdk_send_request_streaming.py`](../test_sdk_send_request_streaming.py) | `BlobClient` *(4 MB chunks + MI)* | `speech_client.send_request()` | Yes (Pod MI) | Yes | No | `5.15 s` | **`40.48 MB`** | **`40.48 MB`** *(Constant)* | Yes (75) |
| **5** | **`BlobMultipartBody` + `send_request` (Patched)**<br>[`test_sdk_send_request_streaming.py`](../test_sdk_send_request_streaming.py) | `BlobClient` *(4 MB chunks + MI)* | `speech_client.send_request()` | Yes (Pod MI) | Yes | Yes (`del __len__`) | **`4.71 s`** | **`12.47 MB`** | **`12.47 MB`** *(Constant)* | Yes (75) |
| **6** | **HTTP Blob + SDK `send_request` (Recommended)**<br>[`test_http_blob_plus_sdk_send_request.py`](../test_http_blob_plus_sdk_send_request.py) | **`requests.get(stream=True)` + MI Token** | **`speech_client.send_request()`** | **Yes (Pod MI)** | **Yes** | **No** | **`~4.70 s`** | **`10.27 MB`** | **`10.27 MB`** *(Constant)* | **Yes (75)** |
| **7** | **Pure HTTP Stream (No SDK)**<br>[`test_pure_stream_low_ram.py`](../test_pure_stream_low_ram.py) / [`run_clean_comparison.py`](../run_clean_comparison.py) | `requests.get(stream=True)` + MI Token | `requests.post(data=gen)` | Yes (Pod MI) | No *(Raw dict)* | No | **`4.65 s`** | **`4.06 – 4.77 MB`** | **`4.06 – 4.77 MB`** *(Constant)* | Yes (75) |
| **8** | **Pod `/tmp` Temp File**<br>[`test_pod_temp_file.py`](../test_pod_temp_file.py) | `BlobClient.download_to_stream(file)` | `requests.post(data=gen)` | Yes (Pod MI) | No *(Raw dict)* | No | `6.14 s` *(Slower)* | `4.68 MB` *(+ Disk)* | `4.68 MB` *(+ 320 MB Disk)* | Yes (75) |

---

## 2. Detailed Breakdown of Each Option's Memory Formula

| Option | Memory Formula | Exact Math for `25.23 MB` File (`4 MB` Chunks) |
| :--- | :--- | :--- |
| **Option #2 (Default SDK, `64 MB`)** | $2\times\text{File} + (\text{File Bytes}\times 8\text{ B pointer list})$ | $25.23 + 25.23 + 201.87\text{ MB (\texttt{list(data)})} \approx \mathbf{236.12\text{ MB}}$ |
| **Option #3 (Tuned SDK, `4 MB`)** | $2\times\text{File} + 1\times\text{Chunk} + \text{SDK overhead}$ | $25.23\text{ (\texttt{fdata})} + 25.23\text{ (\texttt{BytesIO})} + 4.00 + 1.75 = \mathbf{56.21\text{ MB}}$ |
| **Option #4 (`BlobClient` + `send_request` Unpatched)** | $2\times\text{Chunk} + (\text{Chunk Bytes}\times 8\text{ B pointer list})$ | $8.48\text{ MB} + 32.00\text{ MB (\texttt{list(data)} 4M pointers)} = \mathbf{40.48\text{ MB}}$ |
| **Option #5 (`BlobClient` + `send_request` Patched)** | $3\times\text{Chunk} + \text{SDK overhead}$ | $4.00\text{ (prev)} + 4.00\text{ (\texttt{list(data)})} + 4.00\text{ (\texttt{join})} + 0.47 = \mathbf{12.47\text{ MB}}$ |
| **Option #6 (HTTP Blob + `send_request`)** | $2.5\times\text{Chunk} + \text{SDK overhead}$ | $4.00\text{ (prev)} + 4.00\text{ (curr)} + 2.00\text{ (socket)} + 0.27 = \mathbf{10.27\text{ MB}}$ |
| **Option #7 (Pure HTTP `GET` $\rightarrow$ `POST`)** | $1\times\text{Chunk} + \text{HTTP overhead}$ | $4.00\text{ MB} + 0.06\text{–}0.77\text{ MB} = \mathbf{4.06\text{–}4.77\text{ MB}}$ |
| **Option #8 (Pod `/tmp` Temp File)** | $1\times\text{Chunk} + \text{Disk Space Equal to File Size}$ | $\mathbf{4.68\text{ MB RAM}} + 25.23\text{ MB Disk (or 320 MB Disk for 2-hr)}$ |
