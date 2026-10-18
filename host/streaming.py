import asyncio
import json
import logging
from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer, RTCSessionDescription
from control import Controller
from media import DesktopAudio, DesktopVideo

class Host:
    def __init__(self, url, token, report):
        self.url, self.token, self.report = url, token, report
        self.pc = None
        self.tracks = []
        self.quit = False
        from windows_input import backend
        self.controls = Controller(backend)

    async def disconnect(self):
        self.controls.release()
        pc, self.pc = self.pc, None
        for track in self.tracks:
            track.stop()
        self.tracks.clear()
        if pc:
            await pc.close()

    async def offer(self, payload, ws, ice):
        await self.disconnect()
        width = payload.get('width', 1280)
        if width not in (960, 1280, 1920):
            width = 1280
        self.pc = pc = RTCPeerConnection(RTCConfiguration(iceServers=[RTCIceServer(**s) for s in ice]))
        @pc.on('datachannel')
        def on_channel(channel):
            if channel.label != 'controls':
                channel.close()
                return
            @channel.on('message')
            def on_message(raw):
                try:
                    if not isinstance(raw, str) or len(raw) > 4096:
                        return
                    payload = json.loads(raw)
                    self.controls.handle(payload)
                    if payload.get('type') == 'ping' and channel.readyState == 'open':
                        channel.send(json.dumps({'type': 'pong', 'at': payload.get('at')}))
                except Exception:
                    logging.exception('Input error')
            @channel.on('close')
            def closed():
                self.controls.release()
        @pc.on('connectionstatechange')
        async def state():
            self.report('Stream: ' + pc.connectionState)
            if pc.connectionState in ('failed', 'closed') and self.pc is pc:
                await self.disconnect()
        self.tracks = [DesktopVideo(width=width), DesktopAudio(self.report)]
        try:
            await pc.setRemoteDescription(RTCSessionDescription(sdp=payload['sdp'], type='offer'))
            for track in self.tracks:
                pc.addTrack(track)
            await pc.setLocalDescription(await pc.createAnswer())
            await ws.send_json({'type': 'answer', 'sdp': pc.localDescription.sdp})
        except Exception:
            await self.disconnect()
            raise

