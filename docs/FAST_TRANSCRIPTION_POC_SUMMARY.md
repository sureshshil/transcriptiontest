# Azure Speech Fast Transcription POC with ADLS Gen2

## 1. Provisioned Infrastructure
- **Resource Group**: `rg-speech-poc` (`japaneast`)
- **Speech Service**: `speech-poc-jp` (Kind: `SpeechServices`, Tier: `F0` Free)
  - Endpoint: `https://speech-poc-jp.cognitiveservices.azure.com/` (Custom Subdomain)
- **ADLS Gen2 Storage**: `fparecordingadls` (`IsHnsEnabled: True`)
  - Container / Filesystem: `fpa-recording`
  - PCM Directory: `fpa-recording/pcm/`
  - WAV Directory: `fpa-recording/wav/` (`speech_10min_spoken.wav` — 10-min spoken English, `25.23 MB`, 75 phrases)

---

## 2. Consolidated Master Benchmark Comparison (All 8 Options)

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
