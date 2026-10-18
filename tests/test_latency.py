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

class DesktopControlTests(unittest.TestCase):
    def test_pointer_scroll_fullscreen_validation(self):
        events=[];control=Controller(lambda *x:events.append(x))
        for payload in [{'type':'pointer','x':float('nan'),'y':0},{'type':'pointer','x':2,'y':0},{'type':'scroll','steps':999},{'type':'scroll','steps':True}]:control.handle(payload)
        self.assertEqual(events,[])
        control.handle({'type':'pointer','x':.5,'y':.25})
        control.handle({'type':'scroll','steps':-3})
        control.handle({'type':'key','key':'f11','down':True});control.release()
        self.assertEqual(events,[('pointer',(.5,.25),False),('scroll',-3,False),('key','f11',True),('key','f11',False)])
