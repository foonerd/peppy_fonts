#!/usr/bin/env python3
"""PeppyFont build script.

Downloads Google Noto font components and merges them into three
weight-matched font files with broad Unicode coverage for music
metadata display.

Requires: pip install fonttools cu2qu brotli

Usage: python scripts/build.py [--config scripts/config.json] [--dry-run]
"""

import argparse
import json
import os
import struct
import sys
import time
import urllib.request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_DIR = os.path.dirname(SCRIPT_DIR)
DEFAULT_CONFIG = os.path.join(SCRIPT_DIR, "config.json")
DOWNLOAD_DIR = os.path.join(REPO_DIR, ".cache", "downloads")


# ---------------------------------------------------------------------------
# Unicode ranges for CJK subsetting
# Full NotoSansCJKsc has ~65k glyphs (fills the TTF limit).
# We subset to commonly used ranges, leaving room for other scripts.
# ---------------------------------------------------------------------------
CJK_UNICODE_RANGES = (
    # CJK Symbols and Punctuation
    list(range(0x3000, 0x3040))
    # Hiragana
    + list(range(0x3040, 0x30A0))
    # Katakana
    + list(range(0x30A0, 0x3100))
    # Bopomofo
    + list(range(0x3100, 0x3130))
    # CJK Unified Ideographs (full BMP block - ~20k characters)
    + list(range(0x4E00, 0x9FFF))
    # CJK Compatibility Ideographs
    + list(range(0xF900, 0xFB00))
    # Hangul Syllables (8192 most common - AC00 to CBFF)
    + list(range(0xAC00, 0xCC00))
    # Fullwidth Forms (fullwidth ASCII, halfwidth katakana)
    + list(range(0xFF00, 0xFFF0))
    # Basic Latin (overlap with base font - needed for subsetter)
    + list(range(0x0020, 0x007F))
)


def load_config(config_path):
    """Load build configuration from JSON file."""
    with open(config_path, "r") as f:
        return json.load(f)


def download_font(filename, source_url, dest_dir):
    """Download a font file if not already cached.

    :param filename: Font filename (e.g. 'NotoSans-Light.ttf')
    :param source_url: Base URL for the font repository
    :param dest_dir: Directory to save downloaded file
    :return: Path to downloaded file, or None on failure
    """
    dest_path = os.path.join(dest_dir, filename)
    if os.path.exists(dest_path) and os.path.getsize(dest_path) > 0:
        return dest_path

    url = f"{source_url}/{filename}"
    print(f"  Downloading {filename}...")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "PeppyFont-Builder/1.0"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
            if len(data) < 100:
                print(f"    ERROR: Response too small ({len(data)} bytes) - likely 404")
                return None
            os.makedirs(dest_dir, exist_ok=True)
            with open(dest_path, "wb") as f:
                f.write(data)
            print(f"    OK ({len(data) / 1024:.0f}K)")
            return dest_path
    except Exception as e:
        print(f"    FAILED: {e}")
        return None


