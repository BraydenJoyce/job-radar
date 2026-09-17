# Third-party assets

## adzuna_logo.png

The Adzuna logo is a trademark of Adzuna Ltd and is **not** covered by this
project's MIT license. It is included here solely to satisfy the attribution
requirement in Adzuna's API terms, which ask API users to display the Adzuna
logo image, at least 116 x 23 pixels, wherever Adzuna listings are shown.

Source: the official press kit at <https://www.adzuna.co.uk/press.html>,
downloaded as `adzuna_logo.jpg` (4000 x 1025, 341 KB, 300 dpi) and resized to
232 x 59 PNG with no other alteration.

Why a local copy rather than hotlinking Adzuna's own CDN:

- Their CDN serves the logo as SVG, and Slack's image blocks do not render SVG.
  The payload is accepted with a 200 and the image silently breaks.
- The press kit JPG is a 300 dpi print asset at 4000 pixels wide. Slack renders
  an image block at the source's natural size, so it fills the whole message.
- Their CDN has no on-the-fly resizing, and hosts no smaller raster version.

If Adzuna would prefer this not be redistributed, replace `ADZUNA_LOGO_URL` in
`config.py` with a URL they host and delete this file.
