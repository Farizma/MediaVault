## Media Vault 1.0.6

**Install or update:** Settings › About & Updates › Download & install (it installs inside Media Vault and reopens),
or download `MediaVault_v1.0.6_setup.exe` below.

**Windows SmartScreen:** this build is not code-signed yet, so Windows may say it "protected your PC".
Choose *More info* › *Run anyway*. The SHA-256 of the setup file is listed below.

### New
- **Tag suggestions:** typing a tag (in View More or the Tag Manager) lists tags you have used before, most used
  first; Up / Down to pick, Enter or Tab to take one.
- **Adult OVAs as box sets:** an adult OVA from AniList is no longer a series with seasons. Each episode is its own
  film ("Title #1", "Title #2", in number order) inside one box set, so every episode keeps its own cover and disc
  art. Titles already in your library change over with Fix Scraped Data, or Fetch missing on the folder.
- **Whole cover scans:** "Whole cover…" under the 3D box takes one scan of the whole sleeve (back, spine and front
  side by side), finds the spine and wraps it round the box. A wide image chosen as the Front is handled the same way.
- **AniList genres and tags:** AniList gives adult titles a single genre ("Hentai"); what a title is about is in
  AniList's tags. The most relevant ones (no spoilers, up to 12) now come in as genres, the same blue tags films get
  from TMDB, so they filter, search and show in Insights like any genre.
- **Studio tags:** every title from AniList gets its studio(s) as an amber tag. They stay put (re-tagging and rules
  never remove them), can't be deleted by accident, and work in Tag Manager rules ("if Studio is ..., tag ...").
- **More Gallery images** for anime: MyAnimeList's pictures (through Jikan, an open-source MAL API) after the AniList banner.

### Changed
- The 3D box has the proportions of a real DVD case (135 × 190 mm), so covers and sleeve scans fit without cropping.

### Fixed
- **Closing the window left Media Vault running, hidden** (and logged a crash each time): the close handler could not
  receive Qt's close event. Media Vault now saves its size and place and quits properly. This was also why the old
  updater's "Media Vault will close" never happened.
- **Updating libmpv failed** with "Permission denied" while Media Vault had it loaded. The loaded file is now moved
  aside and replaced; libVLC, which used to be deleted half-way when in use, waits for the next start instead.
- AniList searches (automatic and Fix Scraped Data) retry with words only when punctuation in a file name
  ("Title-Name", "Title!") stopped a match, and join a split short name ("Drop Out" finds "Dropout").
- The hover preview on cards could not jump back to its start for its 15-second loop.
- Titles already in your library pick up the new genres, studios and OVA box sets with **Fetch missing** on the folder.
