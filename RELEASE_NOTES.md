## Media Vault 1.0.7

**Install or update:** Settings › About & Updates › Download & install (it installs inside Media Vault and reopens),
or download `MediaVault_v1.0.7_setup.exe` below.

**Windows SmartScreen:** this build is not code-signed yet, so Windows may say it "protected your PC".
Choose *More info* › *Run anyway*. The SHA-256 of the setup file is listed below.

### Fixed
- **Hover previews never showed.** The preview video was drawn inside the poster's hidden, rounded-corner layer,
  where its frames never reached the screen, and it only started once a file reported its length. It now has its own
  layer above the poster, starts as soon as the file opens, and jumps 20 % in once the length is known. If a file
  cannot be previewed, the reason is written to media_vault.log.
- **The dashboard stays where you are** when you change a filter, the sort, the search or the Box sets switch
  (it used to jump back to the top). Switching tabs or Grid / Shelf still starts at the top.

- **The box set carousel turns like a carousel.** Next / previous used to spin the box in place and swap it for the
  next film. Now the box in focus spins as it slides to the side and back, the next film slides forward into the
  middle, the one on the far side drifts back and fades, and a new one fades in behind on the other side. The same
  turn is used by the arrows, the keyboard and the films dropdown, for box sets and OVA box sets alike.

### New
- **Preview videos on hover** can be turned off in Settings › Appearance.
- **OVA box sets without Fetch missing:** the first start of 1.0.7 turns adult OVAs already in your AniList folders
  into box sets, one quick AniList check per series. They open in the same 3D carousel as box sets: the set's cover,
  then each episode as its own floating DVD case.

### Changed
- The release build uses the Node.js 24 versions of GitHub's checkout, setup-python and upload-artifact steps.
