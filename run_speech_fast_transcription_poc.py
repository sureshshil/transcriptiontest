import datetime
import os
import struct
import wave
import win32com.client
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionOptions
from azure.storage.blob import (
    BlobServiceClient,
    BlobSasPermissions,
    generate_blob_sas,
)

# Configuration
STORAGE_ACCOUNT_NAME = "fparecordingadls"
CONTAINER_NAME = "fpa-recording"
STORAGE_ACCOUNT_KEY = os.environ.get(
    "STORAGE_ACCOUNT_KEY",
    os.getenv("STORAGE_KEY", ""),
)

SPEECH_ENDPOINT = os.environ.get(
    "AZURE_SPEECH_ENDPOINT",
    "https://speech-poc-jp.cognitiveservices.azure.com/",
)
SPEECH_KEY = os.environ.get(
    "AZURE_SPEECH_KEY",
    os.getenv("SPEECH_KEY", ""),
)

TARGET_DURATION_SECONDS = 120  # 2 minutes


def generate_2min_audio_files(pcm_path="speech_sample_2min.pcm", wav_path="speech_sample_2min.wav"):
    """
    Synthesizes speech via SAPI with English text, padded/repeated to exactly 2 minutes (120 seconds).
    Saves raw 16-bit mono 16kHz PCM and standard WAV format.
    """
    print(f"[*] Step 1: Synthesizing real speech audio (~{TARGET_DURATION_SECONDS} seconds)...")

    # Sample paragraph designed for speech transcription test
    sentences = [
        "Welcome to the Azure Speech Fast Transcription proof of concept.",
        "In this demonstration, we are testing the performance of high speed speech recognition using audio stored in Azure Data Lake Storage.",
        "The raw audio file is initially generated in linear pulse code modulation format, commonly known as raw PCM.",
        "It is then packaged into a standard Resource Interchange File Format WAV container with proper headers specifying sample rate and channel layout.",
        "Azure Fast Transcription provides rapid turnaround time, making it ideal for interactive call analytics, batch processing, and conversational AI applications.",
        "Cloud native architectures benefit greatly from decoupled storage and processing, allowing scalable analytics pipelines across global enterprise data lakes.",
        "We are verifying that the Transcription Client URL method can securely fetch the target audio asset via Shared Access Signature token authentication.",
        "Every spoken word is accurately captured and transcribed into text with timestamps and confidence scores.",
        "This completes one full cycle of the continuous speech narrative for our audio benchmarking pipeline.",
    ]

    temp_chunk_wav = "temp_sentence_chunk.wav"
    speaker = win32com.client.Dispatch("SAPI.SpVoice")
    stream = win32com.client.Dispatch("SAPI.SpFileStream")
    
    # 3 = SSFMCreateForWrite
    stream.Open(temp_chunk_wav, 3, False)
    speaker.AudioOutputStream = stream

    # Repeat speech sentences to achieve substantial realistic speech content
    full_text = " ".join(sentences * 4)
    speaker.Speak(full_text)
    stream.Close()

    # Read synthesized audio frames
    with wave.open(temp_chunk_wav, "rb") as w:
        n_channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        frames = w.readframes(w.getnframes())

    if os.path.exists(temp_chunk_wav):
        os.remove(temp_chunk_wav)

    # Calculate required bytes for 120 seconds
    target_frames = framerate * TARGET_DURATION_SECONDS
    bytes_per_frame = n_channels * sampwidth
    target_bytes = target_frames * bytes_per_frame

    # Pad or tile raw PCM data to exactly 120 seconds
    if len(frames) < target_bytes:
        repeat_count = (target_bytes // len(frames)) + 1
        tiled = (frames * repeat_count)[:target_bytes]
    else:
        tiled = frames[:target_bytes]

    # 1. Save raw PCM
    with open(pcm_path, "wb") as f_pcm:
        f_pcm.write(tiled)

    # 2. Save WAV file with header
    with wave.open(wav_path, "wb") as f_wav:
        f_wav.setnchannels(n_channels)
        f_wav.setsampwidth(sampwidth)
        f_wav.setframerate(framerate)
        f_wav.writeframes(tiled)

    duration = len(tiled) / (framerate * bytes_per_frame)
    print(f"    [+] Created raw PCM: {pcm_path} ({len(tiled):,} bytes)")
    print(f"    [+] Created WAV:     {wav_path} ({os.path.getsize(wav_path):,} bytes, {duration:.1f}s, {framerate}Hz)")
    return framerate, n_channels, sampwidth


def pcm_to_wav_stream(pcm_bytes, framerate=22050, channels=1, sampwidth=2):
    """
    Converts raw PCM byte stream to a valid WAV formatted byte stream by prepending RIFF/WAVE header.
    """
    data_size = len(pcm_bytes)
    byte_rate = framerate * channels * sampwidth
    block_align = channels * sampwidth

    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        36 + data_size,
        b"WAVE",
        b"fmt ",
        16,  # Subchunk1Size for PCM
        1,   # AudioFormat (1 = PCM)
        channels,
        framerate,
        byte_rate,
        block_align,
        sampwidth * 8,  # BitsPerSample
        b"data",
        data_size,
    )
    return header + pcm_bytes


