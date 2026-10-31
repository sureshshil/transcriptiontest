# Azure Fast Transcription: 10-Minute Real Speech Benchmark

- **File**: `wav/speech_10min_spoken.wav` (10.0 minutes / 600.0 seconds, 22.05 kHz)
- **File Size**: 26,460,044 bytes (~26.46 MB)
- **Content**: 1,313 spoken English words, 75 conversational phrases
- **Environment**: Azure VM `vm-b1ls` (`20.89.145.69`) in `japaneast`

---

## 1. Text Output Verification

| Method | Audio Duration Transcribed | Word Count | Phrase Count | Text Match |
| :--- | :--- | :--- | :--- | :--- |
| **Method 1 (Single Shot)** | 600.0 s (10 min) | 1,313 | 75 | **Exact 100% Match** |
| **Method 2 (4MB Chunked Stream)** | 600.0 s (10 min) | 1,313 | 75 | **Exact 100% Match** |
| **Method 3 (SAS URL)** | 600.0 s (10 min) | 1,313 | 75 | **Exact 100% Match** |

> **Result**: `Method 1 == Method 2 == Method 3: TRUE`  
> All 3 methods produce identical transcription text and phrase timings.

---

## 2. Accurate Timing Comparison

| Method | Peak Audio RAM | Total Execution Time |
| :--- | :--- | :--- |
| **3. SAS URL (Direct Storage-to-Speech)** | **0.0 MB** | **`4.07 s`** 🏆 |
| **1. Single Shot (Full RAM Buffer)** | **26.5 MB** | **`4.96 s`** |
| **2. Chunked Stream (4MB Max RAM)** | **4.0 MB** | **`6.83 s`** |

---

## 3. Analysis of Why Timings Differ:
- **SAS URL (`4.07 s`)**: The fastest because zero audio bytes pass through the VM. The Speech Service streams the 26.5 MB directly from ADLS Storage over the internal data center network.
- **Single Shot (`4.96 s`)**: Fast because inside the Azure region, downloading 26 MB takes just ~0.35s, and uploading a contiguous memory buffer is very efficient.
- **Chunked Streaming (`6.83 s`)**: Slightly slower because chunked HTTP requests make sequential block requests (`4 MB x 7 chunks`) over the socket, introducing small I/O synchronization pauses. Its major advantage is keeping RAM consumption strictly bounded to 4MB regardless of how long the audio is.
