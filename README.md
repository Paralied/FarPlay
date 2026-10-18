# FarPlay — Windows to Android game-streaming prototype

Version 0.1.0. Created for playing your own PC games from an Android phone on another internet connection. Working name; no branding decision is required yet.

**This deliverable is source code, not a tested EXE/APK release.** The Windows and Android builds still need to be run on their build platforms, and the connection service must be deployed. No server has been purchased, provisioned, or published. Do not leave home relying on this until the mobile-data test below passes.

## Included

- Windows host window with Start/Stop, reconnecting signaling connection, primary-monitor video and speaker loopback audio.
- Android app project hosting the phone interface in Android WebView.
- Browser phone interface with Minecraft WASD, swipe-to-look, attack/use, jump, sneak, sprint, inventory, chat, hotbar, Escape and typing.
- 540p / 720p / 1080p width presets for 16:9 displays, at a 30 FPS target. Other monitor aspect ratios are preserved.
- Authenticated single-PC/single-phone signaling, distinct random host/phone keys, TLS via Caddy, short-lived TURN credentials, UDP/TCP relay configuration.
- Input whitelist, held-key cleanup on disconnect, 2-second heartbeat watchdog, immediate host stop control.
- Windows build script and manually triggered GitHub Actions workflow for an EXE and a debug APK.

## What this first version does not yet include

Hardware GPU encoding, 60/120 FPS tuning, gamepad mapping, movable touch layouts, saved device identities, QR pairing, automatic updates, automatic game launching, tray support, wake-on-LAN, adaptive resolution, or multi-user accounts. The host uses software WebRTC encoding and desktop capture; it is a connectivity prototype, not a measured low-latency gaming release. Encoding/decoding hardware and network conditions determine actual performance.

Minecraft Java should be tested in borderless/windowed mode. If swipe look does not respond, try disabling Minecraft's Raw Input setting. Input injection cannot control elevated applications from a non-elevated host; keep both host and game non-elevated. PC must remain awake and unlocked. The stream captures the primary desktop, including anything visible on it, not only the game.

## 1. Deploy the connection service

Requires a Linux server with Docker Compose, a public IPv4 address and a DNS name pointing to it. Hosting and relay bandwidth are external costs; this project does not include a paid account or server.

From the project root on that server:

```sh
python3 deploy/configure.py play.YOUR-DOMAIN.com YOUR_PUBLIC_IPV4
cd deploy
docker compose up -d --build
```

The example uses the server's public IPv4; if the provider NATs the server, update `external-ip` in `turnserver.conf` to `PUBLIC_IPV4/PRIVATE_IPV4` as appropriate. Keep the server clock synchronized for expiring TURN credentials.

Open these server firewall ports:

| Port | Purpose |
|---|---|
| TCP 80 and 443 | HTTPS client/signaling and certificate issuance |
| UDP/TCP 3478 | STUN/TURN |
| UDP 49160–49260 | TURN media allocations |

Do not expose TCP 8080 publicly; Compose binds it to loopback. Do not use a conventional HTTP CDN proxy in front of TURN. No home router port forwarding is required by this design.

Read `deploy/PAIRING-KEYS.txt` privately. It contains the service URL and separate host/phone keys. Never commit this file, `.env`, or `turnserver.conf`. Generated values are excluded by `.gitignore`. The phone key is a bearer credential: anyone with it can control the PC whenever the host runs. The service operator is trusted because it serves the phone client and signaling. This is not a zero-trust end-to-end identity system.

TLS protects website/signaling; WebRTC encrypts the media and control transport even through TURN. This baseline TURN listener supports UDP/TCP 3478, not TURN-over-TLS 443. A workplace that blocks those transports may still prevent connections; mobile data is an alternative, not a guaranteed fix. A future deployment can add a dedicated TURN TLS endpoint.

If running multiple services on this server, resolve conflicts with ports 80/443/3478 first. Caddy and TURN use Linux host networking. Review and pin container versions/digests before production use.

## 2. Build the Windows host

Install Python 3.12 for Windows. Open PowerShell in the project root:

