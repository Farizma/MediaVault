## Media Vault 1.0.1

**Install or update:** download `MediaVault_v1.0.1_setup.exe` below and run it (it updates 1.0.0 in place, same folder).
Already on 1.0.0? Settings › Components › Check now › Download & install.

**Windows SmartScreen:** this build is not code-signed yet, so Windows may say it "protected your PC".
Choose *More info* › *Run anyway*. The SHA-256 of the setup file is listed below.

### Fixed
- View More would not open for a single film (clicking a poster or the ⓘ button did nothing), and films picked inside a
  box set showed no title or details. A name clash in the code broke every non-box-set View More; a new test now
  calls the real View More data for films, series and box sets.
- Setup: choosing a folder that needs administrator rights and answering "Continue as administrator" failed with
  "Administrator permission was not given". Setup now restarts through its own elevation (the normal UAC prompt).
- Scrolling the library with a mouse wheel was slow: each notch now moves further, with a short glide; touchpads
  follow your fingers. View More and Settings scroll the same way.
- Poster hover tilt stuttered when the pointer moved slowly; it now eases every frame.

### New
- **New app icon:** the shelf of spines inside a vault dial, on the taskbar, desktop shortcut, setup wizard and in the app.
- **Black Out** button in the player (and the B key): black out your other monitors while watching, or leave them
  on. Remembered between sessions.
- **Insights** opens in its own window instead of a panel above the catalog.
