#!/usr/bin/env python3
"""Prepare all first-install offline Quran, hadith and recitation assets for Zad Al Qolob.

Network access is used only by the build machine. The installed application reads
all bundled assets from Android's local assets/www directory.
"""
from __future__ import annotations
import concurrent.futures
import json
import sys
import shutil
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_ASSETS = ROOT / "android" / "app" / "src" / "main" / "assets" / "www"
AUDIO_DIR = ANDROID_ASSETS / "audio" / "maher"

URLS = {
    "quran": ["https://api.alquran.cloud/v1/quran/quran-uthmani"],
    "nawawi": [
        "https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/ara-nawawi.min.json",
        "https://raw.githubusercontent.com/fawazahmed0/hadith-api/1/editions/ara-nawawi.json",
    ],
    "bukhari": [
        "https://cdn.jsdelivr.net/gh/fawazahmed0/hadith-api@1/editions/ara-bukhari.min.json",
        "https://raw.githubusercontent.com/fawazahmed0/hadith-api/1/editions/ara-bukhari.json",
    ],
}
AUDIO_BASE = "https://cdn.mp3quran.net/audio/maher-muaiqly/r1/{number}.mp3"


def request_bytes(url: str, timeout: int = 90) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "ZadAlQolob-OfflineAssetBuilder/2.0"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status}: {url}")
        return response.read()


def fetch_json(url: str):
    return json.loads(request_bytes(url).decode("utf-8"))


def download_json(name: str):
    last_error = None
    for url in URLS[name]:
        for attempt in range(3):
            try:
                return fetch_json(url)
            except Exception as exc:
                last_error = exc
                if attempt < 2:
                    time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Unable to download {name} data: {last_error}")


def write_json(filename: str, data) -> None:
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    (ROOT / filename).write_text(encoded, encoding="utf-8")
    (ANDROID_ASSETS / filename).write_text(encoded, encoding="utf-8")
    print(f"  {filename}: {len(encoded.encode('utf-8')):,} bytes")


def build_quran():
    payload = download_json("quran")
    if payload.get("code") != 200 or not isinstance(payload.get("data"), dict):
        raise ValueError("Quran API returned an invalid response")
    source = payload["data"]
    surahs = source.get("surahs") or []
    if len(surahs) != 114:
        raise ValueError(f"Expected 114 surahs, received {len(surahs)}")
    ayahs = []
    for surah in surahs:
        for ayah in surah.get("ayahs") or []:
            if not ayah.get("text") or not ayah.get("page") or not ayah.get("juz"):
                raise ValueError(f"Incomplete Quran ayah in surah {surah.get('number')}")
            ayahs.append({**ayah, "surah": {"number": surah["number"], "name": surah["name"], "englishName": surah.get("englishName", "")}})
    if len(ayahs) != 6236:
        raise ValueError(f"Expected 6236 ayahs, received {len(ayahs)}")
    return {"surahs": surahs, "ayahs": ayahs, "edition": source.get("edition", {})}


def build_nawawi():
    payload = download_json("nawawi")
    hadiths = payload.get("hadiths") if isinstance(payload, dict) else None
    if not isinstance(hadiths, list) or len(hadiths) != 42:
        raise ValueError("Expected exactly 42 Nawawi hadiths")
    if any(not item.get("text") for item in hadiths):
        raise ValueError("Nawawi collection contains an empty hadith")
    return {"hadiths": sorted(hadiths, key=lambda item: int(item.get("hadithnumber", 0)))}


def build_bukhari():
    payload = download_json("bukhari")
    hadiths = payload.get("hadiths") if isinstance(payload, dict) else None
    if not isinstance(hadiths, list) or len(hadiths) < 7500:
        raise ValueError(f"Expected the complete Sahih al-Bukhari corpus (at least 7500 narrations); received {len(hadiths) if isinstance(hadiths, list) else 0}")
    if any(not item.get("text") for item in hadiths):
        raise ValueError("Bukhari corpus contains an empty narration")
    sections = payload.get("metadata", {}).get("sections", {}) if isinstance(payload.get("metadata"), dict) else {}
    # Preserve original text and numbering; do not manufacture commentary or meanings.
    normalized = []
    for item in hadiths:
        h = dict(item)
        ref = h.get("reference") if isinstance(h.get("reference"), dict) else {}
        book_no = h.get("book") or ref.get("book")
        if book_no is not None:
            h["bookNumber"] = book_no
            h["bookNameAr"] = sections.get(str(book_no), sections.get(book_no, ""))
        normalized.append(h)
    return {
        "hadiths": normalized,
        "total": len(normalized),
        "edition": payload.get("metadata", {}),
        "commentary_notice": "نصوص الأحاديث محفوظة كاملة. لا تتضمن هذه الطبعة نص شرح فتح الباري؛ لا يجوز استبداله بشرح مولّد أو منسوب لغير مصدره. يجب إرفاق مادة شرح محققة ومرخصة قبل إعلان اكتمال الشروح.",
        "text_source": "fawazahmed0/hadith-api — ara-bukhari; Arabic source text attributed to Sahih al-Bukhari.",
    }


