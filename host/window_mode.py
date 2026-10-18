"""Borderless Minecraft window toggle; leaves the display mode unchanged."""
import ctypes
from ctypes import wintypes

class Placement(ctypes.Structure):
    _fields_=[('length',wintypes.UINT),('flags',wintypes.UINT),('showCmd',wintypes.UINT),('min',wintypes.POINT),('max',wintypes.POINT),('normal',wintypes.RECT)]
class MonitorInfo(ctypes.Structure):
    _fields_=[('size',wintypes.DWORD),('monitor',wintypes.RECT),('work',wintypes.RECT),('flags',wintypes.DWORD)]

_saved={}
def toggle_game_window():
    u=ctypes.windll.user32
    u.GetForegroundWindow.restype=wintypes.HWND
    u.GetWindowTextW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
    u.GetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int]
    u.SetWindowLongW.argtypes=[wintypes.HWND,ctypes.c_int,wintypes.LONG]
    u.GetWindowPlacement.argtypes=[wintypes.HWND,ctypes.POINTER(Placement)]
    u.SetWindowPlacement.argtypes=[wintypes.HWND,ctypes.POINTER(Placement)]
    u.SetWindowPos.argtypes=[wintypes.HWND,wintypes.HWND,ctypes.c_int,ctypes.c_int,ctypes.c_int,ctypes.c_int,wintypes.UINT]
    u.MonitorFromWindow.argtypes=[wintypes.HWND,wintypes.DWORD];u.MonitorFromWindow.restype=wintypes.HANDLE
    u.GetMonitorInfoW.argtypes=[wintypes.HANDLE,ctypes.POINTER(MonitorInfo)]
    hwnd=u.GetForegroundWindow();title=ctypes.create_unicode_buffer(512);u.GetWindowTextW(hwnd,title,512)
    if 'minecraft' not in title.value.lower():
        return  # Never restyle unrelated desktop windows.
    awareness=u.SetThreadDpiAwarenessContext
    awareness.argtypes=[ctypes.c_void_p];awareness.restype=ctypes.c_void_p
    previous=awareness(ctypes.c_void_p(-4))
    try:
        if hwnd in _saved:
            restore_game_window(hwnd)
            return
        if not _ensure_f11_hook():
            return
        placement=Placement();placement.length=ctypes.sizeof(placement)
        info=MonitorInfo();info.size=ctypes.sizeof(info)
        if not u.GetWindowPlacement(hwnd,ctypes.byref(placement)) or not u.GetMonitorInfoW(u.MonitorFromWindow(hwnd,2),ctypes.byref(info)):
            return
        style=u.GetWindowLongW(hwnd,-16)
        _saved[hwnd]=(style,placement)
        # Remove caption/resizing border. Do not switch monitor resolution or exclusivity.
        u.SetWindowLongW(hwnd,-16,style & ~0x00CF0000)
        r=info.monitor
        u.SetWindowPos(hwnd,None,r.left,r.top,r.right-r.left,r.bottom-r.top,0x0020|0x0004|0x0040)
    finally:
        if previous:awareness(previous)

# F11 while FarPlay owns borderless mode means "return to windowed". Swallow
# that one key pair so Minecraft does not enter exclusive fullscreen afterward.
_hook_started = False
_hook_ready = None
_hook_ok = False
_hook_callback = None
_f11_down = False

def _ensure_f11_hook():
    global _hook_started, _hook_ready
    import threading
    if not _hook_started:
        _hook_started = True
        _hook_ready = threading.Event()
        threading.Thread(target=_keyboard_loop,daemon=True,name='FarPlayF11').start()
    _hook_ready.wait(1)
    return _hook_ok

def _keyboard_loop():
    global _hook_ok, _hook_callback
    import logging
    try:
        u=ctypes.windll.user32;k=ctypes.windll.kernel32
        k.GetModuleHandleW.argtypes=[wintypes.LPCWSTR];k.GetModuleHandleW.restype=wintypes.HMODULE
        callback_type=ctypes.WINFUNCTYPE(ctypes.c_ssize_t,ctypes.c_int,wintypes.WPARAM,wintypes.LPARAM)
        class Key(ctypes.Structure):
            _fields_=[('vk',wintypes.DWORD),('scan',wintypes.DWORD),('flags',wintypes.DWORD),('time',wintypes.DWORD),('extra',ctypes.c_size_t)]
        u.CallNextHookEx.argtypes=[wintypes.HANDLE,ctypes.c_int,wintypes.WPARAM,wintypes.LPARAM];u.CallNextHookEx.restype=ctypes.c_ssize_t
        u.SetWindowsHookExW.argtypes=[ctypes.c_int,callback_type,wintypes.HINSTANCE,wintypes.DWORD];u.SetWindowsHookExW.restype=wintypes.HANDLE
        u.GetForegroundWindow.restype=wintypes.HWND
        def callback(code,message,data):
            if code>=0 and ctypes.cast(data,ctypes.POINTER(Key)).contents.vk==0x7A:
                if handle_f11(message,u.GetForegroundWindow()):return 1
            return u.CallNextHookEx(None,code,message,data)
        _hook_callback=callback_type(callback)
        hook=u.SetWindowsHookExW(13,_hook_callback,k.GetModuleHandleW(None),0)
        _hook_ok=bool(hook);_hook_ready.set()
        if not hook:return
        msg=wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg),None,0,0)>0:
            u.TranslateMessage(ctypes.byref(msg));u.DispatchMessageW(ctypes.byref(msg))
    except Exception:
        logging.exception('Could not install Minecraft F11 exit handler')
        _hook_ready.set()

def restore_game_window(hwnd=None):
    u=ctypes.windll.user32
    u.GetForegroundWindow.restype=wintypes.HWND
    hwnd=hwnd or u.GetForegroundWindow()
    saved=_saved.pop(hwnd,None)
    if saved is None:return False
    title=ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd,title,512)
    if 'minecraft' not in title.value.lower():return False
    awareness=u.SetThreadDpiAwarenessContext
    awareness.argtypes=[ctypes.c_void_p];awareness.restype=ctypes.c_void_p
    previous=awareness(ctypes.c_void_p(-4))
    try:
        style,placement=saved
        u.SetWindowLongW(hwnd,-16,style)
        u.SetWindowPlacement(hwnd,ctypes.byref(placement))
        u.SetWindowPos(hwnd,None,0,0,0,0,0x0020|0x0001|0x0002|0x0004)
        return True
    finally:
        if previous:awareness(previous)

def handle_f11(message,hwnd):
    global _f11_down
    if message in (0x100,0x104):
        if _f11_down:return True
        if hwnd in _saved:
            _f11_down=True
            restore_game_window(hwnd)
            return True
    elif message in (0x101,0x105) and _f11_down:
        _f11_down=False
        return True
    return False

def restore_all():
    for hwnd in list(_saved):restore_game_window(hwnd)
