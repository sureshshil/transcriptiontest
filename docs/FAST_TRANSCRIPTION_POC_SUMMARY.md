# Azure Speech Fast Transcription POC with ADLS Gen2

## 1. Provisioned Infrastructure
- **Resource Group**: `rg-speech-poc` (`japaneast`)
- **Speech Service**: `speech-poc-jp` (Kind: `SpeechServices`, Tier: `F0` Free)
  - Endpoint: `https://speech-poc-jp.cognitiveservices.azure.com/` (Custom Subdomain)
- **ADLS Gen2 Storage**: `fparecordingadls` (`IsHnsEnabled: True`)
  - Container / Filesystem: `fpa-recording`
  - PCM Directory: `fpa-recording/pcm/`
  - WAV Directory: `fpa-recording/wav/`

## 2. Implemented Workflow
1. **Audio Synthesis & PCM Creation**:
   - Synthesized natural English speech audio matching exactly **2 minutes (120 seconds)**.
   - Saved 16-bit 22.05 kHz mono linear PCM (`5,292,000` bytes).
2. **ADLS Gen2 Upload**:
   - Uploaded raw PCM file to ADLS Gen2: `fpa-recording/pcm/recording_2min.pcm`.
3. **PCM to WAV Conversion**:
   - Downloaded PCM stream and dynamically prepended RIFF/WAVE header (44-byte standard PCM format).
   - Saved converted audio to ADLS Gen2: `fpa-recording/wav/recording_2min.wav` (`5,292,044` bytes).
4. **SAS Token URL Generation**:
   - Generated a secure Shared Access Signature (SAS) token for the WAV blob.
5. **Azure Fast Transcription SDK Execution**:
   - Used `azure-ai-transcription` SDK with `transcribe_from_url(audio_url=wav_sas_url, options=options)`.

## 3. Benchmark Results
- **Audio Duration**: 120.00 seconds (2.0 minutes)
- **Fast Transcription SDK Latency**: **1.66 seconds**
- **Transcription Status**: Succeeded with phrase breakdown and offset timestamps.
