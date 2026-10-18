"""Real WebRTC negotiation using synthetic media and a fake Windows input sink."""
import asyncio
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from aiortc import RTCPeerConnection, RTCConfiguration, RTCSessionDescription, VideoStreamTrack, AudioStreamTrack
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'host'))
os.environ['LOCALAPPDATA'] = tempfile.mkdtemp(prefix='farplay-test-')
events = []
sys.modules['windows_input'] = types.SimpleNamespace(backend=lambda *args: events.append(args))
import legacy_host as host_module

class Stream(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        # Local-only test: no host interface enumeration or external traffic.
        self.addresses = patch('aioice.ice.get_host_addresses', return_value=['127.0.0.1'])
        self.addresses.start()
    async def asyncTearDown(self):
        self.addresses.stop()
    async def test_host_offer_media_and_controls(self):
        host_module.DesktopVideo = lambda **kwargs: VideoStreamTrack()
        host_module.DesktopAudio = lambda report: AudioStreamTrack()
        host = host_module.Host('https://example.org', 'x'*40, lambda text: None)
        phone = RTCPeerConnection(RTCConfiguration(iceServers=[]))
        phone.addTransceiver('video', direction='recvonly')
        phone.addTransceiver('audio', direction='recvonly')
        control = phone.createDataChannel('controls')
        received = asyncio.Event()
        frames = []
        tasks = []
        @phone.on('track')
        def track(track):
            async def read():
                frame = await track.recv()
                frames.append(track.kind)
                if 'video' in frames and 'audio' in frames:
                    received.set()
            tasks.append(asyncio.create_task(read()))
        @control.on('open')
        def opened():
            control.send('{"type":"key","key":"w","down":true}')
        class WS:
            async def send_json(self, data):
                await phone.setRemoteDescription(RTCSessionDescription(sdp=data['sdp'], type='answer'))
        try:
            await phone.setLocalDescription(await phone.createOffer())
            await host.offer({'sdp':phone.localDescription.sdp,'width':1280}, WS(), [])
            await asyncio.wait_for(received.wait(), 15)
            for _ in range(30):
                if ('key','w',True) in events:
                    break
                await asyncio.sleep(.05)
            self.assertIn(('key','w',True), events)
            await host.disconnect()
            self.assertIn(('key','w',False), events)
            self.assertCountEqual(frames, ['audio','video'])
        finally:
            await host.disconnect()
            await phone.close()
            for task in tasks:
                task.cancel()

if __name__ == '__main__':
    unittest.main()
