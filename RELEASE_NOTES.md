## Media Vault 1.0.6

**Install or update:** Settings › About & Updates › Download & install (it installs inside Media Vault and reopens),
or download `MediaVault_v1.0.6_setup.exe` below.

**Windows SmartScreen:** this build is not code-signed yet, so Windows may say it "protected your PC".
Choose *More info* › *Run anyway*. The SHA-256 of the setup file is listed below.

### New
- **Alternate titles** under the title in View More, grouped **English**, **Romanized**, **Native**, then **Other
  languages** (folded away; click to show). From AniList's synonyms and TMDB's translations and alternative titles;
  every one is searchable. Titles already in your library get them with **Fetch missing**.
- **Discord status, your way:** write both status lines yourself with {title}, {year}, {episode} and {type}
  (with a live preview of a film and an episode), choose what the image tooltip says, and whether pausing shows
  "Paused" or clears the status.
- **Discord privacy:** adult titles (rated 18+ / R18+ / NC-17 / X, or a Hentai / Erotica genre) show only
  "Watching a video" (on by default); pick tags whose titles are never named; and set each folder to show its
  titles, only "Watching a video", or nothing at all (Library › Configure › Discord).
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

### Security
- **API keys are encrypted** with Windows' own Data Protection (DPAPI), tied to your Windows account on this PC.
  Keys saved by older versions are encrypted the first time 1.0.6 starts. A backup restored on another PC or
  account cannot read them: Settings asks for them again.
- **Watch on other devices (LAN streaming):** a title could carry script into the library page (an inline handler
  it could break out of); the page now has no script at all, under a strict Content-Security-Policy, plus
  nosniff / no-referrer / no-framing headers. The server answers only devices on your own network (private,
  link-local and loopback addresses), listens on this network's address instead of every interface, drops idle
  connections after 30 s, refuses anything but GET, and no longer names its Python version.
- **Updates are checked before they run:** Media Vault's installer must match the SHA-256 GitHub publishes for it
  (a mismatch is deleted, never started) and is saved in a private folder. The emergency 7-Zip unpacker is now a
  pinned release checked by hash before it runs, and the upscaling shader is checked by hash too.
- **Downloads are HTTPS only** (no file:// or plain http:// from scraped answers), size-capped, and pictures with
  absurd pixel counts ("decompression bombs") are refused.
- **Scraped text is only ever text:** markup in titles, synopses, cast and tags from TMDB, AniList or OMDb is
  dropped, so the app never renders it as rich text (which can load remote or local images). Result thumbnails
  must be HTTPS.
- A rollback can only hand pip a version number.

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
