import asyncio
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox
from urllib.parse import urlsplit
import aiohttp
from aiortc import RTCPeerConnection, RTCConfiguration, RTCIceServer, RTCSessionDescription
from control import Controller
from media import DesktopAudio, DesktopVideo

VERSION = '0.1.0-prototype'
DATA = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'FarPlay'
DATA.mkdir(parents=True, exist_ok=True)
handler = RotatingFileHandler(DATA / 'host.log', maxBytes=2_000_000, backupCount=2)
logging.basicConfig(handlers=[handler], level=logging.INFO, format=f'%(asctime)s FarPlay {VERSION} %(levelname)s %(message)s')

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

    async def run(self):
        socket_url = 'wss://' + urlsplit(self.url).netloc + '/ws'
        async def watchdog():
            while not self.quit:
                self.controls.watchdog()
                await asyncio.sleep(0.25)
        watch = asyncio.create_task(watchdog())
        try:
            async with aiohttp.ClientSession() as session:
                while not self.quit:
                    try:
                        self.report('Connecting to your service…')
                        async with session.ws_connect(socket_url, heartbeat=15, max_msg_size=65536) as ws:
                            await ws.send_json({'role': 'host', 'token': self.token})
                            ice = []
                            while not self.quit:
                                try:
                                    msg = await asyncio.wait_for(ws.receive(), 1)
                                except TimeoutError:
                                    continue
                                if msg.type != aiohttp.WSMsgType.TEXT:
                                    break
                                data = json.loads(msg.data)
                                if data['type'] == 'ready':
                                    ice = data['iceServers']
                                    self.report('Ready — leave this app open and PC awake')
                                elif data['type'] == 'offer':
                                    self.report('Phone connecting…')
                                    await self.offer(data, ws, data.get('iceServers', ice))
                                elif data['type'] in ('stop', 'peer-offline'):
                                    await self.disconnect()
                                    self.report('Ready — phone disconnected')
                    except Exception as exc:
                        logging.exception('Connection error')
                        self.report('Connection error: ' + str(exc))
                    finally:
                        await self.disconnect()
                    for _ in range(20):
                        if self.quit:
                            break
                        await asyncio.sleep(0.25)
        finally:
            watch.cancel()
            await self.disconnect()

class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title('FarPlay · PC Host')
        self.root.geometry('610x440')
        self.root.configure(bg='#0b101b')
        self.messages = queue.Queue()
        self.worker = None
        self.host = None
        self.loop = None
        self.task = None
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#0b101b')
        style.configure('TLabel', background='#0b101b', foreground='#eaf0ff', font=('Segoe UI', 11))
        style.configure('TButton', padding=12, font=('Segoe UI', 11))
        frame = ttk.Frame(self.root, padding=28)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='FarPlay', font=('Segoe UI', 28, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='Your PC. Wherever you are.').pack(anchor='w', pady=(0, 22))
        ttk.Label(frame, text='Your service HTTPS address').pack(anchor='w')
        self.url = ttk.Entry(frame, font=('Segoe UI', 12))
        self.url.pack(fill='x', pady=(5, 14))
        config = DATA / 'settings.json'
        if config.exists():
            try:
                self.url.insert(0, json.loads(config.read_text()).get('url', ''))
            except ValueError:
                pass
        ttk.Label(frame, text='Host key (from service setup)').pack(anchor='w')
        self.token = ttk.Entry(frame, show='●', font=('Segoe UI', 12))
        self.token.pack(fill='x', pady=(5, 18))
        self.button = ttk.Button(frame, text='Start host', command=self.toggle)
        self.button.pack(fill='x')
        self.status = ttk.Label(frame, text='Stopped · No device has access', wraplength=540)
        self.status.pack(anchor='w', pady=18)
        ttk.Label(frame, text=f'{VERSION} · Primary monitor · 30 FPS', font=('Segoe UI', 9)).pack(anchor='w')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(100, self.poll)

    def report(self, text):
        self.messages.put(text)
        logging.info(text)

    def toggle(self):
        if self.worker and self.worker.is_alive():
            self.stop()
            return
        url, token = self.url.get().strip().rstrip('/'), self.token.get().strip()
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.netloc or parsed.path or len(token) < 32:
            messagebox.showerror('Setup needed', 'Enter your HTTPS service origin and host key (32+ characters).')
            return
        (DATA / 'settings.json').write_text(json.dumps({'url': url}))
        self.button.configure(text='Stop host')
        self.url.configure(state='disabled')
        self.token.configure(state='disabled')
        def run():
            async def launch():
                self.loop = asyncio.get_running_loop()
                self.task = asyncio.current_task()
                self.host = Host(url, token, self.report)
                await self.host.run()
            try:
                asyncio.run(launch())
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logging.exception('Host failure')
                self.report('Host failed: ' + str(exc))
            finally:
                self.loop = None
                self.host = None
                self.messages.put('__stopped__')
        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def stop(self):
        if self.host:
            self.host.quit = True
        if self.loop and self.task:
            self.loop.call_soon_threadsafe(self.task.cancel)
        self.button.configure(state='disabled')

    def close(self):
        if self.worker and self.worker.is_alive():
            self.stop()
            self.root.after(150, self.close)
        else:
            self.root.destroy()

    def poll(self):
        while not self.messages.empty():
            text = self.messages.get_nowait()
            if text == '__stopped__':
                self.button.configure(text='Start host', state='normal')
                self.url.configure(state='normal')
                self.token.configure(state='normal')
                self.status.configure(text='Stopped · No device has access')
            else:
                self.status.configure(text=text)
        self.root.after(100, self.poll)

if __name__ == '__main__':
    import sys
    if '--self-test' in sys.argv:
        import soundcard
        import windows_input
        app = App()
        app.root.update()
        app.root.destroy()
        logging.info('Packaged host startup self-test passed')
    else:
        App().root.mainloop()