```powershell
./host/build.ps1
```

The output is `host/dist/FarPlayHost.exe`. Alternatively, run `host/main.py` using a virtual environment with `host/requirements.txt` installed. No administrator privileges should be necessary.

Launch the host, paste the service HTTPS address and **host key**, and click Start host. The service URL is saved; keys are intentionally not written to settings. Logs with the application version are at `%LOCALAPPDATA%\FarPlay\host.log`. Start Minecraft locally, keep the host running, and disable automatic PC sleep for the session.

## 3. Build the Android app

Open the `android` folder in Android Studio with JDK 17, Android SDK 35 and Gradle 8.9. Sync, then build a debug APK. Or, with Gradle installed:

```sh
gradle --no-daemon -p android assembleDebug
```

APK output: `android/app/build/outputs/apk/debug/app-debug.apk`. A Gradle wrapper binary is not included. The repository workflow installs Gradle itself. The debug APK is for personal testing, not Play Store release. Use a maintained Android System WebView. Minimum Android version is 8.0.

Launch FarPlay on the phone, enter the same service URL, then enter the **phone key**. Choose 720p to start and tap Connect & play. Rotate the phone into landscape, then use Full screen if supported. Enable sound if autoplay audio is blocked. The browser interface at the same HTTPS address can also be used while APK builds are being tested.

Keys remain only in the running phone page. Backgrounding the app intentionally ends the stream and releases controls. Reopen and connect again. Android's typing dialog sends text into the focused PC field; tap Chat first to open Minecraft chat, then Type, then Enter.

## GitHub builds

Place the contents of this project at the root of a private GitHub repository, then run **Actions → Build FarPlay prototypes → Run workflow**. Download both build artifacts after successful jobs. This workflow builds and uploads artifacts only; it does not publish releases or deploy the service. No repository has been created or modified by this deliverable.

## Verification performed here

- Python syntax and JavaScript syntax checks. Browser visual QA was attempted but could not run because the browser binary download failed; the phone layout has not been visually verified.
- 9 core tests: token rejection, role separation, duplicate-device protection, offer/answer routing, expiring relay credential signature, malformed auth, no key exposure in the page, input validation/clamping and stuck-key release.
- 1 real local WebRTC integration test: actual SDP negotiation, synthetic audio/video reception, a control packet received by a fake Windows input backend, and key release during disconnect. It uses only loopback addresses; it does not validate NAT traversal or hardware capture.

Run tests with Python dependencies installed:

```sh
python -m unittest discover -s tests -v
node --check web/client.js
```

Not verified here: Windows desktop/audio capture and SendInput on real hardware, packaged EXE launch, Android compilation/installation, public TURN deployment, mobile-network latency, sustained performance, or Minecraft compatibility. Dependency ranges are intentionally not described as a reproducible release lockfile.

## First real-device test

1. Connect on home Wi-Fi and confirm video, speaker audio, mouse look and WASD.
2. Hold W, disconnect the phone, and confirm W releases within two seconds.
3. Turn phone Wi-Fi off. Connect over mobile data while the PC stays on home internet.
4. Enable Force relay, reconnect, and verify audio/video and controls again. This specifically tests TURN, which a same-network test does not prove.
5. Play for 15 minutes, rotate/background/reopen the app, disconnect and restart the host. Record the host log and any error shown on the phone.
6. Only after these checks should you rely on it away from home.

To revoke access, stop the host. Rotate PHONE_TOKEN in `.env` and restart signaling to revoke a leaked phone key. Restarting signaling closes active sessions. TURN credentials already issued expire after one hour.

## Design references

- WebRTC connection setup: https://webrtc.org/getting-started/peer-connections
- aiortc API: https://aiortc.readthedocs.io/en/latest/api.html
- Android WebView: https://developer.android.com/develop/ui/views/layout/webapps/webview
- SoundCard loopback capture: https://soundcard.readthedocs.io/en/latest/
- Coturn configuration: https://github.com/coturn/coturn/blob/master/examples/etc/turnserver.conf
- Caddy HTTPS: https://caddyserver.com/docs/quick-starts/https
