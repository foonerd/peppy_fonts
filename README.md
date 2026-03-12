# Custom-built fonts for PeppyMeter Screensaver and PeppyMeter Remote.

Assembles Google Noto font components into three weight-matched files
with broad Unicode coverage for music metadata display worldwide.

## Output

- `fonts/PeppyFont-Light.ttf` - Light weight (artist, album, smaller text)
- `fonts/PeppyFont-Regular.ttf` - Regular weight (title, general text)
- `fonts/PeppyFont-Bold.ttf` - Bold weight (emphasis, headers)

DSEG7Classic-Italic.ttf (segment display) is not built here. It ships
separately with peppy_screensaver and peppy_remote.

## Script Coverage

Target coverage for music metadata in all major languages:

- Latin (English, French, German, Spanish, Portuguese, etc.)
- Cyrillic (Russian, Ukrainian, etc.)
- Greek
- CJK - Chinese, Japanese, Korean (IICore common subset)
- Arabic
- Hebrew
- Devanagari (Hindi, Marathi, Nepali)
- Bengali
- Tamil
- Thai
- Georgian
- Armenian

## Build

Fonts are built via GitHub Actions using Google's fonttools (pyftmerge).

Source fonts are downloaded from the official Noto Fonts project at build
time. No source font files are stored in this repository.

### Manual build

```
pip install fonttools
python scripts/build.py
```

Output goes to `fonts/`.

## Source

All source fonts are from the Google Noto project:
https://github.com/notofonts

## License

Output fonts are licensed under the SIL Open Font License, Version 1.1,
as required by the upstream Noto fonts.

Build scripts are licensed under GPL v3 (consistent with PeppyMeter).

## Integration

Built fonts are consumed by:
- [peppy_screensaver](https://github.com/foonerd/peppy_screensaver) - server plugin
- [peppy_remote](https://github.com/foonerd/peppy_remote) - Windows remote client