def otf_to_ttf(input_path, output_path, max_err=1.0):
    """Convert OTF (CFF outlines) to TTF (TrueType quadratic outlines).

    CJK Noto fonts are distributed as OTF (CFF). pyftmerge requires all
    input fonts to have the same outline format. This converts CFF cubic
    curves to TrueType quadratic curves.

    :param input_path: Path to OTF font file
    :param output_path: Path to write TTF font file
    :param max_err: Maximum approximation error for cubic-to-quadratic conversion
    """
    from fontTools.ttLib import TTFont
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib.tables._g_l_y_f import table__g_l_y_f, Glyph as TTGlyph
    from fontTools.ttLib.tables._l_o_c_a import table__l_o_c_a
    from fontTools.ttLib.tables._m_a_x_p import table__m_a_x_p

    font = TTFont(input_path)

    if "CFF " not in font:
        # Already TTF - just copy
        font.save(output_path)
        font.close()
        return True

    cff = font["CFF "]
    char_strings = cff.cff.topDictIndex[0].CharStrings
    glyph_order = font.getGlyphOrder()
    total = len(glyph_order)
    print(f"    Converting {total} glyphs CFF -> glyf...")

    glyf_table = table__g_l_y_f()
    glyf_table.glyphs = {}
    glyf_table.glyphOrder = glyph_order

    ok = 0
    for gn in glyph_order:
        try:
            tt_pen = TTGlyphPen(None)
            cu2qu_pen = Cu2QuPen(tt_pen, max_err, reverse_direction=True)
            char_strings[gn].draw(cu2qu_pen)
            glyf_table[gn] = tt_pen.glyph()
            ok += 1
        except Exception:
            glyf_table[gn] = TTGlyph()

    # Remove CFF-specific tables
    for t in ["CFF ", "VORG", "vhea", "vmtx", "BASE", "DSIG"]:
        if t in font:
            del font[t]

    # Add TTF-specific tables
    font["glyf"] = glyf_table
    font["loca"] = table__l_o_c_a()
    font["head"].indexToLocFormat = 1
    font.sfntVersion = "\x00\x01\x00\x00"

    # Rebuild maxp as TTF version 1.0 (CFF maxp v0.5 causes merge failure)
    new_maxp = table__m_a_x_p()
    new_maxp.tableTag = "maxp"
    raw = struct.pack(">I", 0x00010000)  # version 1.0
    raw += struct.pack(">H", total)  # numGlyphs
    raw += struct.pack(">H", 0) * 13  # remaining fields (recalculated on save)
    new_maxp.decompile(raw, font)
    font["maxp"] = new_maxp

    font.save(output_path)
    font.close()

    failed = total - ok
    if failed > 0:
        print(f"    Done: {ok} ok, {failed} empty fallback")
    else:
        print(f"    Done: {ok} glyphs converted")
    return True


def subset_cjk(input_path, output_path):
    """Subset CJK font to commonly used Unicode ranges.

    Full NotoSansCJKsc has ~65k glyphs which fills the TTF limit.
    Subsetting to common ranges leaves room for other scripts in
    the merged font.

    :param input_path: Path to full CJK font
    :param output_path: Path to write subsetted font
    """
    from fontTools.ttLib import TTFont
    from fontTools.subset import Subsetter, Options

    font = TTFont(input_path)
    options = Options()
    options.layout_features = ["*"]
    options.name_IDs = ["*"]
    options.notdef_outline = True

    subsetter = Subsetter(options=options)
    subsetter.populate(unicodes=CJK_UNICODE_RANGES)
    subsetter.subset(font)

    glyphs = len(font.getGlyphOrder())
    font.save(output_path)
    font.close()

    print(f"    Subset: {glyphs} glyphs")
    return True


def merge_fonts(font_paths, output_path):
    """Merge multiple TTF font files into one.

    All input fonts must be TTF format (TrueType outlines).
    Use otf_to_ttf() to convert OTF fonts before merging.

    :param font_paths: List of TTF file paths to merge
    :param output_path: Path to write merged font
    :return: (glyph_count, char_count) tuple
    """
    from fontTools.merge import Merger

    merger = Merger()
    merged = merger.merge(font_paths)
    merged.save(output_path)

    glyphs = len(merged.getGlyphOrder())
    cmap = merged.getBestCmap()
    chars = len(cmap) if cmap else 0
    merged.close()

    return glyphs, chars


def resolve_url(filename, sources_config):
    """Resolve download URL for a font filename.

    :param filename: Font filename (e.g. 'NotoSansArabic-Light.ttf')
    :param sources_config: Sources dict from config.json
    :return: Base URL string
    """
    if "CJK" in filename:
        return sources_config["noto_cjk"]
    else:
        # Extract family name: NotoSansArabic-Light.ttf -> NotoSansArabic
        family = filename.split("-")[0]
        base = sources_config["noto_base"]
        return f"{base}/{family}/hinted/ttf"


