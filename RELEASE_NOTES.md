## Media Vault 1.0.4

**Install or update:** download `MediaVault_v1.0.4_setup.exe` below and run it (it updates in place).
Already on 1.0.x? Settings › About & Updates › Check now › Download & install.

**Windows SmartScreen:** this build is not code-signed yet, so Windows may say it "protected your PC".
Choose *More info* › *Run anyway*. The SHA-256 of the setup file is listed below.

### Fixed
- AniList found nothing for file names like "Title Episode 1", "Title - Episode 01 (Uncensored)", "Title OVA 1" or
  "Title 01" (common for adult and OVA releases). These are read as episodes now, and when AniList still finds
  nothing, Media Vault drops a trailing number or "OVA" and asks again. Adult titles are included.
- Folder names in Settings › Library no longer cut off early: the status chips moved under the name, beside the path.
- Settings section names sit level with their icons.

### Changed
- **Fix Scraped Data** (was Fix match) searches TMDB, AniList and OMDb at once; each result says where it is from,
  and one service being down does not hide the others. TMDB results include adult titles when you search by hand.
- Titles scraped from AniList show AniList's average score as a percentage (green / orange / red, as on AniList)
  instead of audience stars.
- Settings: Integrations is now **Integrations & APIs**, Components is **About & Updates**, Library health is
  **Library Status**.
