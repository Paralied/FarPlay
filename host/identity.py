"""Local identity, one-time invitations and pinned TLS. No cloud registration."""
import base64
import ctypes
import datetime
import hashlib
import json
import os
from pathlib import Path
import secrets
import ssl
import time
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def protect(raw, decrypt=False):
    if os.name != 'nt':
        return raw  # Tests/development: mode 0600 protects local files.
    class Blob(ctypes.Structure):
        _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    buffer = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.windll.crypt32
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    fn.restype = ctypes.c_int
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        ctypes.windll.kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        ctypes.windll.kernel32.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


class Identity:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.file = self.directory / 'identity.dat'
        if self.file.exists():
            self.data = json.loads(protect(self.file.read_bytes(), True))
        else:
            key = ec.generate_private_key(ec.SECP256R1())
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'FarPlay PC')])
            now = datetime.datetime.now(datetime.timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
                    .public_key(key.public_key()).serial_number(x509.random_serial_number())
                    .not_valid_before(now - datetime.timedelta(days=1))
                    .not_valid_after(now + datetime.timedelta(days=3650))
                    .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                    .sign(key, hashes.SHA256()))
            self.data = {
                'certificate': cert.public_bytes(serialization.Encoding.PEM).decode(),
                'key': key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()).decode(),
                'phones': {},
            }
            self.save()
        cert = x509.load_pem_x509_certificate(self.data['certificate'].encode())
        self.fingerprint = cert.fingerprint(hashes.SHA256()).hex()
        self.invite = None
        self.expires = 0

    def save(self):
        temp = self.file.with_suffix('.tmp')
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(protect(json.dumps(self.data).encode()))
        os.replace(temp, self.file)

    def tls_context(self):
        # Encrypt the temporary PEM too; load_cert_chain needs a filesystem path.
        password = secrets.token_urlsafe(32).encode()
        key = serialization.load_pem_private_key(self.data['key'].encode(), None)
        pem = self.directory / ('tls-' + secrets.token_hex(8) + '.pem')
        fd = os.open(pem, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, 'wb') as f:
                f.write(self.data['certificate'].encode())
                f.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.BestAvailableEncryption(password)))
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.minimum_version = ssl.TLSVersion.TLSv1_2
            context.load_cert_chain(pem, password=password)
            return context
        finally:
            pem.unlink(missing_ok=True)

    def invitation(self, endpoints, name):
        self.invite = secrets.token_urlsafe(32)
        self.expires = time.monotonic() + 300
        payload = {'v': 2, 'name': name[:60], 'urls': endpoints,
                   'pin': self.fingerprint, 'invite': self.invite}
        return 'farplay:' + base64.urlsafe_b64encode(json.dumps(payload, separators=(',', ':')).encode()).decode().rstrip('=')

    def pair(self, invite, name):
        if not isinstance(invite, str) or not self.invite or time.monotonic() > self.expires:
            return None
        if not secrets.compare_digest(invite, self.invite):
            return None
        if len(self.data['phones']) >= 16:
            raise ValueError('Remove paired phones on the PC first')
        token = secrets.token_urlsafe(32)
        self.data['phones'][hashlib.sha256(token.encode()).hexdigest()] = str(name)[:60]
        self.save()
        self.invite = None
        return token

    def authorized(self, token):
        return isinstance(token, str) and hashlib.sha256(token.encode()).hexdigest() in self.data['phones']

    def revoke(self):
        self.data['phones'] = {}
        self.invite = None
        self.save()
