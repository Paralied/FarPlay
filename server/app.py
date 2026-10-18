"""Single-owner signaling server. Deploy behind HTTPS; never stores media."""
import asyncio
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from aiohttp import web, WSMsgType


def create_app(host_token=None, phone_token=None, turn_secret=None, turn_urls=None):
    host_token = host_token or os.environ.get('HOST_TOKEN', '')
    phone_token = phone_token or os.environ.get('PHONE_TOKEN', '')
    if min(len(host_token), len(phone_token)) < 32 or host_token == phone_token:
        raise ValueError('Set distinct HOST_TOKEN and PHONE_TOKEN values of at least 32 characters')
    turn_secret = turn_secret or os.environ.get('TURN_SECRET', '')
    turn_urls = turn_urls or os.environ.get('TURN_URLS', '')
    peers = {}
    app = web.Application(client_max_size=65536)

    def ice():
        import base64
        servers = []
        if turn_urls and turn_secret:
            username = f'{int(time.time()) + 3600}:farplay'
            credential = base64.b64encode(hmac.new(turn_secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
            servers.append({'urls': turn_urls.split(','), 'username': username, 'credential': credential})
        stun = os.environ.get('STUN_URL', '')
        if stun:
            servers.append({'urls': stun})
        return servers

    async def socket(request):
        ws = web.WebSocketResponse(heartbeat=15, max_msg_size=65536)
        await ws.prepare(request)
        role = None
        try:
            msg = await asyncio.wait_for(ws.receive(), 10)
            if msg.type != WSMsgType.TEXT:
                return ws
            auth = json.loads(msg.data)
            if not isinstance(auth, dict):
                await ws.close(code=1008)
                return ws
            role = auth.get('role')
            if not isinstance(role, str):
                role = None
                await ws.close(code=1008)
                return ws
            expected = {'host': host_token, 'phone': phone_token}.get(role)
            token = auth.get('token')
            if not expected or not isinstance(token, str) or not hmac.compare_digest(expected, token):
                await ws.close(code=1008, message=b'Authentication failed')
                return ws
            if role in peers:
                await ws.close(code=1008, message=b'Device already connected')
                return ws
            peers[role] = ws
            other = 'phone' if role == 'host' else 'host'
            await ws.send_json({'type': 'ready', 'iceServers': ice(), 'peerOnline': other in peers})
            if other in peers:
                await peers[other].send_json({'type': 'peer-online', 'iceServers': ice()})
            start, count = time.monotonic(), 0
            async for msg in ws:
                if msg.type != WSMsgType.TEXT:
                    break
                now = time.monotonic()
                if now - start > 10:
                    start, count = now, 0
                count += 1
                if count > 80:
                    await ws.close(code=1008, message=b'Rate limit')
                    break
                payload = json.loads(msg.data)
                allowed = {'offer', 'stop'} if role == 'phone' else {'answer', 'status'}
                if not isinstance(payload, dict) or payload.get('type') not in allowed:
                    continue
                if payload['type'] in {'offer', 'answer'} and (not isinstance(payload.get('sdp'), str) or len(payload['sdp']) > 60000):
                    continue
                if payload['type'] == 'offer':
                    payload['iceServers'] = ice()
                if other in peers:
                    await peers[other].send_json(payload)
        except (TimeoutError, ValueError, TypeError, ConnectionError):
            await ws.close(code=1008)
        finally:
            if peers.get(role) is ws:
                del peers[role]
                other = peers.get('phone' if role == 'host' else 'host')
                if other is not None and not other.closed:
                    await other.send_json({'type': 'peer-offline'})
        return ws

    async def cleanup(app):
        for peer in list(peers.values()):
            await peer.close(code=1001)
    app.on_shutdown.append(cleanup)
    app.router.add_get('/ws', socket)
    root = Path(__file__).resolve().parents[1] / 'web'
    async def index(request):
        return web.FileResponse(root / 'index.html', headers={'Cache-Control': 'no-store'})
    app.router.add_get('/', index)
    app.router.add_static('/assets/', root)
    return app

if __name__ == '__main__':
    web.run_app(create_app(), host='0.0.0.0', port=8080, access_log=None)
