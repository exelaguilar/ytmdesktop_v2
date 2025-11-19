# 🎵 Home Assistant - YTMDesktop (v2) Media Player

This custom component provides a Home Assistant `media_player` entity for controlling and displaying the status of **YouTube Music Desktop App (YTMDesktop)** via its Companion Server API.

## ✨ Features

* **Real-time Status:** Uses Socket.IO (WebSockets) for immediate state updates, volume, and playback status.
* **Smooth Progress:** Implements a local progress timer to ensure the media position bar updates smoothly in the Home Assistant UI, even between API state pushes.
* **Full Control:** Supports standard media commands including Play, Pause, Next/Previous Track, Stop, Volume Set, Mute, Seek, Shuffle, and Repeat mode.
* **Detailed Metadata:** Displays media title, artist, album, thumbnail, and like status.

---

## 🚀 Installation (Recommended: HACS)

The easiest way to install this integration is through the Home Assistant Community Store (HACS).

1.  **Add Custom Repository:**
    * In Home Assistant, navigate to **HACS** → **Integrations**.
    * Click the **three dots menu** (top right) → **Custom Repositories**.
    * Enter the URL of this repository: `https://github.com/exelaguilar/ytmdesktop_v2`
    * Select Category: `Integration`.
    * Click **Add**.
2.  **Install Integration:**
    * Search for "YTMDesktop" in HACS and click **Download**.
3.  **Restart Home Assistant** to load the new component files.

### Manual Installation (For Development/Testing)

1.  Copy all files from this repository's `custom_components/ytmd_v2/` folder into your Home Assistant's `custom_components/ytmd_v2/` directory.
2.  Restart Home Assistant.

---

## ⚙️ Configuration & Usage

### 1. YTMDesktop Server Setup (Crucial!)

Before starting the Home Assistant configuration flow, you must enable the Companion Server in the YTMDesktop application:

1.  Open the **YouTube Music Desktop App**.
2.  Go to **Settings** (gear icon in the top right).
3.  Navigate to the **Integrations** tab on the left menu.
4.  Ensure the following options under the **Companion Server** section are **enabled**:
    * **Companion server** (or similar, typically port `9863`).
    * **Enable companion authorization.**
    * **Allow browser communication.**

### 2. Home Assistant Integration

1.  In Home Assistant, navigate to **Settings** → **Devices & Services** → **Add Integration**.
2.  Search for **YTMDesktop (v2) Remote** and select it.
3.  **Enter Connection Details** (Host and Port).
4.  **Authorization Step:**
    * The integration will connect and request an authorization code, which triggers an approval popup in the YTMDesktop app.
    * **Verify** the code in Home Assistant matches the code shown in the YTMDesktop app, **Approve** the request in the YTMDesktop app, and then check the "Approved" box and click **Submit** in Home Assistant.
5.  Once approved, the final token will be exchanged, and the `media_player` entity will be created.

---

## ⚠️ Known Issues & Workarounds

### Connection Drop Bug (Manual Reload Required)

If the network connection between Home Assistant and the YTMDesktop Companion Server is interrupted (e.g., computer sleeps, network drops), the entity may fail to automatically reconnect, even if the companion server is running again.

**Workaround:**

If the media player entity becomes `unavailable` and does not automatically recover:

1.  Navigate to **Settings** → **Devices & Services**.
2.  Find the **YTMDesktop** integration entry.
3.  Click the **three dots menu** → **Reload**.

Reloading the integration entry will force a full re-initialization and reconnection.

---

## 📜 License

This project is licensed under the MIT License.