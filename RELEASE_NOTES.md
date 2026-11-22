## Media Vault 1.4.2

**Install or update:** Settings › About & Updates › Download & install (it installs inside Media Vault and reopens),
or download `MediaVault_v1.4.2_setup.exe` below.

**Windows SmartScreen:** this build is not code-signed yet, so Windows may say it "protected your PC".
Choose *More info* › *Run anyway*. The SHA-256 of the setup file is listed below.

This release includes 1.4.0, 1.4.1 and 1.4.2.

### New
- **Watch away from home.** Settings › Streaming › Remote access lets your iPhone or another computer reach Media
  Vault through Tailscale, with a password, a link that stays the same, a QR code and a step-by-step guide. On an
  iPhone, *Add to Home Screen* makes it an app.
- **Videos convert as they stream.** Files a phone or browser cannot play (MKV, HEVC, surround Opus...) are converted
  on the fly to 1080p, 720p or 480p, on your graphics card when it can. Add ffmpeg in Settings › About & Updates ›
  Components. Converted pieces live in a temporary folder and are deleted on their own.
- **The phone pages, redone in Liquid Glass.** Frosted header, tabs and panels over the cover art.
  - Resume where you stopped, on the phone or on the PC: your place is saved as you watch, and a video counts as
    watched at 92 %, just like on the PC. Tabs that do not track watched videos stay that way.
  - Continue Watching row, search, series and box-set pages with every episode, and the next episode starts by itself.
  - Folder tabs such as Artists show a card per folder, with your folder pictures.
  - Subtitles: .srt and .vtt files next to the video, and text subtitles inside the file (with ffmpeg).
- **Liquid Glass player controls.** The title floats in a glass capsule, the control bar and volume are glass, and
  the volume that drops down from the top stretches like liquid as you change it. Prefer the old look? Settings ›
  Playback › *Liquid Glass player controls* switches back to Classic at once.
- **Pop-up windows grow with the window.** Settings, View More and the other sheets scale up, contents and all, on a
  big window or screen.

### Fixed
- The View More DVD carousel turns smoothly: the box leaving the middle no longer blinks.
- A converted stream survives a pause of up to 15 minutes, and leftovers from a crash are cleared at the next start.
