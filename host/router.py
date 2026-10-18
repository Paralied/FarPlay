"""Best-effort router mappings. Never uses public discovery or relay servers."""
import ipaddress
import socket
import threading
import miniupnpc
import logging
from natpmp import NatPmp, default_gateway

PORT = 47990


def local_address():
    # UDP connect selects a route without sending data. RFC 2544 address is not contacted.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('198.18.0.1', 9))
            return sock.getsockname()[0]
    except OSError:
        return socket.gethostbyname(socket.gethostname())


class Router:
    def __init__(self):
        self.upnp = None
        self.lan = local_address()
        self.public = None
        self.mapped = set()
        self.pmp = None
        self.external_port = PORT
        self.gateway = None
        self.wan = None
        self.method = None
        self.notice = 'Remote setup has not been checked yet.'
        self.renew_after = 1200
        self.lock = threading.RLock()

    def discover(self):
        with self.lock:
            try:
                upnp = miniupnpc.UPnP()
                upnp.discoverdelay = 1500
                if upnp.discover():
                    upnp.selectigd()
                    self.upnp = upnp
                    self.lan = upnp.lanaddr
                    self.wan = upnp.externalipaddress()
                    if ipaddress.ip_address(self.wan).is_global:
                        self.public = self.wan
                        if self.add(PORT, 'TCP'):
                            if self.pmp:
                                try:self.pmp.map_tcp(PORT, self.external_port, 0)
                                except Exception:pass
                                self.pmp = None
                            self.method = 'UPnP'
                            self.renew_after = 1200
                            self.external_port = PORT
                            self.notice = 'Router mapping active (UPnP). Connect once on home Wi-Fi to sync the phone, then test on mobile data.'
                            return self.notice
            except Exception:
                logging.info('UPnP setup unavailable', exc_info=True)
            try:
                self.gateway = default_gateway()
                if self.gateway:
                    pmp = NatPmp(self.gateway)
                    self.wan = pmp.external_address()
                    if ipaddress.ip_address(self.wan).is_global:
                        self.public = self.wan
                        self.external_port, lease = pmp.map_tcp(PORT, self.external_port)
                        self.pmp, self.method = pmp, 'NAT-PMP'
                        self.renew_after = max(1, min(1200, lease//2))
                        self.notice = 'Router mapping active (NAT-PMP). Connect once on home Wi-Fi to sync the phone, then test on mobile data.'
                        return self.notice
            except Exception:
                logging.info('NAT-PMP setup unavailable', exc_info=True)
            if self.wan and not ipaddress.ip_address(self.wan).is_global:
                self.public = None
                self.notice = 'Router WAN is private/shared: double NAT or CGNAT. Ask your ISP for a public IPv4 address, or forward through the upstream router. A direct internet connection is not ready.'
            elif self.public:
                self.notice = 'Public address found, but automatic mapping failed. Enable UPnP/NAT-PMP in the router or forward TCP 47990 to this PC, then retry.'
            else:
                self.notice = 'Router did not provide a public address/mapping. Enable UPnP/NAT-PMP in router settings and retry. ISP restrictions are unknown until the router WAN address is available.'
            return self.notice

    def add(self, port, protocol):
        with self.lock:
            if not self.upnp:
                return False
            try:
                existing = self.upnp.getspecificportmapping(port, protocol)
                if existing and (existing[0] != self.lan or int(existing[1]) != port or not str(existing[2]).startswith('FarPlay')):
                    return False  # Do not overwrite another app's router rule.
                if self.upnp.addportmapping(port, protocol, self.lan, port, 'FarPlay direct', '', 3600):
                    self.mapped.add((port, protocol))
                    return True
            except Exception:
                pass
            return False

    def renew(self):
        with self.lock:
            if self.pmp:
                self.wan = self.pmp.external_address()
                self.public = self.wan if ipaddress.ip_address(self.wan).is_global else None
                self.external_port, lease = self.pmp.map_tcp(PORT, self.external_port)
                self.renew_after = max(1, min(1200, lease//2))
            if self.upnp and self.method != 'NAT-PMP':
                address = self.upnp.externalipaddress()
                self.public = address if ipaddress.ip_address(address).is_global else None
            return all([self.add(port, protocol) for port, protocol in list(self.mapped)])

    def remove_udp(self):
        self.remove('UDP')

    def remove(self, protocol=None):
        with self.lock:
            if self.pmp and protocol in (None, 'TCP'):
                try:
                    self.pmp.map_tcp(PORT, self.external_port, 0)
                except Exception:
                    logging.info('NAT-PMP lease will expire after stop')
                self.pmp = None
            for port, proto in list(self.mapped):
                if protocol and proto != protocol:
                    continue
                try:
                    entry = self.upnp.getspecificportmapping(port, proto)
                    if entry and entry[0] == self.lan and int(entry[1]) == port and str(entry[2]).startswith('FarPlay'):
                        self.upnp.deleteportmapping(port, proto)
                except Exception:
                    pass
                self.mapped.discard((port, proto))

    def public_candidates(self, sdp):
        if not self.public or not self.upnp:
            return sdp
        output = []
        for line in sdp.splitlines():
            output.append(line)
            parts = line.split()
            if (line.startswith('a=candidate:') and len(parts) >= 8 and parts[2].lower() == 'udp'
                    and parts[4] == self.lan and parts[7] == 'host'):
                port = int(parts[5])
                if self.add(port, 'UDP'):
                    output.append(f'a=candidate:fp{port} {parts[1]} UDP 1694498815 {self.public} {port} typ srflx raddr {self.lan} rport {port}')
        return '\r\n'.join(output) + '\r\n'
