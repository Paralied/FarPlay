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
            style,placement=_saved.pop(hwnd)
            u.SetWindowLongW(hwnd,-16,style)
            u.SetWindowPlacement(hwnd,ctypes.byref(placement))
            u.SetWindowPos(hwnd,None,0,0,0,0,0x0020|0x0001|0x0002|0x0004)
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
