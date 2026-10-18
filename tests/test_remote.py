import asyncio
import struct
import sys
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host'))
from natpmp import NatPmp
from router import Router, PORT
import window_mode

class RemoteTests(unittest.TestCase):
    def test_natpmp_wire_format_and_assigned_port(self):
        pmp=NatPmp('192.168.0.1')
        response=struct.pack('!BBHIHHI',0,130,0,1,PORT,48000,3600)
        with patch.object(pmp,'exchange',return_value=response) as exchange:
            self.assertEqual(pmp.map_tcp(PORT,PORT),(48000,3600))
            exchange.assert_called_once_with(struct.pack('!BBHHHI',0,2,0,PORT,PORT,3600),2,16)
        with patch.object(pmp,'exchange',return_value=struct.pack('!BBHIHHI',0,130,0,1,22,48000,3600)):
            with self.assertRaises(OSError):pmp.map_tcp(PORT,PORT)

    def test_invalid_response_rejected(self):
        sock=MagicMock();sock.__enter__.return_value=sock;sock.recv.return_value=b'\x01\x80'+b'\x00'*10
        with patch('natpmp.socket.socket',return_value=sock):
            with self.assertRaises(OSError):NatPmp('192.168.0.1').external_address()
        sock.connect.assert_called_once_with(('192.168.0.1',5351))

    def test_fallback_mapping_renewal_and_cleanup(self):
        upnp=MagicMock();upnp.discover.return_value=0
        pmp=MagicMock();pmp.external_address.return_value='8.8.4.4';pmp.map_tcp.return_value=(48000,120)
        with patch('router.miniupnpc.UPnP',return_value=upnp),patch('router.default_gateway',return_value='192.168.0.1'),patch('router.NatPmp',return_value=pmp):
            router=Router();self.assertIn('NAT-PMP',router.discover());self.assertEqual(router.external_port,48000);self.assertEqual(router.renew_after,60)
            self.assertTrue(router.renew());router.remove_udp();self.assertIsNotNone(router.pmp)
            router.remove();pmp.map_tcp.assert_called_with(PORT,48000,0)

    def test_shared_wan_does_not_claim_remote_ready(self):
        upnp=MagicMock();upnp.discover.return_value=1;upnp.lanaddr='192.168.0.13';upnp.externalipaddress.return_value='100.64.1.2'
        with patch('router.miniupnpc.UPnP',return_value=upnp),patch('router.default_gateway',return_value=None):
            router=Router();self.assertIn('CGNAT',router.discover());self.assertIsNone(router.public);upnp.addportmapping.assert_not_called()

    def test_f11_exits_owned_mode_once_and_leaves_normal_keys_alone(self):
        window_mode._saved.clear();window_mode._f11_down=False
        window_mode._saved[42]=object()
        def restore(hwnd):window_mode._saved.pop(hwnd);return True
        with patch.object(window_mode,'restore_game_window',side_effect=restore) as restore:
            self.assertTrue(window_mode.handle_f11(0x100,42))
            self.assertTrue(window_mode.handle_f11(0x100,42))
            self.assertTrue(window_mode.handle_f11(0x101,42))
            self.assertFalse(window_mode.handle_f11(0x100,42))
            restore.assert_called_once_with(42)