def main():
    print("=" * 70)
    print("Azure Speech Fast Transcription POC with ADLS Gen2")
    print("=" * 70)

    # 1. Generate local 2-minute PCM audio and WAV
    local_pcm = "sample_2min.pcm"
    local_wav = "sample_2min.wav"
    framerate, channels, sampwidth = generate_2min_audio_files(local_pcm, local_wav)

    # 2. Connect to ADLS Gen2
    print("\n[*] Step 2: Uploading files to ADLS Gen2 (fparecordingadls / fpa-recording)...")
    connection_string = (
        f"DefaultEndpointsProtocol=https;AccountName={STORAGE_ACCOUNT_NAME};"
        f"AccountKey={STORAGE_ACCOUNT_KEY};EndpointSuffix=core.windows.net"
    )
    blob_service_client = BlobServiceClient.from_connection_string(connection_string)
    container_client = blob_service_client.get_container_client(CONTAINER_NAME)

    # Upload raw PCM into "pcm/" virtual directory
    pcm_blob_name = "pcm/recording_2min.pcm"
    with open(local_pcm, "rb") as f_pcm:
        pcm_blob_client = container_client.get_blob_client(pcm_blob_name)
        pcm_blob_client.upload_blob(f_pcm, overwrite=True)
        print(f"    [+] Uploaded PCM to: {CONTAINER_NAME}/{pcm_blob_name}")

    # Read back PCM from ADLS Gen2 and convert to WAV format in container
    print("\n[*] Step 3: Converting PCM from ADLS Gen2 to WAV format...")
    downloaded_pcm = pcm_blob_client.download_blob().readall()
    wav_bytes = pcm_to_wav_stream(downloaded_pcm, framerate, channels, sampwidth)

    wav_blob_name = "wav/recording_2min.wav"
    wav_blob_client = container_client.get_blob_client(wav_blob_name)
    wav_blob_client.upload_blob(wav_bytes, overwrite=True)
    print(f"    [+] Uploaded converted WAV to: {CONTAINER_NAME}/{wav_blob_name} ({len(wav_bytes):,} bytes)")

    # 3. Generate SAS token URL for Azure Fast Transcription
    print("\n[*] Step 4: Generating SAS URL for the WAV blob...")
    sas_token = generate_blob_sas(
        account_name=STORAGE_ACCOUNT_NAME,
        container_name=CONTAINER_NAME,
        blob_name=wav_blob_name,
        account_key=STORAGE_ACCOUNT_KEY,
        permission=BlobSasPermissions(read=True),
        expiry=datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=2),
    )
    wav_sas_url = f"{wav_blob_client.url}?{sas_token}"
    print(f"    [+] WAV SAS URL successfully created.")

    # 4. Transcribe using Azure Fast Transcription SDK URL method
    print("\n[*] Step 5: Invoking Azure Fast Transcription SDK via URL method (`transcribe_from_url`)...")
    transcription_client = TranscriptionClient(
        endpoint=SPEECH_ENDPOINT,
        credential=AzureKeyCredential(SPEECH_KEY),
    )

    options = TranscriptionOptions(locales=["en-US"])
    start_time = datetime.datetime.now()

    # URL method call
    result = transcription_client.transcribe_from_url(audio_url=wav_sas_url, options=options)
    elapsed = (datetime.datetime.now() - start_time).total_seconds()

    print("\n" + "=" * 70)
    print("TRANSCRIPTION COMPLETED SUCCESSFULLY")
    print("=" * 70)
    print(f"Elapsed Time for Fast Transcription: {elapsed:.2f} seconds (for 120 seconds of audio!)")
    if hasattr(result, "duration_milliseconds") and result.duration_milliseconds:
        print(f"Audio Duration: {result.duration_milliseconds / 1000:.2f} seconds")

    print("\n[--- Transcribed Text ---]")
    if result.combined_phrases:
        for idx, phrase in enumerate(result.combined_phrases):
            print(f"Phrase {idx + 1}: {phrase.text}")
    else:
        print("No text phrases found.")

    print("\n[--- Sample Phrase Details (first 3) ---]")
    for i, p in enumerate(result.phrases[:3]):
        print(f"  [{i+1}] Offset: {p.offset_milliseconds}ms, Duration: {p.duration_milliseconds}ms: \"{p.text}\"")

    # Clean up local temporary files
    for tmp in [local_pcm, local_wav]:
        if os.path.exists(tmp):
            os.remove(tmp)
    print("\n[*] Local cleanup done. ADLS Gen2 artifacts preserved.")


if __name__ == "__main__":
    main()
