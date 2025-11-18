# Home Assistant - YTMDesktop (v2) Integration

This repository provides a Home Assistant custom integration that connects to YTMDesktop v2's Companion Server API (API v1) and exposes a `media_player` entity.

## Installation (HACS)

1. Push this repository to GitHub.
2. Create a release tag (e.g., `v0.1.0`) — HACS requires at least one tag.
3. In Home Assistant -> HACS -> Integrations -> Custom repositories:
   - Add repository URL: `https://github.com/exelaguilar/ytmdesktop_v2`
   - Category: `Integration`
4. Install the integration via HACS and restart Home Assistant.

## Manual install (development)

1. Copy the `custom_components/ytmdesktop/` folder into your Home Assistant `custom_components/` directory.
2. Restart Home Assistant.
3. Settings -> Devices & Services -> Add Integration -> "YTMDesktop" and follow instructions.

## Usage

- During setup, the integration will request an authorization code.
- Accept the incoming request in the YTMDesktop app running on the target machine (or paste the code in the app's Companion settings).
- Complete the setup in Home Assistant to finalize token exchange.

## Notes

- Requires YTMDesktop Companion Server enabled (default port 9863).
- Integration uses Socket.IO for realtime updates; ensure network reachability if HA runs on a different machine.
- Seek units (seconds vs ms), token expiry, and rate-limit behavior should be tested with your YTMDesktop version.

## License

MIT
