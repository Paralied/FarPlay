import asyncio, base64, json, sys, tempfile, time, types, unittest
from pathlib import Path
from unittest.mock import patch
import aiohttp
from aiohttp import WSMsgType, WSServerHandshakeError
from aiohttp.test_utils import TestClient, TestServer
from aiortc import AudioStreamTrack, VideoStreamTrack, RTCPeerConnection, RTCConfiguration, RTCSessionDescription
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'host'))
from identity import Identity
from direct_server import DirectServer
from router import Router

class IdentityTests(unittest.TestCase):
    def test_one_use_expiry_persistence_and_revocation(self):
        with tempfile.TemporaryDirectory() as root:
            owner=Identity(root)
            code=owner.invitation(['https://192.168.1.5:47990'],'PC')
            data=json.loads(base64.urlsafe_b64decode(code[8:]+'='*(-len(code[8:])%4)))
            self.assertEqual(data['pin'],owner.fingerprint)
            self.assertIsNone(owner.pair('bad','phone'))
            token=owner.pair(data['invite'],'phone')
            self.assertTrue(owner.authorized(token))
            self.assertIsNone(owner.pair(data['invite'],'phone'))
            loaded=Identity(root)
            self.assertTrue(loaded.authorized(token));self.assertEqual(loaded.fingerprint,owner.fingerprint)
            self.assertNotIn(token,str(loaded.data))
            loaded.invitation([],'PC');loaded.expires=time.monotonic()-1
            self.assertIsNone(loaded.pair(loaded.invite,'phone'))
            loaded.revoke();self.assertFalse(Identity(root).authorized(token))

    def test_mapping_does_not_overwrite_other_apps(self):
        class IGD:
            calls=[]
            def getspecificportmapping(self,p,proto):return ('192.168.1.9',p,'Other app',True,'',0)
            def addportmapping(self,*args):self.calls.append(args);return True
        router=Router();router.upnp=IGD();router.lan='192.168.1.5'
        self.assertFalse(router.add(47990,'TCP'));self.assertEqual(router.upnp.calls,[])

    def test_public_sdp_only_for_mapped_local_address(self):
        router=Router();router.lan='192.168.1.5';router.public='8.8.4.4';router.upnp=object()
        with patch.object(router,'add',return_value=True) as add:
            out=router.public_candidates('a=candidate:x 1 udp 123 192.168.1.5 50000 typ host\r\na=candidate:y 1 udp 123 10.0.0.9 50001 typ host\r\n')
            self.assertIn('8.8.4.4 50000 typ srflx',out);self.assertNotIn('8.8.4.4 50001',out)
            add.assert_called_once_with(50000,'UDP')

class NoRouter:
    def public_candidates(self,sdp):return sdp
    def remove_udp(self):pass

class DirectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory();self.identity=Identity(self.temp.name);self.events=[]
        self.patches=[patch.dict(sys.modules,{'windows_input':types.SimpleNamespace(backend=lambda *x:self.events.append(x))}),patch('aioice.ice.get_host_addresses',return_value=['127.0.0.1']),patch('streaming.DesktopVideo',lambda **kw:VideoStreamTrack()),patch('streaming.DesktopAudio',lambda report:AudioStreamTrack())]
        for p in self.patches:p.start()
        self.direct=DirectServer(self.identity,NoRouter(),lambda t:None,video_factory=lambda **kw:VideoStreamTrack(),audio_factory=lambda r:AudioStreamTrack())
        self.server=TestServer(self.direct.app);await self.server.start_server(ssl=self.identity.tls_context())
        self.client=TestClient(self.server);await self.client.start_server()
        self.pin=aiohttp.Fingerprint(bytes.fromhex(self.identity.fingerprint))
        self.identity.invitation([],'PC')
        response=await self.client.post('/pair',json={'invite':self.identity.invite,'name':'test'},ssl=self.pin)
        self.assertEqual(response.status,200);self.token=(await response.json())['token']
    async def asyncTearDown(self):
        await self.client.close()
        for p in self.patches:p.stop()
        self.temp.cleanup()
    async def connect(self):
        ws=await self.client.ws_connect('/ws',headers={'Authorization':'Bearer '+self.token},ssl=self.pin)
        self.assertEqual((await ws.receive_json())['type'],'ready');return ws
    async def test_wrong_certificate(self):
        with self.assertRaises(aiohttp.ServerFingerprintMismatch):await self.client.post('/pair',json={},ssl=aiohttp.Fingerprint(b'0'*32))
    async def test_auth_and_duplicate(self):
        response=await self.client.post('/pair',json={'invite':'bad'},ssl=self.pin);self.assertEqual(response.status,401)
        with self.assertRaises(WSServerHandshakeError) as wrong:await self.client.ws_connect('/ws',ssl=self.pin)
        self.assertEqual(wrong.exception.status,401)
        ws=await self.connect()
        with self.assertRaises(WSServerHandshakeError) as duplicate:await self.connect()
        self.assertEqual(duplicate.exception.status,409)
        await ws.send_json({'type':'ping','at':42});self.assertEqual((await ws.receive_json())['at'],42)
        await ws.close()
    async def test_tcp_video_audio_controls_release(self):
        ws=await self.connect();await ws.send_json({'type':'compatibility'})
        self.assertEqual((await ws.receive_json())['type'],'compatibility')
        await ws.send_json({'type':'input','payload':{'type':'key','key':'w','down':True}})
        kinds=set()
        for _ in range(30):
            msg=await asyncio.wait_for(ws.receive(),3)
            if msg.type==WSMsgType.BINARY:
                kinds.add(msg.data[0])
                if msg.data[0]==1:
                    self.assertEqual(msg.data[1:3],b'\xff\xd8');await ws.send_json({'type':'frame-ack'})
                if kinds=={1,2}:break
        self.assertEqual(kinds,{1,2})
        for _ in range(20):
            if ('key','w',True) in self.events:break
            await asyncio.sleep(.01)
        self.assertIn(('key','w',True),self.events)
        await ws.close()
        for _ in range(30):
            if ('key','w',False) in self.events:break
            await asyncio.sleep(.05)
        self.assertIn(('key','w',False),self.events)
    async def test_direct_rtc_signaling(self):
        await self.check_direct_rtc(60)
    async def test_direct_rtc_fast_h264(self):
        await self.check_direct_rtc(30)
    async def check_direct_rtc(self,fps):
        ws=await self.connect();pc=RTCPeerConnection(RTCConfiguration(iceServers=[]))
        pc.addTransceiver('video',direction='recvonly');pc.addTransceiver('audio',direction='recvonly')
        dc=pc.createDataChannel('controls');done=asyncio.Event();tasks=[];received=set()
        @pc.on('track')
        def track(t):
            async def read():
                await t.recv();received.add(t.kind)
                if received=={'video','audio'}:done.set()
            tasks.append(asyncio.create_task(read()))
        try:
            await pc.setLocalDescription(await pc.createOffer());await ws.send_json({'type':'offer','sdp':pc.localDescription.sdp,'width':1280,'fps':fps})
            answer=await ws.receive_json()
            import re
            payload=re.search(r'm=video[^\r\n]+',answer['sdp']).group().split()[3]
            self.assertIn('a=rtpmap:'+payload+(' H264/' if fps==30 else ' VP8/'),answer['sdp'])
            await pc.setRemoteDescription(RTCSessionDescription(sdp=answer['sdp'],type='answer'))
            await asyncio.wait_for(done.wait(),5);self.assertEqual(received,{'video','audio'})
        finally:
            await ws.close();await pc.close()
            for t in tasks:t.cancel()
            await asyncio.gather(*tasks,return_exceptions=True)
    async def test_revoke(self):
        self.identity.revoke()
        with self.assertRaises(WSServerHandshakeError) as result:await self.connect()
        self.assertEqual(result.exception.status,401)
