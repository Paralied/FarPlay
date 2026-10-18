"""Best-effort router mappings. Never uses public discovery or relay servers."""
import ipaddress
import socket
import threading
import miniupnpc

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
        self.lock = threading.RLock()

    def discover(self):
        with self.lock:
            upnp = miniupnpc.UPnP()
            upnp.discoverdelay = 1200
            if not upnp.discover():
                return 'Home Wi-Fi ready. Router did not offer automatic setup. Open Network setup for remote access.'
            upnp.selectigd()
            self.upnp = upnp
            self.lan = upnp.lanaddr
            address = upnp.externalipaddress()
            if not ipaddress.ip_address(address).is_global:
                return 'Home Wi-Fi ready. Router has no public IPv4 address (double NAT or ISP sharing). Remote access needs a network change.'
            self.public = address
            if self.add(PORT, 'TCP'):
                return 'Router configured for remote access. Test from mobile data before leaving home.'
            return 'Home Wi-Fi ready. Automatic port setup failed. Open Network setup for the manual step.'

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
            if self.upnp:
                address = self.upnp.externalipaddress()
                self.public = address if ipaddress.ip_address(address).is_global else None
            return all([self.add(port, protocol) for port, protocol in list(self.mapped)])

    def remove_udp(self):
        self.remove('UDP')

    def remove(self, protocol=None):
        with self.lock:
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
