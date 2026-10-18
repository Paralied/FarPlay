import asyncio
import fractions
import threading
import time
import numpy as np
import mss
from aiortc import MediaStreamTrack
from av import VideoFrame, AudioFrame

class DesktopVideo(MediaStreamTrack):
    """Capture on one dedicated thread; never block signaling or input handling.

    Work is demand-driven: no frame queue can accumulate behind the encoder.
    MSS must be created, used and closed on the same thread on Windows.
    """
    kind = 'video'
    def __init__(self, width=1280, fps=60):
        super().__init__()
        from concurrent.futures import ThreadPoolExecutor
        self.width, self.fps = width, fps
        self.started = time.monotonic()
        self.capture = None
        self.worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix='FarPlayCapture')
        self.closed = False
        self.last = 0

    def capture_frame(self):
        if self.capture is None:
            self.capture = mss.mss()
        shot = self.capture.grab(self.capture.monitors[1])
        # MSS is already packed BGRA. Avoid the full-desktop BGR slice/copy.
        frame = VideoFrame.from_ndarray(np.asarray(shot), format='bgra')
        width = min(self.width, shot.width) // 2 * 2
        height = int(shot.height * width / shot.width) // 2 * 2
        frame = frame.reformat(width=width, height=height, format='yuv420p')
        frame.pts = int((time.monotonic() - self.started) * 90000)
        frame.time_base = fractions.Fraction(1, 90000)
        return frame

    async def recv(self):
        from aiortc.mediastreams import MediaStreamError
        if self.closed:
            raise MediaStreamError
        await asyncio.sleep(max(0, 1 / self.fps - (time.monotonic() - self.last)))
        if self.closed:
            raise MediaStreamError
        self.last = time.monotonic()
        return await asyncio.get_running_loop().run_in_executor(self.worker, self.capture_frame)

    def close_capture(self):
        if self.capture is not None:
            self.capture.close()
            self.capture = None

    def stop(self):
        if self.closed:
            return
        self.closed = True
        super().stop()
        # Queue cleanup behind any in-flight grab, on its owning thread.
        self.worker.submit(self.close_capture)
        self.worker.shutdown(wait=False)

class DesktopAudio(MediaStreamTrack):
    kind = 'audio'
    def __init__(self, report):
        super().__init__()
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue(maxsize=2)
        self.quit = threading.Event()
        self.samples = 0
        self.report = report
        threading.Thread(target=self.capture, daemon=True).start()
    def enqueue(self, data):
        if self.queue.full():
            self.queue.get_nowait()
        self.queue.put_nowait(data)
    def capture(self):
        try:
            import soundcard as sc
            speaker = sc.default_speaker()
            mic = sc.get_microphone(id=speaker.id, include_loopback=True)
            with mic.recorder(samplerate=48000, channels=2, blocksize=960) as recorder:
                while not self.quit.is_set():
                    data = recorder.record(numframes=960)
                    self.loop.call_soon_threadsafe(self.enqueue, data)
        except Exception as exc:
            self.report('Audio unavailable: ' + str(exc))
    async def recv(self):
        try:
            data = await asyncio.wait_for(self.queue.get(), timeout=0.02)
        except TimeoutError:
            data = np.zeros((960, 2), dtype=np.float32)
        data = np.ascontiguousarray(data.T, dtype=np.float32)
        frame = AudioFrame.from_ndarray(data, format='fltp', layout='stereo')
        frame.sample_rate = 48000
        frame.time_base = fractions.Fraction(1, 48000)
        frame.pts = self.samples
        self.samples += frame.samples
        return frame
    def stop(self):
        self.quit.set()
        super().stop()