def download_one_surah(number: int):
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    name = f"{number:03d}.mp3"
    dest = AUDIO_DIR / name
    if dest.exists() and dest.stat().st_size > 20_000:
        with dest.open("rb") as existing:
            head = existing.read(3)
        if head == b"ID3" or (head and head[0] == 0xFF):
            return number, dest.stat().st_size, "cached"
    url = AUDIO_BASE.format(number=f"{number:03d}")
    last_error = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ZadAlQolob-OfflineAssetBuilder/2.0"})
            tmp = dest.with_suffix(".mp3.part")
            with urllib.request.urlopen(req, timeout=180) as response, tmp.open("wb") as out:
                if response.status != 200:
                    raise RuntimeError(f"HTTP {response.status}: {url}")
                first = response.read(3)
                if not (first == b"ID3" or (first and first[0] == 0xFF)):
                    raise ValueError(f"Invalid MP3 header for surah {number}")
                out.write(first)
                shutil.copyfileobj(response, out, length=1024 * 1024)
            size = tmp.stat().st_size
            if size < 20_000:
                tmp.unlink(missing_ok=True)
                raise ValueError(f"Truncated MP3 for surah {number}")
            tmp.replace(dest)
            return number, size, "downloaded"
        except Exception as exc:
            last_error = exc
            if attempt < 3:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"Unable to download surah {number}: {last_error}")


def build_audio():
    print("Preparing all 114 original MP3 recitations by Maher Al-Muaiqly...")
    total = 0
    completed = 0
    failures = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(download_one_surah, n): n for n in range(1, 115)}
        for future in concurrent.futures.as_completed(futures):
            n = futures[future]
            try:
                _, size, state = future.result()
                total += size
                completed += 1
                print(f"  [{completed:03d}/114] Surah {n:03d}: {size:,} bytes ({state})")
            except Exception as exc:
                failures.append(str(exc))
    if failures:
        raise RuntimeError("Audio package incomplete:\n" + "\n".join(failures[:10]))
    manifest = {
        "reciter": "الشيخ ماهر المعيقلي",
        "riwayah": "حفص عن عاصم",
        "style": "مرتل",
        "count": 114,
        "files": [f"audio/maher/{n:03d}.mp3" for n in range(1, 115)],
        "bytes": total,
        "attribution": "Audio source: mp3quran.net — Maher Al-Muaiqly recitation. Attribution required.",
    }
    write_json("quran-audio-manifest.json", manifest)
    credit = "تلاوة القرآن الكريم: الشيخ ماهر المعيقلي — رواية حفص عن عاصم. مصدر ملفات الصوت: mp3quran.net (مسار reciter: maher-muaiqly/r1). تم تضمين الملفات محليًا لتعمل دون اتصال بعد تثبيت التطبيق."
    (ANDROID_ASSETS / "AUDIO_ATTRIBUTION.txt").write_text(credit, encoding="utf-8")
    attribution = (
        "زاد القلوب — مصادر المحتوى المضمّن\n"
        "نص القرآن: AlQuran Cloud API (quran-uthmani).\n"
        "الأربعون النووية وصحيح البخاري: fawazahmed0/hadith-api؛ متن صحيح البخاري عربي، مع حفظ الترقيم وبيانات المصدر.\n"
        "التلاوة: الشيخ ماهر المعيقلي، حفص عن عاصم، مرتل؛ ملفات MP3 من mp3quran.net.\n"
        "تنبيه: تضمين متن البخاري لا يعني تضمين شرح فتح الباري. لا تُنسب شروح إلى العلماء إلا بعد تضمين نص موثّق ومراجعته.\n"
    )
    (ANDROID_ASSETS / "CONTENT_ATTRIBUTION.txt").write_text(attribution, encoding="utf-8")
    print(f"  Audio total: {total:,} bytes ({total / (1024**3):.2f} GiB)")


def main():
    ANDROID_ASSETS.mkdir(parents=True, exist_ok=True)
    print("Preparing complete Quran text...")
    write_json("quran-data.json", build_quran())
    print("Preparing the 42 Nawawi hadiths...")
    write_json("nawawi-hadiths.json", build_nawawi())
    print("Preparing the complete Sahih al-Bukhari corpus...")
    write_json("bukhari-full.json", build_bukhari())
    build_audio()
    print("All requested text/audio assets are downloaded and validated for offline packaging.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
