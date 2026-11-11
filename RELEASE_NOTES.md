## Media Vault 1.0.3

**Install or update:** download `MediaVault_v1.0.3_setup.exe` below and run it (it updates in place).
Already on 1.0.x? Settings › Components › Check now › Download & install.

**Windows SmartScreen:** this build is not code-signed yet, so Windows may say it "protected your PC".
Choose *More info* › *Run anyway*. The SHA-256 of the setup file is listed below.

### New
- **Age ratings** (PG, PG-13, R, TV-MA, 18+…) are scraped from TMDB, OMDb and AniList, shown in View More and
  tagged automatically ("Rated R"). Fetch missing adds them to titles already in your library.
- **Original titles:** anime and non-English films show their original title in small under the English one, and
  it is searchable. Settings › Library › Titles chooses English, Romaji or Original everywhere.
- **Tag Manager** (Settings › Library): pick many titles and tag or untag them at once (Shift-click picks a run);
  rename, merge or delete tags; hide a tag from the All tab.
- **Tag rules:** "if *field* *test* *value*, tag with *tag*" — file name, folder, title, original title, genre,
  your tags, age rating, resolution, codec, audio, type, year, length or score; contains, is, starts / ends with,
  pattern, more / less than. Rules can be limited to one folder, switched off, and show how many titles they match.
- **Configure** on each folder opens its own window: name, All / Insights, scraping source and parts, Fetch missing,
  Re-tag, Remove.

### Changed
- Settings reorganised: one **Library** section for folders, titles, box sets and tags.
- The player follows the theme colours. Black Out uses the accent colour when it is on, and switching it briefly
  shows "On" or "Off" in place of its name.

### Fixed
- A layout loop in View More's title that could stop other parts of the window from laying out.
