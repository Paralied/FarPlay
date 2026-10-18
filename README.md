# FarPlay 0.2 — your PC is the host

Leave FarPlay open on your Windows PC, pair the Android phone once, then tap **Connect**. The PC runs the game and serves the connection itself. This version does not use the old hosted signaling service, TURN relay, VPN, paid hosting, or an internet discovery service.

Download the latest **0.2** EXE and APK from [Releases](https://github.com/Paralied/FarPlay/releases). These are personal-use test builds; Windows launch and automated transport checks do not establish real-device performance.

## First connection

1. Open `FarPlayHost.exe` on the PC. Hosting starts automatically.
2. If Windows asks, allow FarPlay through the firewall. The **Network setup** button also offers an explicit firewall setup action (Windows asks for administrator approval).
3. Open the new Android app. Use home Wi-Fi for the first pairing.
4. On the PC choose **Pair my phone**, then scan its QR code in the phone app. Pasting the complete pairing code is also supported.
5. Tap **Connect & play**. After pairing, the phone remembers your PC.
6. To check access from work, switch phone Wi-Fi off and try over mobile data before leaving home.

If Android refuses to install over an earlier test build, uninstall that build first. This removes its old pairing. CI debug builds are not yet distributed with a permanent production signing key.

## Network behavior

- The PC listens on **TCP 47990** for TLS-encrypted pairing, signaling, and compatibility streaming.
- FarPlay attempts a one-hour UPnP router mapping and renews it while running. It removes its own mappings when stopped normally. An expired lease also removes them after a crash.
- The app reads your public IPv4 address from your router; it does not contact a public IP lookup service.
- The first stream attempt is direct WebRTC, with no STUN/TURN servers configured. Where UPnP is available, the host maps the local UDP media ports and advertises the mapped candidates.
- If the WebRTC path does not connect, the phone automatically tries **direct TCP compatibility mode over the same PC connection**. This is not a cloud relay. It sends 960-pixel-wide JPEG frames (up to 20 FPS, limited by round-trip delay) and PCM speaker audio. It uses more bandwidth and can have more latency than WebRTC.
- If UPnP is unavailable, manually forward **TCP 47990** to the PC and enter the public IPv4 address in **Network setup**, then pair again. Compatibility mode works through that one forwarded port if the connection is reachable.
- A non-public router WAN address can indicate double NAT or CGNAT. FarPlay reports this rather than claiming that remote access is ready. A manually configured router/ISP change can still be necessary; the app cannot bypass CGNAT without an external route.
- This version supports IPv4 pairing. If your public address changes, the saved phone address needs updating by pairing again. There is no external dynamic-address directory.
- The PC app prevents automatic Windows sleep while hosting; the PC still needs to stay powered on, unlocked, online, and running the host. Closing or stopping the host disconnects phones.

## Controls and safety

Minecraft touch controls include WASD, mouse look, attack, use, jump, sneak, sprint, inventory, chat, hotbar, typing, and Escape. Try Minecraft in borderless/windowed mode; turn Raw Input off if swipe look is not recognized. Keep the game non-elevated.

Pairing QR codes carry a random one-use invitation, the PC's TLS certificate SHA-256 fingerprint, and the PC addresses. Codes expire after five minutes. Keep them private. The phone verifies that exact certificate, exchanges the invitation for a persistent random credential, and stores the credential using Android Keystore encryption. Windows protects the PC identity with DPAPI. Access tokens are stored hashed on the host, and are never placed in URLs. **Forget all phones** revokes access and disconnects the current session.

The Android WebView loads only bundled assets. Network requests go through a native client pinned to the paired PC; it never accepts arbitrary certificates. Only one phone streams at a time. Disconnects, app backgrounding, and stale heartbeats release held controls. The app captures your primary desktop and speaker audio, including anything visible or playing there.

## Build and verification

GitHub Actions builds both packages on pushes to `main` and publishes them on Releases only after successful build jobs. The Windows job runs the tests and a packaged startup check.

- Windows: Python 3.12, then run `host/build.ps1`.
- Android: JDK 17, Gradle 8.9, Android SDK 35; run `gradle --no-daemon -p android assembleDebug`.
- Tests: install `host/requirements.txt`, then `python -m unittest discover -s tests -v`.

The automated direct tests cover expiring/one-use pairing, persisted identity, revocation, incorrect TLS fingerprints, unauthorized and duplicate connections, synthetic WebRTC audio/video, direct TCP video/audio/control traffic, key release on disconnect, and safe UPnP candidate handling. Actual router mappings, the Android camera/WebView, Windows game capture, and mobile-data gameplay still require device testing.

`server/`, `deploy/`, `web/`, and `host/legacy_host.py` retain the old 0.1 prototype and regression tests. They are not used by the 0.2 EXE or APK and do not need deploying.
