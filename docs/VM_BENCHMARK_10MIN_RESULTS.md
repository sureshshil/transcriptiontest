# Azure Fast Transcription: 10-Minute Audio Benchmark on Azure VM

- **Environment**: Azure VM `vm-b1ls` (`20.89.145.69`) in `japaneast`
- **Audio File**: 10 Minutes (600 seconds), 16kHz Mono 16-bit PCM WAV (`19,200,044` bytes / `18.31 MB`)
- **Storage**: ADLS Gen2 `fparecordingadls` (`fpa-recording/wav/audio_10min.wav`)
- **Speech Service**: `speech-poc-jp.cognitiveservices.azure.com` (`japaneast`)

---

## Benchmark Results

| Method | Peak Audio RAM | Blob Download Time | Transcribe / Execution Time | Total Latency |
| :--- | :--- | :--- | :--- | :--- |
| **1. Single Shot (Full Memory)** | **18.31 MB** | 0.31 s | 3.00 s | **3.31 s** |
| **2. Chunked Streaming (4MB max)** | **4.00 MB** | *Pipelined concurrently* | 0.91 s | **0.91 s** |
| **3. SAS URL (Direct Storage-to-Speech)** | **0.00 MB** | *0.00 s (Direct)* | 2.85 s | **2.85 s** |

---

## Key Observations

1. **Why Streaming (Method 2) is the fastest (`0.91 s`)**:
   - Azure Speech Fast Transcription endpoint supports streaming multipart data using chunked transfer.
   - The VM pulls a 4MB chunk from ADLS and streams it into the HTTP socket simultaneously.
   - Speech Service begins processing frames as chunks arrive, overlapping transfer and transcription.

2. **Why Single Shot (Method 1) took `3.31 s`**:
   - The entire 19.2 MB is buffered in RAM first before opening the HTTP upload connection.
   - Inside the same Azure region, downloading 18 MB took only **0.31 seconds** (vs ~3.4s when testing locally).

3. **Why SAS URL (Method 3) took `2.85 s`**:
   - Zero VM memory or bandwidth used.
   - Speech Service downloads directly from ADLS Storage over the internal backbone and executes transcription.
