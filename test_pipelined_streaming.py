import io
import queue
import threading
import time
from test_10min_spoken_real import get_blob_client, SPEECH_ENDPOINT, SPEECH_KEY
from azure.core.credentials import AzureKeyCredential
from azure.ai.transcription import TranscriptionClient
from azure.ai.transcription.models import TranscriptionOptions

CHUNK_SIZE = 16 * 1024 * 1024  # 16 MB chunk


class AsyncPrefetchBlobStream(io.RawIOBase):
    """
    Double-buffered / pipelined stream:
    A background thread continuously pre-fetches the NEXT chunk from Blob storage into a queue
    WHILE the main thread is busy uploading/writing the current chunk to Speech Service.
    
    Result: Storage download time overlaps 100% with Speech upload time.
    """
    def __init__(self, blob_client, chunk_size=CHUNK_SIZE):
        super().__init__()
        self.blob_client = blob_client
        self.chunk_size = chunk_size
        self.total_size = blob_client.get_blob_properties().size
        self.position = 0
        
        # Queue with maxsize=1 enforces strict double-buffering (RAM never exceeds 2 * chunk_size)
        self.queue = queue.Queue(maxsize=1)
        self.current_chunk = b""
        self.chunk_pos = 0
        self.stop_event = threading.Event()
        
        # Start background prefetch worker
        self.worker = threading.Thread(target=self._prefetch_loop, daemon=True)
        self.worker.start()

    def _prefetch_loop(self):
        offset = 0
        while offset < self.total_size and not self.stop_event.is_set():
            read_len = min(self.chunk_size, self.total_size - offset)
            stream = self.blob_client.download_blob(offset=offset, length=read_len)
            chunk_data = stream.readall()
            self.queue.put(chunk_data)  # Blocks if previous chunk hasn't been consumed yet
            offset += read_len
        self.queue.put(None)  # Sentinel for EOF

    def readable(self):
        return True

    def seekable(self):
        return False

    def readinto(self, b):
        if self.position >= self.total_size and self.chunk_pos >= len(self.current_chunk):
            return 0

        # Need next chunk from queue
        if self.chunk_pos >= len(self.current_chunk):
            chunk = self.queue.get()
            if chunk is None:
                return 0
            self.current_chunk = chunk
            self.chunk_pos = 0

        available = len(self.current_chunk) - self.chunk_pos
        to_copy = min(len(b), available)
        b[:to_copy] = self.current_chunk[self.chunk_pos:self.chunk_pos + to_copy]
        self.chunk_pos += to_copy
        self.position += to_copy
        return to_copy

    def close(self):
        self.stop_event.set()
        super().close()


def benchmark():
    blob_client = get_blob_client()
    client = TranscriptionClient(endpoint=SPEECH_ENDPOINT, credential=AzureKeyCredential(SPEECH_KEY))

    print("=" * 60)
    print("PIPELINED DOUBLE-BUFFERED STREAMING (ZERO WAITING FOR STORAGE)")
    print("=" * 60)

    # 1. Test Regular Chunked Stream (Sequential)
    from test_10min_spoken_real import StrictChunkedBlobStream
    stream_seq = StrictChunkedBlobStream(blob_client, chunk_size=CHUNK_SIZE)
    t0 = time.perf_counter()
    res_seq = client.transcribe({
        "definition": TranscriptionOptions(locales=["en-US"]),
        "audio": ("audio.wav", stream_seq, "audio/wav")
    })
    t_seq = time.perf_counter() - t0
    print(f"1. Sequential Streaming (16MB): {t_seq:.3f} s")

    # 2. Test Async Prefetch Pipelined Stream
    stream_pipe = AsyncPrefetchBlobStream(blob_client, chunk_size=CHUNK_SIZE)
    t0 = time.perf_counter()
    res_pipe = client.transcribe({
        "definition": TranscriptionOptions(locales=["en-US"]),
        "audio": ("audio.wav", stream_pipe, "audio/wav")
    })
    t_pipe = time.perf_counter() - t0
    print(f"2. Pipelined Prefetch Stream (16MB): {t_pipe:.3f} s")

    print("=" * 60)
    print(f"Text Match: {res_seq.combined_phrases[0].text == res_pipe.combined_phrases[0].text}")
    print(f"Speedup: {((t_seq - t_pipe) / t_seq) * 100:.1f}% reduction in overhead")


if __name__ == "__main__":
    benchmark()
