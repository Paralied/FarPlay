import asyncio
import base64
import ctypes
import ipaddress
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import platform
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import qrcode
from PIL import ImageTk
from aiohttp import web
from direct_server import DirectServer
from identity import Identity
from router import Router, PORT

VERSION = '0.2.0-direct'
DATA = Path(os.environ.get('LOCALAPPDATA', Path.home())) / 'FarPlay'
DATA.mkdir(parents=True, exist_ok=True)
logging.basicConfig(handlers=[RotatingFileHandler(DATA / 'host.log', maxBytes=2_000_000, backupCount=2)],
                    level=logging.INFO, format=f'%(asctime)s FarPlay {VERSION} %(levelname)s %(message)s')


class App:
    def __init__(self, autostart=True):
        self.root = tk.Tk()
        self.root.title('FarPlay · Your PC is the host')
        self.root.geometry('700x550')
        self.root.minsize(650, 520)
        self.root.configure(bg='#0b101b')
        self.messages = queue.Queue()
        self.identity = Identity(DATA)
        self.router = Router()
        self.server = self.loop = self.task = self.worker = None
        self.ready = False
        self.manual = ''
        try:
            self.manual = json.loads((DATA / 'direct-settings.json').read_text()).get('public', '')
        except (OSError, ValueError):
            pass
        style = ttk.Style()
        style.theme_use('clam')
        style.configure('TFrame', background='#0b101b')
        style.configure('TLabel', background='#0b101b', foreground='#eaf0ff', font=('Segoe UI', 11))
        style.configure('TButton', padding=10, font=('Segoe UI', 11))
        frame = ttk.Frame(self.root, padding=28)
        frame.pack(fill='both', expand=True)
        ttk.Label(frame, text='FarPlay', font=('Segoe UI', 28, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='This PC is your server. Leave this window open.').pack(anchor='w', pady=(5, 20))
        self.status = ttk.Label(frame, text='Starting your PC host…', wraplength=620, font=('Segoe UI', 13, 'bold'))
        self.status.pack(anchor='w', pady=10)
        self.network = ttk.Label(frame, text='Checking your router…', wraplength=620)
        self.network.pack(anchor='w', pady=(0, 20))
        self.pair_button = ttk.Button(frame, text='Pair my phone', command=self.pair, state='disabled')
        self.pair_button.pack(fill='x', pady=5)
        self.stop_button = ttk.Button(frame, text='Stop hosting', command=self.toggle)
        self.stop_button.pack(fill='x', pady=5)
        row = ttk.Frame(frame)
        row.pack(fill='x', pady=10)
        ttk.Button(row, text='Network setup', command=self.network_setup).pack(side='left')
        ttk.Button(row, text='Forget all phones', command=self.revoke).pack(side='right')
        ttk.Label(frame, text='First time: scan the pairing code in the phone app.\nAfter pairing: open the phone app and tap Connect.', wraplength=620).pack(anchor='w', pady=12)
        ttk.Label(frame, text=f'{VERSION} · Direct connection · No hosted service', font=('Segoe UI', 9)).pack(anchor='w')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(100, self.poll)
        if autostart:
            self.root.after(400, self.start)

    def report(self, text):
        self.messages.put(('status', text))
        logging.info(text)

    def endpoints(self):
        urls = [f'https://{self.router.lan}:{PORT}']
        public = self.manual or self.router.public
        if public:
            urls.append(f'https://{public}:{PORT}')
        return urls

    def start(self):
        if self.worker and self.worker.is_alive():
            return
        self.stop_button.configure(text='Stop hosting', state='normal')
        self.report('Starting your PC host…')
        def work():
            async def launch():
                self.loop = asyncio.get_running_loop()
                self.task = asyncio.current_task()
                self.server = DirectServer(self.identity, self.router, self.report)
                runner = web.AppRunner(self.server.app, access_log=None)
                try:
                    await runner.setup()
                    await web.TCPSite(runner, '0.0.0.0', PORT, ssl_context=self.identity.tls_context()).start()
                    self.report('Ready · waiting for your phone')
                    try:
                        notice = await asyncio.to_thread(self.router.discover)
                    except Exception:
                        logging.exception('Automatic router configuration failed')
                        notice = 'Home Wi-Fi ready. Automatic router setup unavailable. Open Network setup for remote access.'
                    self.messages.put(('network', notice))
                    self.messages.put(('ready', True))
                    while True:
                        await asyncio.sleep(1200)
                        old = self.router.public
                        try:
                            ok = await asyncio.to_thread(self.router.renew)
                            if old != self.router.public:
                                self.messages.put(('network', 'Your internet address changed. Pair the phone again to update its saved address.'))
                            elif not ok:
                                self.messages.put(('network', 'Router renewal failed. Home Wi-Fi remains available; check Network setup.'))
                        except Exception:
                            self.messages.put(('network', 'Router renewal failed. Check Network setup.'))
                finally:
                    await runner.cleanup()
                    await asyncio.to_thread(self.router.remove)
            try:
                asyncio.run(launch())
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logging.exception('Host stopped')
                self.report('Could not start hosting: ' + str(exc))
            finally:
                self.loop = self.server = self.task = None
                self.messages.put(('ready', False))
        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def toggle(self):
        if self.worker and self.worker.is_alive():
            self.stop()
        else:
            self.start()

    def stop(self):
        self.ready = False
        self.pair_button.configure(state='disabled')
        self.stop_button.configure(state='disabled')
        if self.loop and self.task:
            self.loop.call_soon_threadsafe(self.task.cancel)

    def pair(self):
        if not self.ready or not self.loop:
            return
        async def invite():
            return self.identity.invitation(self.endpoints(), platform.node() or 'My PC')
        future = asyncio.run_coroutine_threadsafe(invite(), self.loop)
        def show():
            if not future.done():
                self.root.after(50, show)
                return
            try:
                code = future.result()
            except Exception:
                messagebox.showerror('Pairing', 'Host stopped. Start it and try again.')
                return
            window = tk.Toplevel(self.root)
            window.title('Pair your phone')
            ttk.Label(window, text='On your phone: Pair PC → Scan QR code', padding=16).pack()
            qr = qrcode.QRCode(box_size=5, border=3)
            qr.add_data(code)
            qr.make(fit=True)
            image = ImageTk.PhotoImage(qr.make_image(fill_color='black', back_color='white').convert('RGB'))
            label = tk.Label(window, image=image)
            label.image = image
            label.pack(padx=20)
            ttk.Label(window, text='One use · Expires in 5 minutes · Keep this code private', padding=12).pack()
            def copy():
                window.clipboard_clear()
                window.clipboard_append(code)
            ttk.Button(window, text='Copy pairing code instead', command=copy).pack(pady=10)
            def expire():
                if window.winfo_exists():
                    label.configure(image='')
                    label.image = None
                    ttk.Label(window, text='Code expired. Close and generate a new one.').pack()
            window.after(300000, expire)
        show()

    def revoke(self):
        if not messagebox.askyesno('Forget phones', 'Disconnect and remove access for every paired phone?'):
            return
        if self.loop and self.server:
            async def remove():
                self.identity.revoke()
                await self.server.shutdown()
                self.report('All phones forgotten. Pair again to reconnect.')
            asyncio.run_coroutine_threadsafe(remove(), self.loop)
        else:
            self.identity.revoke()

    def network_setup(self):
        window = tk.Toplevel(self.root)
        window.title('FarPlay · Network setup')
        frame = ttk.Frame(window, padding=22)
        frame.pack()
        ttk.Label(frame, text=f'PC address: {self.router.lan}\nFarPlay port: {PORT} TCP', font=('Segoe UI', 12, 'bold')).pack(anchor='w')
        ttk.Label(frame, text='If automatic setup worked, test Connect with phone Wi-Fi off.\n\nIf it did not: forward TCP port 47990 on your router to this PC.\nThen enter your public IPv4 address below and pair your phone.\n\nIf your ISP shares your public address (CGNAT), forwarding alone\nwill not work. FarPlay cannot change an ISP network restriction.\n\nThe PC must be awake, unlocked, and running FarPlay.\nIf your public address changes, pair the phone again.', padding=(0, 16)).pack(anchor='w')
        ttk.Label(frame, text='Manual public IPv4 address (optional)').pack(anchor='w')
        field = ttk.Entry(frame, width=40)
        field.insert(0, self.manual)
        field.pack(fill='x', pady=8)
        def save():
            value = field.get().strip()
            try:
                if value and (not isinstance(ipaddress.ip_address(value), ipaddress.IPv4Address) or not ipaddress.ip_address(value).is_global):
                    raise ValueError()
            except ValueError:
                messagebox.showerror('Address', 'Enter a public IPv4 address, or leave this empty for automatic setup.')
                return
            self.manual = value
            (DATA / 'direct-settings.json').write_text(json.dumps({'public': value}))
            window.destroy()
        ttk.Button(frame, text='Save', command=save).pack(fill='x', pady=8)
        ttk.Button(frame, text='Allow FarPlay through Windows Firewall', command=self.firewall).pack(fill='x')

    def firewall(self):
        if os.name != 'nt' or not getattr(sys, 'frozen', False):
            messagebox.showinfo('Firewall', 'Use the packaged Windows EXE for this action.')
            return
        exe = sys.executable.replace("'", "''")
        script = (f"New-NetFirewallRule -DisplayName 'FarPlay Direct TCP' -Direction Inbound -Action Allow -Protocol TCP -LocalPort {PORT} -Program '{exe}' -Profile Any; "
                  f"New-NetFirewallRule -DisplayName 'FarPlay Direct Video' -Direction Inbound -Action Allow -Protocol UDP -Program '{exe}' -Profile Any")
        encoded = base64.b64encode(script.encode('utf-16le')).decode()
        result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', 'powershell.exe', '-NoProfile -EncodedCommand ' + encoded, None, 1)
        if result <= 32:
            messagebox.showerror('Firewall', 'Windows did not allow the firewall setup. You can add FarPlay in Windows Firewall settings.')

    def close(self):
        if self.worker and self.worker.is_alive():
            self.stop()
            self.root.after(150, self.close)
        else:
            if os.name == 'nt':
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)
            self.root.destroy()

    def poll(self):
        while not self.messages.empty():
            kind, value = self.messages.get()
            if kind == 'ready':
                self.ready = value
                self.pair_button.configure(state='normal' if value else 'disabled')
                self.stop_button.configure(text='Stop hosting' if value else 'Start hosting', state='normal')
                if os.name == 'nt':
                    ctypes.windll.kernel32.SetThreadExecutionState(0x80000003 if value else 0x80000000)
                if not value:
                    self.network.configure(text='Hosting is off. Phones cannot connect.')
            elif kind == 'network':
                self.network.configure(text=value)
            else:
                self.status.configure(text=value)
        self.root.after(100, self.poll)


if __name__ == '__main__':
    if '--self-test' in sys.argv:
        import soundcard
        import windows_input
        app = App(autostart=False)
        app.identity.tls_context()
        app.root.update()
        app.root.destroy()
        logging.info('Packaged direct host startup self-test passed')
    else:
        App().root.mainloop()
