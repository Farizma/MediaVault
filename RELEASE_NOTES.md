## Media Vault 1.0.2

**Install or update:** download `MediaVault_v1.0.2_setup.exe` below and run it (it updates in place).
Already on 1.0.x? Settings › Components › Check now › Download & install.

**Windows SmartScreen:** this build is not code-signed yet, so Windows may say it "protected your PC".
Choose *More info* › *Run anyway*. The SHA-256 of the setup file is listed below.

### Fixed
- The player window crashed while drawing (a black window that could not be moved or closed, most visibly in
  picture in picture, and the crash when a video was opened with "Open with" while Media Vault was running).
- Picture in picture: drag it anywhere, and it has Back, play/pause, back/forward 10 s and a button back to the full
  player. Media Vault minimises while it is up, and closing Media Vault closes the player too.
- Videos open in a window first (F, a double-click or the HUD button goes full screen), at the size you last used.
- The selected tab could show as an empty white pill on wide windows.

### New
- **Anime:** mark a folder as anime (when adding it, or in Settings › Folders) and Media Vault uses AniList
  (no key needed): titles, synopsis, genres, score, cover, banner, characters with their voice actors' photos.
  Understands "[Group] Show - 07" file names.
- **Crop editor** for your own box art and disc art: drag, zoom and turn the image to fit the box. The file
  dialog opens in the title's own folder.
- **Gallery:** wide stills per title, scraped (TMDB backdrops, AniList banners) or your own, shown in View More and
  behind the recommended carousel.
- **Automatic tags** from sub-folder names and file names: 4K / HDR / Dolby Vision, Remux / Blu-ray / Web, codec,
  audio (Atmos, DTS-HD…), editions (Director's Cut, Extended, IMAX…), 3D, decade, anime release group.
- **Hide folders and tags** from the All tab and from Insights.
- **Reorder tabs** by dragging them in the top bar, or in Settings › Folders.
- **Reorder View More** by dragging rows in Settings › Appearance › View More layout.
- **Box sets** on/off pill next to the filters.
- **Custom theme:** choose every colour (page, panels, cards, text, secondary text, accent, highlight, warning, danger).
- Search and Grid / Shelf sit on the same line as the sort and filters.
- The window remembers its size and place, fills wide screens, and keeps a minimum size; View More grows with it.
- View More: a bigger 3D box, scroll over it to zoom, and clearer labels.
- **Black Out** shows clearly when it is on.
