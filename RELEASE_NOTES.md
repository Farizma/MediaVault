## Media Vault 1.0.8

**Install or update:** Settings › About & Updates › Download & install (it installs inside Media Vault and reopens),
or download `MediaVault_v1.0.8_setup.exe` below.

**Windows SmartScreen:** this build is not code-signed yet, so Windows may say it "protected your PC".
Choose *More info* › *Run anyway*. The SHA-256 of the setup file is listed below.

### New
- **Paste a link into Fix Scraped Data.** A TMDB page (film or series; an episode or season page counts as its
  series), an AniList page, a MyAnimeList page (found on AniList) or an IMDb page (through OMDb) brings up exactly
  that title as the only result. Pick it to re-scrape from it. A TMDB link decides film or series by itself.
- **Episode images in series Galleries.** A TMDB series' Gallery now has its episode stills (the "Episode Images"
  on TMDB) after its backdrops, from the first three seasons, up to 18 images. New series get them when scanned; for
  series already in your library, Fix Scraped Data (with the title or its TMDB link) refreshes the Gallery.

### Fixed
- **Front… always opens the crop editor** and changes only the front cover, whatever the shape of the picture. A wide
  picture picked as the Front used to be split like a whole sleeve. Splitting a sleeve into back, spine and front is
  only done by **Whole cover…** (and a picture that is not a whole sleeve opens in the crop editor as the front).
