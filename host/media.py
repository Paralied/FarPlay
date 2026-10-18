import asyncio
import fractions
import threading
import time
import numpy as np
import mss
from aiortc import MediaStreamTrack
from av import VideoFrame, AudioFrame

class DesktopVideo(MediaStreamTrack):
    kind = 'video'
    def __init__(self, width=1280, fps=30):
        super().__init__()
        self.width, self.fps = width, fps
        self.started = time.monotonic()
        self.capture = None
    async def recv(self):
        await asyncio.sleep(max(0, 1 / self.fps - (time.monotonic() - getattr(self, 'last', 0))))
        self.last = time.monotonic()
        if self.capture is None:
            self.capture = mss.mss()
        shot = self.capture.grab(self.capture.monitors[1])
        frame = VideoFrame.from_ndarray(np.asarray(shot)[:, :, :3].copy(), format='bgr24')
        width = min(self.width, shot.width) // 2 * 2
        height = int(shot.height * width / shot.width) // 2 * 2
        frame = frame.reformat(width=width, height=height, format='yuv420p')
        frame.pts = int((time.monotonic() - self.started) * 90000)
        frame.time_base = fractions.Fraction(1, 90000)
        return frame
    def stop(self):
        super().stop()
        if self.capture is not None:
            self.capture.close()
            self.capture = None

class DesktopAudio(MediaStreamTrack):
    kind = 'audio'
    def __init__(self, report):
        super().__init__()
        self.loop = asyncio.get_running_loop()
        self.queue = asyncio.Queue(maxsize=5)
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