def build_weight(weight_name, weight_config, sources_config, output_dir,
                 output_prefix, cache_dir, dry_run=False):
    """Build a single weight (Light, Regular, or Bold).

    Pipeline per weight:
    1. Download base font (Latin/Cyrillic/Greek TTF)
    2. Download CJK font (OTF) -> subset -> convert to TTF
    3. Download per-script fonts (TTF)
    4. Merge all into one TTF

    :return: Output file path, or None on failure
    """
    print(f"\n{'='*60}")
    print(f"Building {output_prefix}-{weight_name}")
    print(f"{'='*60}")
    start = time.time()

    if dry_run:
        print(f"  BASE: {weight_config['base']}")
        print(f"  CJK:  {weight_config['cjk']}")
        for s in weight_config.get("scripts", []):
            print(f"  SCRIPT: {s}")
        return None

    merge_inputs = []
    cjk_cache = os.path.join(cache_dir, "cjk")
    base_cache = os.path.join(cache_dir, "base")
    os.makedirs(cjk_cache, exist_ok=True)
    os.makedirs(base_cache, exist_ok=True)

    # --- Base font (TTF, no conversion needed) ---
    base_name = weight_config["base"]
    base_url = resolve_url(base_name, sources_config)
    base_path = download_font(base_name, base_url, base_cache)
    if not base_path:
        print(f"  ERROR: Failed to download base font {base_name}")
        return None
    merge_inputs.append(base_path)

    # --- CJK font (OTF -> subset -> convert to TTF) ---
    cjk_name = weight_config["cjk"]
    cjk_url = resolve_url(cjk_name, sources_config)
    cjk_raw = download_font(cjk_name, cjk_url, cjk_cache)
    if cjk_raw:
        # Subset
        cjk_subset = os.path.join(cjk_cache, cjk_name.replace(".otf", "-subset.otf"))
        if not os.path.exists(cjk_subset):
            print(f"  Subsetting {cjk_name}...")
            subset_cjk(cjk_raw, cjk_subset)

        # Convert OTF to TTF
        cjk_ttf = os.path.join(cjk_cache, cjk_name.replace(".otf", "-subset.ttf"))
        if not os.path.exists(cjk_ttf):
            print(f"  Converting {cjk_name} OTF -> TTF...")
            otf_to_ttf(cjk_subset, cjk_ttf)

        merge_inputs.append(cjk_ttf)
    else:
        print(f"  WARNING: CJK font {cjk_name} not available - skipping CJK")

    # --- Per-script fonts (TTF, no conversion needed) ---
    for script_name in weight_config.get("scripts", []):
        script_url = resolve_url(script_name, sources_config)
        script_path = download_font(script_name, script_url, base_cache)
        if script_path:
            merge_inputs.append(script_path)
        else:
            print(f"  WARNING: Script font {script_name} not available - skipping")

    # --- Merge ---
    print(f"\n  Merging {len(merge_inputs)} fonts...")
    output_name = f"{output_prefix}-{weight_name}.ttf"
    output_path = os.path.join(output_dir, output_name)

    try:
        glyphs, chars = merge_fonts(merge_inputs, output_path)
        sz = os.path.getsize(output_path)
        elapsed = time.time() - start
        print(f"  OUTPUT: {output_name}")
        print(f"  Glyphs: {glyphs}, Characters: {chars}, Size: {sz/1024/1024:.1f}MB")
        print(f"  Time: {elapsed:.1f}s")
        return output_path
    except Exception as e:
        print(f"  MERGE FAILED: {e}")
        import traceback
        traceback.print_exc()
        return None


