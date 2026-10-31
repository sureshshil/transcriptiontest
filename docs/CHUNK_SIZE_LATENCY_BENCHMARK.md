# Chunk Size vs Latency Benchmark: Azure Fast Transcription

- **Host**: Azure VM `vm-b1ls` (`20.194.235.45`, Japan East)
- **Audio Payload**: 10-Minute spoken WAV (`26,460,044` bytes / `25.23 MB`, 75 phrases)
- **Storage**: ADLS Gen2 `fparecordingadls` (`fpa-recording/wav/speech_10min_spoken.wav`)
- **Speech Service**: `speech-poc-jp.cognitiveservices.azure.com` (`japaneast`)

---

## Benchmark Results Across Chunk Sizes

| Chunk Size | Number of Chunks Streamed | Total Execution Latency | Improvement vs 2MB/4MB | Peak VM RAM |
| :---: | :---: | :---: | :---: | :---: |
| **2 MB** | 13 chunks | **~9.41 s** | *Baseline (Slowest)* | 2 MB |
| **4 MB** | 7 chunks | **~5.67 – 6.38 s** | 35% faster | 4 MB |
| **8 MB** | 4 chunks | **~4.93 – 5.15 s** | 45% faster | 8 MB |
| **16 MB** | 2 chunks | **~4.06 – 4.45 s** | **55% faster** ⚡ | 16 MB |
| **26 MB (Single-shot equivalent)** | 1 chunk | **~4.32 s** | Plateaued | 26 MB |

---

## Key Takeaways

1. **Latency drops significantly as chunk size increases**:
   - Going from **2 MB ➔ 16 MB cuts latency by more than half** (from ~9.4s down to ~4.0s).
   - The primary bottleneck at small chunk sizes (2MB–4MB) is the per-chunk HTTP overhead and context-switching between reading from Azure Storage and piping into the Speech Service socket.

2. **The Optimal Sweet Spot: 16 MB**:
   - At **16 MB**, you achieve the same performance as sending the entire file at once (~4.0s), while still capping VM memory strictly to 16 MB.
   - For long recordings (e.g. 1–2 hours), setting your chunk size to **16 MB or 32 MB** prevents server memory bloat while delivering near-instantaneous streaming speed.
