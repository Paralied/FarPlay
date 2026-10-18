"""NAT-PMP to the local default router only (RFC 6886); no outside service."""
import ipaddress
import json
import os
import socket
import struct
import subprocess


def default_gateway():
    if os.name != 'nt':
        return None
    script = "Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' | Sort-Object RouteMetric | Select-Object -First 1 -ExpandProperty NextHop"
    result = subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],capture_output=True,text=True,timeout=12,creationflags=0x08000000)
    value = result.stdout.strip()
    try:
        address = ipaddress.IPv4Address(value)
        if address.is_private and not address.is_unspecified and not address.is_loopback:
            return str(address)
    except ValueError:
        pass
    return None

class NatPmp:
    def __init__(self, gateway):
        self.gateway = gateway

    def exchange(self, request, opcode, length):
        with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
            # Connected UDP validates the source router and source port.
            sock.connect((self.gateway,5351))
            for timeout in (.25,.5,1):
                sock.settimeout(timeout)
                sock.send(request)
                try:
                    response=sock.recv(64)
                except socket.timeout:
                    continue
                if len(response)!=length or response[0]!=0 or response[1]!=128+opcode:
                    raise OSError('Unexpected NAT-PMP response')
                if struct.unpack('!H',response[2:4])[0]!=0:
                    raise OSError('Router rejected NAT-PMP request')
                return response
        raise TimeoutError('Router did not answer NAT-PMP')

    def external_address(self):
        return str(ipaddress.IPv4Address(self.exchange(b'\x00\x00',0,12)[8:12]))

    def map_tcp(self, internal, external, lifetime=3600):
        packet=struct.pack('!BBHHHI',0,2,0,internal,external,lifetime)
        response=self.exchange(packet,2,16)
        inside,outside,lease=struct.unpack('!HHI',response[8:])
        if inside!=internal or (lifetime and (not outside or not lease)):
            raise OSError('Invalid NAT-PMP mapping response')
        return outside,lease
