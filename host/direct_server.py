"""Authenticated HTTPS/WebSocket server running only on the user's PC."""
import asyncio
import contextlib
import io
import json
import logging
import time
import numpy as np
from aiohttp import web, WSMsgType
from PIL import Image
from media import DesktopVideo, DesktopAudio
from streaming import Host


class DirectServer:
    def __init__(self, identity, router, report, host_factory=Host, video_factory=DesktopVideo, audio_factory=DesktopAudio, endpoint_provider=None):
        self.identity, self.router, self.report = identity, router, report
        self.host_factory, self.video_factory, self.audio_factory = host_factory, video_factory, audio_factory
        self.endpoint_provider = endpoint_provider or (lambda: [])
        self.ws = None
        self.attempts = []
        self.app = web.Application(client_max_size=65536)
        self.app.router.add_post('/pair', self.pair)
        self.app.router.add_get('/ws', self.stream)
        self.app.on_shutdown.append(self.shutdown)

    async def pair(self, request):
        now = time.monotonic()
        self.attempts = [t for t in self.attempts if now-t < 60]
        if len(self.attempts) >= 15:
            raise web.HTTPTooManyRequests(text='Too many attempts. Wait one minute.')
        self.attempts.append(now)
        try:
            data = await request.json()
            if not isinstance(data, dict):
                raise ValueError()
            token = self.identity.pair(data.get('invite'), data.get('name', 'Phone'))
        except (ValueError, TypeError):
            raise web.HTTPBadRequest(text='Invalid pairing request')
        if token is None:
            raise web.HTTPUnauthorized(text='Pairing code expired or already used. Generate a new one on the PC.')
        self.report('Phone paired. Keep FarPlay open to allow connections.')
        return web.json_response({'token': token}, headers={'Cache-Control': 'no-store'})

    async def shutdown(self, app=None):
        if self.ws is not None:
            await self.ws.close(code=1001)

    async def stream(self, request):
        token = request.headers.get('Authorization', '').removeprefix('Bearer ')
        if not self.identity.authorized(token):
            raise web.HTTPUnauthorized()
        if self.ws is not None:
            raise web.HTTPConflict(text='Another phone is already connected')
        ws = web.WebSocketResponse(heartbeat=10, max_msg_size=65536)
        # Reserve before awaiting the handshake: never let concurrent phones take over.
        self.ws = ws
        host = self.host_factory('', '', self.report)
        compat_tasks = []
        tracks = []
        watchdog = None
        # A bounded two-frame window overlaps delivery with capture without a backlog.
        frame_ack = asyncio.Queue(maxsize=2)
        frame_ack.put_nowait(True)
        frame_ack.put_nowait(True)
        last_ping = time.monotonic()
        mode = 'idle'
        last_urls = self.endpoint_provider()
        try:
            await ws.prepare(request)
            await ws.send_json({'type': 'ready', 'version': '0.2.4', 'iceServers': [], 'urls': self.endpoint_provider()})
            self.report('Phone connected securely')

            async def watch():
                while not ws.closed:
                    host.controls.watchdog()
                    if time.monotonic() - last_ping > 15:
                        await ws.close(code=1001, message=b'Phone heartbeat lost')
                        return
                    await asyncio.sleep(.25)
            watchdog = asyncio.create_task(watch())

            async def video_loop():
                track = self.video_factory(width=960, fps=30)
                tracks.append(track)
                while not ws.closed:
                    # Never more than two unacknowledged frames in transit.
                    await asyncio.wait_for(frame_ack.get(), 5)
                    frame = await track.recv()
                    def jpeg():
                        output = io.BytesIO()
                        Image.fromarray(frame.to_ndarray(format='rgb24')).save(output, format='JPEG', quality=60)
                        return b'\x01' + output.getvalue()
                    packet = await asyncio.to_thread(jpeg)
                    await asyncio.wait_for(ws.send_bytes(packet), 2)

            async def audio_loop():
                track = self.audio_factory(self.report)
                tracks.append(track)
                while not ws.closed:
                    frame = await track.recv()
                    pcm = (np.clip(frame.to_ndarray().T, -1, 1) * 32767).astype('<i2').tobytes()
                    await asyncio.wait_for(ws.send_bytes(b'\x02' + pcm), 2)

            async def guarded(coro):
                try:
                    await coro
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logging.exception('Compatibility stream stopped')
                    await ws.close(code=1011, message=b'Stream interrupted')

            class Answer:
                async def send_json(inner, data):
                    data['sdp'] = await asyncio.to_thread(self.router.public_candidates, data['sdp'])
                    await ws.send_json(data)

            started, count = time.monotonic(), 0
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    break
                now = time.monotonic()
                if now-started > 1:
                    started, count = now, 0
                count += 1
                if count > 300:
                    await ws.close(code=1008)
                    break
                try:
                    data = json.loads(msg.data)
                    if not isinstance(data, dict):
                        continue
                    kind = data.get('type')
                    if kind == 'ping':
                        last_ping = now
                        host.controls.handle({'type': 'ping'})
                        await ws.send_json({'type': 'pong', 'at': data.get('at')})
                        current_urls = self.endpoint_provider()
                        if current_urls != last_urls:
                            last_urls = current_urls
                            await ws.send_json({'type': 'endpoints', 'urls': current_urls})
                    elif kind == 'offer' and mode == 'idle':
                        if not isinstance(data.get('sdp'), str) or len(data['sdp']) > 60000:
                            raise ValueError('Invalid offer')
                        mode = 'rtc'
                        await host.offer(data, Answer(), [])
                    elif kind == 'compatibility' and mode != 'compatibility':
                        mode = 'compatibility'
                        await host.disconnect()
                        await asyncio.to_thread(self.router.remove_udp)
                        await ws.send_json({'type': 'compatibility'})
                        self.report('Streaming directly · compatibility mode')
                        compat_tasks = [asyncio.create_task(guarded(video_loop())), asyncio.create_task(guarded(audio_loop()))]
                    elif kind == 'frame-ack':
                        if not frame_ack.full():
                            frame_ack.put_nowait(True)
                    elif kind == 'input' and mode == 'compatibility':
                        host.controls.handle(data.get('payload'))
                    elif kind == 'stop':
                        break
                except (ValueError, TypeError, KeyError):
                    await ws.close(code=1008)
                    break
        except Exception:
            logging.exception('Direct stream error')
        finally:
            for task in compat_tasks + ([watchdog] if watchdog else []):
                task.cancel()
            await asyncio.gather(*compat_tasks, *([watchdog] if watchdog else []), return_exceptions=True)
            for track in tracks:
                track.stop()
            await host.disconnect()
            await asyncio.to_thread(self.router.remove_udp)
            with contextlib.suppress(Exception):
                await ws.close()
            if self.ws is ws:
                self.ws = None
            self.report('Ready · waiting for your phone')
        return ws
