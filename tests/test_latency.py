"""Check event-loop responsiveness and capture lifetime without a real desktop."""
import asyncio
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'host'))
from media import DesktopVideo
from control import Controller

class LatencyTests(unittest.IsolatedAsyncioTestCase):
    async def test_capture_does_not_block_controls_and_closes_on_owner_thread(self):
        started, closed = threading.Event(), threading.Event()
        threads=[]
        class Shot:
            width,height=320,180
            def __array__(self,dtype=None,copy=None):
                return np.zeros((180,320,4),dtype=np.uint8)
        class Capture:
            monitors=[{},{}]
            def __init__(self):threads.append(threading.get_ident())
            def grab(self,monitor):
                threads.append(threading.get_ident());started.set();time.sleep(.12);return Shot()
            def close(self):threads.append(threading.get_ident());closed.set()
        with patch('media.mss.mss',Capture):
            track=DesktopVideo(width=320,fps=60)
            task=asyncio.create_task(track.recv())
            await asyncio.to_thread(started.wait,1)
            # A slow grab must leave the event loop free to handle input.
            self.assertFalse(task.done())
            events=[];Controller(lambda *x:events.append(x)).handle({'type':'key','key':'w','down':True})
            self.assertEqual(events,[('key','w',True)])
            frame=await asyncio.wait_for(task,2)
            self.assertEqual((frame.width,frame.height),(320,180))
            track.stop();track.stop()
            self.assertTrue(await asyncio.to_thread(closed.wait,1))
            self.assertEqual(len(set(threads)),1)
            self.assertNotEqual(threads[0],threading.get_ident())

    async def test_cancel_inflight_capture_still_closes(self):
        closed=threading.Event()
        class Capture:
            monitors=[{},{}]
            def grab(self,monitor):time.sleep(.06);raise RuntimeError('display changed')
            def close(self):closed.set()
        with patch('media.mss.mss',Capture):
            track=DesktopVideo()
            task=asyncio.create_task(track.recv())
            await asyncio.sleep(.02)
            task.cancel();track.stop()
            await asyncio.gather(task,return_exceptions=True)
            self.assertTrue(await asyncio.to_thread(closed.wait,1))

    async def test_display_change_recreates_capture_and_video_resumes(self):
        instances=[]
        class Shot:
            width,height=320,180
            def __array__(self,dtype=None,copy=None):return np.zeros((180,320,4),dtype=np.uint8)
        class Capture:
            monitors=[{},{}]
            def __init__(self):self.index=len(instances);self.closed=False;instances.append(self)
            def grab(self,monitor):
                if self.index==0:raise OSError('display mode changed')
                return Shot()
            def close(self):self.closed=True
        with patch('media.mss.mss',Capture):
            track=DesktopVideo(width=320)
            try:
                with self.assertLogs(level='WARNING'):
                    frame=await asyncio.wait_for(track.recv(),2)
                self.assertEqual(frame.width,320)
                self.assertEqual(len(instances),2)
                self.assertTrue(instances[0].closed)
            finally:track.stop()

class EncoderTests(unittest.TestCase):
    def test_fast_h264_emits_and_decodes_without_delayed_frames(self):
        import av, fractions
        from fast_video import FastH264Encoder
        encoder=FastH264Encoder();decoder=av.CodecContext.create('h264','r')
        for i in range(4):
            frame=av.VideoFrame.from_ndarray(np.full((180,320,3),i*30,dtype=np.uint8),format='rgb24').reformat(format='yuv420p')
            frame.pts=i*3000;frame.time_base=fractions.Fraction(1,90000)
            nalus=list(encoder._encode_frame(frame, i==0))
            self.assertTrue(nalus)
            decoded=decoder.decode(av.Packet(b''.join(b'\x00\x00\x00\x01'+n for n in nalus)))
            self.assertEqual(len(decoded),1)
            self.assertEqual(decoded[0].width,320)

class DesktopControlTests(unittest.TestCase):
    def test_pointer_scroll_fullscreen_validation(self):
        events=[];control=Controller(lambda *x:events.append(x))
        for payload in [{'type':'pointer','x':float('nan'),'y':0},{'type':'pointer','x':2,'y':0},{'type':'scroll','steps':999},{'type':'scroll','steps':True}]:control.handle(payload)
        self.assertEqual(events,[])
        control.handle({'type':'pointer','x':.5,'y':.25})
        control.handle({'type':'scroll','steps':-3})
        control.handle({'type':'key','key':'f11','down':True});control.release()
        self.assertEqual(events,[('pointer',(.5,.25),False),('scroll',-3,False),('key','f11',True),('key','f11',False)])
