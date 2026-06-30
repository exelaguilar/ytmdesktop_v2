# Home Assistant - YTMDesktop v2 Media Player

This custom component provides a Home Assistant `media_player` entity for controlling and displaying the status of the YouTube Music Desktop App through the YTMDesktop Companion Server API.

## Features

- Real-time status updates through Socket.IO.
- Smooth local progress updates for the Home Assistant media position bar.
- Standard media controls: play, pause, next, previous, stop, seek, volume, mute, shuffle, and repeat.
- Media metadata including title, artist, album, thumbnail, like status, shuffle state, repeat mode, and current video ID.
- Automatic reconnect attempts when the Companion Server or network connection becomes temporarily unavailable.
- Home Assistant reauthorization flow when the stored Companion Server token is rejected.

## Installation

### HACS

1. In Home Assistant, go to **HACS** > **Integrations**.
2. Open the three-dot menu in the top right and choose **Custom repositories**.
3. Add this repository URL:

   `https://github.com/exelaguilar/ytmdesktop_v2`

4. Select **Integration** as the category.
5. Search for **YTMDesktop** in HACS and download it.
6. Restart Home Assistant.

### Manual Installation

1. Copy the `custom_components/ytmd_v2/` folder from this repository into your Home Assistant `custom_components/ytmd_v2/` directory.
2. Restart Home Assistant.

## YTMDesktop Companion Server Setup

Before adding the integration in Home Assistant, enable the Companion Server in YouTube Music Desktop:

1. Open the YouTube Music Desktop App.
2. Go to **Settings**.
3. Open the **Integrations** tab.
4. Enable the Companion Server options:
   - Companion server, usually on port `9863`.
   - Companion authorization.
   - Browser communication.

## Home Assistant Setup

1. In Home Assistant, go to **Settings** > **Devices & services**.
2. Click **Add integration**.
3. Search for **YTMDesktop (v2) Remote**.
4. Enter the Companion Server host and port.
5. Home Assistant will request an authorization code from YTMDesktop.
6. Confirm that the code shown in Home Assistant matches the approval code shown in YTMDesktop.
7. Approve the request in YTMDesktop.
8. Check **I have approved the code in YTMDesktop** in Home Assistant and submit.

After approval, Home Assistant stores the Companion Server token and creates the media player entity.

## Reauthorization

If YTMDesktop rejects the stored token, Home Assistant will mark the integration as needing reauthorization. Start the repair flow from **Settings** > **Repairs** or from the integration entry, then approve the new code in YTMDesktop.

Reauthorization updates the existing integration entry. It does not create a second media player.

## Connection Recovery

The integration automatically retries the Socket.IO connection with exponential backoff after disconnects. This helps recover from temporary network drops, app restarts, or a sleeping computer waking back up.

If the entity remains unavailable after YTMDesktop is running again, reload the integration entry from **Settings** > **Devices & services**. That forces a full reconnect.

## Notes

- The Companion Server must remain enabled in YTMDesktop.
- The configured host and port must be reachable from Home Assistant.
- This integration uses local network communication only.

## License

This project is licensed under the MIT License.
