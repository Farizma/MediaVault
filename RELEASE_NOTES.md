## Media Vault 1.0.5

**Install or update:** download `MediaVault_v1.0.5_setup.exe` below and run it.
Already on 1.0.x? Settings › About & Updates › Download & install. Updating *to* 1.0.5 still opens the setup
wizard once (that is how 1.0.4 and earlier update); from 1.0.5 on, updates happen inside Media Vault.

**Windows SmartScreen:** this build is not code-signed yet, so Windows may say it "protected your PC".
Choose *More info* › *Run anyway*. The SHA-256 of the setup file is listed below.

### Changed
- **Updates stay inside Media Vault.** Download & install no longer opens the setup wizard: Media Vault downloads
  the new version, closes, installs it in the same folder with no windows, and opens again. A copy installed for
  all users still shows Windows' own permission prompt once.

### New
- **Update all** in Settings › About & Updates updates the video engines, shader and packages, then Media Vault.
- **Update badge:** a count on the Settings button and next to About & Updates whenever something has an update
  (checked a minute after start, then weekly, and whenever you open About & Updates).
- **Roll back:** Media Vault can go back to the previous release (two clicks, same silent install). libmpv, libVLC
  and the shader keep the version they replaced; Roll back puts it back when Media Vault restarts, and rolling back
  again undoes it. Running from source, Python packages roll back with pip.

### Fixed
- After "Starting the installer… Media Vault will close", Media Vault stayed open (its close was scheduled from a
  background thread, where it never ran).