def verify_coverage(font_path):
    """Verify script coverage of a built font."""
    from fontTools.ttLib import TTFont

    font = TTFont(font_path)
    cmap = font.getBestCmap()
    font.close()

    if not cmap:
        print("  No cmap found!")
        return False

    test_chars = {
        "Latin":      "Hello World",
        "Cyrillic":   "\u041f\u0440\u0438\u0432\u0435\u0442",
        "Greek":      "\u0393\u03b5\u03b9\u03b1",
        "CJK":        "\u4e16\u754c\u4f60\u597d",
        "Japanese":   "\u3053\u3093\u306b\u3061\u306f",
        "Korean":     "\uc548\ub155",
        "Arabic":     "\u0645\u0631\u062d\u0628\u0627",
        "Hebrew":     "\u05e9\u05dc\u05d5\u05dd",
        "Devanagari": "\u0928\u092e\u0938\u094d\u0924\u0947",
        "Thai":       "\u0e2a\u0e27\u0e31\u0e2a\u0e14\u0e35",
        "Bengali":    "\u09a8\u09ae\u09b8\u09cd\u0995\u09be\u09b0",
        "Tamil":      "\u0bb5\u0ba3\u0b95\u0bcd\u0b95\u0bae\u0bcd",
        "Georgian":   "\u10d2\u10d0\u10db\u10d0",
        "Armenian":   "\u0532\u0561\u0580\u0565\u0582",
    }

    print(f"\n  Coverage: {os.path.basename(font_path)}")
    all_ok = True
    for script, text in test_chars.items():
        covered = sum(1 for ch in text if ord(ch) in cmap)
        total = len(text)
        if covered == total:
            status = "OK"
        else:
            status = f"PARTIAL ({covered}/{total})"
            all_ok = False
        print(f"    {script:12s}: {status}")

    return all_ok


def main():
    parser = argparse.ArgumentParser(description="Build PeppyFont from Noto components")
    parser.add_argument("--config", default=DEFAULT_CONFIG, help="Path to config.json")
    parser.add_argument("--output", default=None, help="Output directory (overrides config)")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be done")
    parser.add_argument("--no-verify", action="store_true", help="Skip coverage verification")
    parser.add_argument("--clean", action="store_true", help="Remove download cache before build")
    args = parser.parse_args()

    config = load_config(args.config)
    output_dir = args.output or os.path.join(REPO_DIR, config["output_dir"])
    output_prefix = config.get("output_prefix", "PeppyFont")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)

    if args.clean and os.path.exists(DOWNLOAD_DIR):
        import shutil
        shutil.rmtree(DOWNLOAD_DIR)
        print("Cleaned download cache")

    print("PeppyFont Builder")
    print(f"  Config: {args.config}")
    print(f"  Output: {output_dir}")
    print(f"  Prefix: {output_prefix}")
    if args.dry_run:
        print("  Mode: DRY RUN")

    results = {}
    for weight_name, weight_config in config["weights"].items():
        output_path = build_weight(
            weight_name, weight_config, config["sources"],
            output_dir, output_prefix, DOWNLOAD_DIR, args.dry_run
        )
        results[weight_name] = output_path

    # Summary
    print(f"\n{'='*60}")
    print("Build Summary")
    print(f"{'='*60}")
    all_ok = True
    for weight_name, path in results.items():
        if path and os.path.exists(path):
            sz = os.path.getsize(path)
            print(f"  {weight_name:8s}: {os.path.basename(path)} ({sz/1024/1024:.1f}MB)")
        else:
            print(f"  {weight_name:8s}: {'SKIPPED (dry run)' if args.dry_run else 'FAILED'}")
            if not args.dry_run:
                all_ok = False

    # Verify coverage
    if not args.dry_run and not args.no_verify:
        for weight_name, path in results.items():
            if path and os.path.exists(path):
                verify_coverage(path)

    if all_ok and not args.dry_run:
        print("\nBuild complete.")
    elif args.dry_run:
        print("\nDry run complete.")
    else:
        print("\nBuild completed with errors.")
        sys.exit(1)


if __name__ == "__main__":
    main()
