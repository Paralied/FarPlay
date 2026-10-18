import asyncio
import base64
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time
import unittest
from aiohttp import WSMsgType
from aiohttp.test_utils import TestClient, TestServer
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'host'))
from server.app import create_app
from control import Controller

class Controls(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.control = Controller(lambda *args: self.events.append(args))
    def test_invalid_input_does_not_execute(self):
        for message in [None, [], {'type':'key','key':'win','down':True}, {'type':'key','key':[], 'down':True}, {'type':'move','x':float('nan'),'y':2}, {'type':'text','text':'hello\n'}]:
            self.control.handle(message)
        self.assertEqual(self.events, [])
    def test_disconnect_and_watchdog_release(self):
        self.control.handle({'type':'key','key':'w','down':True})
        self.control.handle({'type':'key','key':'w','down':True})
        self.assertEqual(len(self.events), 1)
        self.control.last = time.monotonic() - 3
        self.control.watchdog()
        self.assertEqual(self.events[-1], ('key','w',False))
        self.assertFalse(self.control.held)
    def test_movement_clamped(self):
        self.control.handle({'type':'move','x':10000,'y':-10000})
        self.assertEqual(self.events[-1], ('move',(300,-300),False))

class Signaling(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.client = TestClient(TestServer(create_app('H'*40,'P'*40,'secret','turn:example.org:3478')))
        await self.client.start_server()
    async def asyncTearDown(self):
        await self.client.close()
    async def login(self, role, token):
        ws = await self.client.ws_connect('/ws')
        await ws.send_json({'role':role,'token':token})
        return ws
    async def test_reject_wrong_token(self):
        ws = await self.login('phone','bad')
        self.assertEqual((await ws.receive()).type, WSMsgType.CLOSE)
    async def test_wrong_role_cannot_impersonate(self):
        ws = await self.login('host','P'*40)
        self.assertEqual((await ws.receive()).type, WSMsgType.CLOSE)
    async def test_duplicate_does_not_evict_host(self):
        host = await self.login('host','H'*40)
        await host.receive_json()
        duplicate = await self.login('host','H'*40)
        self.assertEqual((await duplicate.receive()).type, WSMsgType.CLOSE)
        phone = await self.login('phone','P'*40)
        self.assertTrue((await phone.receive_json())['peerOnline'])
        self.assertEqual((await host.receive_json())['type'], 'peer-online')
    async def test_exchange_and_turn_auth(self):
        host = await self.login('host','H'*40)
        ready = await host.receive_json()
        turn = ready['iceServers'][0]
        expected = base64.b64encode(hmac.new(b'secret', turn['username'].encode(), hashlib.sha1).digest()).decode()
        self.assertEqual(turn['credential'], expected)
        phone = await self.login('phone','P'*40)
        await phone.receive_json(); await host.receive_json()
        await phone.send_json({'type':'offer','sdp':'test-offer'})
        self.assertEqual((await host.receive_json())['sdp'], 'test-offer')
        await host.send_json({'type':'answer','sdp':'test-answer'})
        self.assertEqual((await phone.receive_json())['sdp'], 'test-answer')
        await phone.close()
        self.assertEqual((await host.receive_json())['type'], 'peer-offline')
    async def test_page_available_without_exposing_key(self):
        response = await self.client.get('/')
        self.assertEqual(response.status, 200)
        self.assertNotIn('P'*40, await response.text())
    async def test_non_object_auth_rejected(self):
        ws = await self.client.ws_connect('/ws')
        await ws.send_json([])
        self.assertEqual((await ws.receive()).type, WSMsgType.CLOSE)

if __name__ == '__main__':
    unittest.main()
