#!/usr/bin/env python3
"""Fail the Android build if any required offline content is missing or incomplete."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WWW = ROOT / "android" / "app" / "src" / "main" / "assets" / "www"

def load(name):
    path = WWW / name
    if not path.is_file():
        raise SystemExit(f"Missing required offline asset: {path}")
    return json.loads(path.read_text(encoding="utf-8"))

quran = load("quran-data.json")
assert len(quran.get("surahs", [])) == 114, "Quran must contain 114 surahs"
assert len(quran.get("ayahs", [])) == 6236, "Quran must contain 6236 ayahs"
nawawi = load("nawawi-hadiths.json")
assert len(nawawi.get("hadiths", [])) == 42, "Nawawi must contain 42 hadiths"
bukhari = load("bukhari-full.json")
assert len(bukhari.get("hadiths", [])) >= 7500, "Bukhari must contain the complete corpus"
manifest = load("quran-audio-manifest.json")
assert manifest.get("count") == 114, "Audio manifest must list 114 surahs"
for n in range(1, 115):
    f = WWW / "audio" / "maher" / f"{n:03d}.mp3"
    if not f.is_file() or f.stat().st_size < 20_000:
        raise SystemExit(f"Missing or suspiciously small recitation file: {f}")
    with f.open("rb") as stream:
        header = stream.read(3)
    if header != b"ID3" and (not header or header[0] != 0xFF):
        raise SystemExit(f"Invalid MP3 header: {f}")
print(f"Offline validation passed: 114 surahs, 6236 ayahs, 42 Nawawi hadiths, {len(bukhari['hadiths'])} Bukhari narrations, 114 MP3 files.")
