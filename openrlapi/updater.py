import os
import json
import time
import shutil
import asyncio
import logging
import subprocess
import struct
import urllib.request
from pathlib import Path
from typing import Any
from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import (
    PROJECT_ROOT, DATA_DIR, CACHE_DIR, THUMBNAILS_DIR, GAMES_DIR,
    ITEMS_FILE, TITLES_FILE, ITEMS_VER_FILE, SYNC_MANIFEST_FILE,
    ALL_LANGUAGES, LANGUAGE_ALIASES,
    DEFAULT_PSYNET_BUILD_ID, DEFAULT_GAME_VERSION, EPIC_APP_NAME
)
from .extractor import generate
from .thumbnails import extract_thumbnails

log = logging.getLogger("openrlapi.updater")

LEGENDARY_BIN = shutil.which("legendary") or "legendary"


def get_legendary_status() -> dict[str, Any]:
    status = {
        "logged_in": False,
        "account": None,
        "account_id": None,
        "game_installed": False,
        "installed_version": None,
        "available_version": None,
        "thumbnails_count": 0,
        "items_count": 0,
        "last_sync": None,
        "disk_free_gb": 0.0,
    }

    try:
        _, _, free = shutil.disk_usage(str(PROJECT_ROOT))
        status["disk_free_gb"] = round(free / (1024 ** 3), 2)
    except OSError:
        pass

    if THUMBNAILS_DIR.exists():
        status["thumbnails_count"] = sum(1 for f in THUMBNAILS_DIR.iterdir() if f.is_file() and f.suffix.lower() == ".png")

    if ITEMS_FILE.exists():
        try:
            data = json.loads(ITEMS_FILE.read_text(encoding="utf-8"))
            status["items_count"] = len(data.get("items") or data.get("Items") or [])
        except Exception:
            pass

    if SYNC_MANIFEST_FILE.exists():
        try:
            status["last_sync"] = json.loads(SYNC_MANIFEST_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass

    try:
        res = subprocess.run([LEGENDARY_BIN, "status"], capture_output=True, text=True, timeout=15)
        for line in res.stdout.splitlines():
            line = line.strip()
            if line.startswith("Epic account:"):
                acc = line.split(":", 1)[1].strip()
                if acc and "<not logged in>" not in acc:
                    status["logged_in"] = True
                    status["account"] = acc
    except Exception as e:
        log.warning("Could not check Legendary status: %s", e)

    try:
        res_info = subprocess.run([LEGENDARY_BIN, "info", EPIC_APP_NAME, "-J"], capture_output=True, text=True, timeout=15)
        if res_info.returncode == 0 and res_info.stdout.strip():
            info_json = json.loads(res_info.stdout)
            status["game_installed"] = info_json.get("install", {}).get("is_installed", False)
            status["installed_version"] = info_json.get("install", {}).get("version")
            status["available_version"] = info_json.get("manifest", {}).get("app_version")
    except Exception:
        pass

    try:
        ver_info = get_or_derive_build_id()
        status["psynet_build_id"] = ver_info.get("build_id")
        status["game_version"] = ver_info.get("game_version")
    except Exception:
        status["psynet_build_id"] = DEFAULT_PSYNET_BUILD_ID

    return status


def decode_build_id(version_str: str) -> int:
    """Non-reflected CRC-32 (poly 0x04C11DB7) over UTF-16LE bytes used by PsyNet."""
    data = version_str.encode("utf-16-le")
    poly = 0x04C11DB7
    crc = 0xFFFFFFFF
    for b in data:
        crc ^= (b << 24) & 0xFFFFFFFF
        for _ in range(8):
            if crc & 0x80000000:
                crc = ((crc << 1) ^ poly) & 0xFFFFFFFF
            else:
                crc = (crc << 1) & 0xFFFFFFFF
    res = crc ^ 0xFFFFFFFF
    return res - 0x100000000 if res >= 0x80000000 else res


def extract_pe_version(exe_path: str | Path) -> dict[str, Any]:
    import pefile

    exe_path = Path(exe_path)
    if not exe_path.exists():
        raise FileNotFoundError(f"Binary not found: {exe_path}")

    pe = pefile.PE(str(exe_path), fast_load=True)
    pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_EXPORT"]])

    with open(exe_path, "rb") as f:
        raw_data = f.read()

    export_rva = None
    if hasattr(pe, "DIRECTORY_ENTRY_EXPORT") and pe.DIRECTORY_ENTRY_EXPORT:
        for exp in pe.DIRECTORY_ENTRY_EXPORT.symbols:
            if exp.name == b"GPsyonixBuildID":
                export_rva = exp.address
                break

    if not export_rva:
        raise ValueError("GPsyonixBuildID export symbol not found in PE binary")

    base = pe.OPTIONAL_HEADER.ImageBase
    ptr_off = pe.get_offset_from_rva(export_rva)
    string_va = struct.unpack("<Q", raw_data[ptr_off : ptr_off + 8])[0]
    string_rva = string_va - base
    str_off = pe.get_offset_from_rva(string_rva)

    chars = []
    idx = str_off
    while idx + 1 < len(raw_data):
        c = struct.unpack("<H", raw_data[idx : idx + 2])[0]
        if c == 0:
            break
        chars.append(chr(c))
        idx += 2

    game_version = "".join(chars)
    build_id = decode_build_id(game_version)

    needle = "PrimeUpdate".encode("utf-16-le")
    feature_sets = []
    for section in pe.sections:
        name = section.Name.decode("latin1", errors="ignore").rstrip("\x00")
        if ".rdata" in name:
            sect_data = raw_data[section.PointerToRawData : section.PointerToRawData + section.SizeOfRawData]
            offset = 0
            while True:
                pos = sect_data.find(needle, offset)
                if pos < 0:
                    break
                offset = pos + 1
                if pos % 2 != 0:
                    continue
                rest = sect_data[pos + len(needle) :]
                chars = []
                for i in range(0, len(rest), 2):
                    if i + 1 >= len(rest):
                        break
                    c = struct.unpack("<H", rest[i : i + 2])[0]
                    if c <= 0x20:
                        break
                    chars.append(chr(c))
                tail = "".join(chars)
                if tail:
                    digits = "".join(ch for ch in tail if ch.isdigit())
                    if digits:
                        feature_sets.append((int(digits), tail, f"PrimeUpdate{tail}"))

    feature_set = None
    if feature_sets:
        feature_sets.sort(key=lambda x: (x[0], x[1]), reverse=True)
        feature_set = feature_sets[0][2]

    return {
        "game_version": game_version,
        "build_id": str(build_id),
        "build_id_int": build_id,
        "feature_set": feature_set,
        "binary_path": str(exe_path),
    }


def fetch_manifest_file(
    rel_filename: str,
    output_path: Path | None = None,
    manifest_path: Path | None = None,
) -> Path:
    from legendary.models.manifest import Manifest
    from legendary.models.chunk import Chunk

    if output_path is None:
        output_path = GAMES_DIR / Path(rel_filename).name
    output_path = Path(output_path)

    if manifest_path is None:
        manifest_dir = Path.home() / ".config" / "legendary" / "manifests"
        manifests = sorted(manifest_dir.glob("Sugar_Windows_*.manifest"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not manifests:
            raise FileNotFoundError("No Sugar manifests found in legendary manifests directory")
        manifest_path = manifests[0]

    manifest_path = Path(manifest_path)
    m = Manifest.read_all(manifest_path.read_bytes())

    target_rel = rel_filename.replace("\\", "/").lower()
    target = next((f for f in m.file_manifest_list.elements if f.filename.replace("\\", "/").lower() == target_rel), None)
    if not target:
        raise ValueError(f"{rel_filename} not found in manifest")

    cdl = {c.guid: c for c in m.chunk_data_list.elements}
    base_url = "https://egdownload.fastly-edge.com/Builds/Org/o-98larctxyhn55kqjq5xjb9wzjl9hf9/e6bcca5b37d0457ca881aec508205542/default"
    needed_guids = list(dict.fromkeys(part.guid for part in target.chunk_parts))
    downloaded_chunks = {}

    def _dl_chunk(guid):
        url = f"{base_url}/{cdl[guid].path}"
        req = urllib.request.Request(url, headers={"User-Agent": "OpenRLApi/2.0"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            return guid, Chunk.read_buffer(resp.read()).data

    workers = min(16, max(4, len(needed_guids)))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        for guid, chunk_bytes in executor.map(_dl_chunk, needed_guids):
            downloaded_chunks[guid] = chunk_bytes

    out = bytearray(target.file_size)
    offset = 0
    for part in target.chunk_parts:
        part_data = downloaded_chunks[part.guid][part.offset : part.offset + part.size]
        out[offset : offset + part.size] = part_data
        offset += part.size

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(out)
    return output_path


def ensure_tagame_assets(cooked_dir: Path, _log=None) -> bool:
    log_func = _log if _log else log.info
    tagame_path = cooked_dir / "TAGame.upk"
    cache_dir = CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)

    for lang in ALL_LANGUAGES:
        c_name = f"Coalesced_{lang}.bin"
        c_path = cooked_dir / c_name
        cache_c = cache_dir / c_name
        if not c_path.exists() or c_path.stat().st_size < 100_000:
            if cache_c.exists() and cache_c.stat().st_size > 100_000:
                shutil.copy2(cache_c, c_path)
            else:
                log_func(f"Downloading {c_name} from CDN...")
                try:
                    fetch_manifest_file(f"TAGame/CookedPCConsole/{c_name}", c_path)
                    shutil.copy2(c_path, cache_c)
                except Exception as e:
                    log_func(f"Warning: Failed to fetch {c_name}: {e}")
        elif not cache_c.exists():
            shutil.copy2(c_path, cache_c)

    if not tagame_path.exists() or tagame_path.stat().st_size < 10_000_000:
        cache_tagame = cache_dir / "TAGame.upk"
        if cache_tagame.exists() and cache_tagame.stat().st_size > 10_000_000:
            shutil.copy2(cache_tagame, tagame_path)
        else:
            log_func("Downloading TAGame.upk from CDN...")
            try:
                fetch_manifest_file("TAGame/CookedPCConsole/TAGame.upk", tagame_path)
                shutil.copy2(tagame_path, cache_tagame)
            except Exception as e:
                log_func(f"Warning: Failed to fetch TAGame.upk: {e}")
    else:
        cache_tagame = cache_dir / "TAGame.upk"
        if not cache_tagame.exists():
            shutil.copy2(tagame_path, cache_tagame)

    return tagame_path.exists() and (cooked_dir / "Coalesced_INT.bin").exists()


def get_or_derive_build_id() -> dict[str, Any]:
    candidates = [
        GAMES_DIR / "RocketLeague.exe",
        GAMES_DIR / "TAGame" / "CookedPCConsole" / "RocketLeague.exe",
        GAMES_DIR / "rocketleague" / "Binaries" / "Win64" / "RocketLeague.exe",
    ]
    for c in candidates:
        if c.exists():
            try:
                return extract_pe_version(c)
            except Exception as e:
                log.warning("Failed to extract version from %s: %s", c, e)

    try:
        exe_path = fetch_manifest_file("Binaries/Win64/RocketLeague.exe", GAMES_DIR / "RocketLeague.exe")
        return extract_pe_version(exe_path)
    except Exception as e:
        log.warning("Could not fetch/extract RocketLeague.exe: %s", e)

    return {
        "game_version": DEFAULT_GAME_VERSION,
        "build_id": DEFAULT_PSYNET_BUILD_ID,
        "build_id_int": int(DEFAULT_PSYNET_BUILD_ID),
        "feature_set": "PrimeUpdate59.1",
        "binary_path": None,
    }


def sync_titles_from_psynet(build_id: str | None = None) -> dict[str, Any]:
    version_info = None
    if not build_id:
        version_info = get_or_derive_build_id()
        build_id = version_info["build_id"]

    game_version = version_info.get("game_version") if version_info else DEFAULT_GAME_VERSION
    feature_set = version_info.get("feature_set") if version_info else "PrimeUpdate59.1"
    headers = {
        "User-Agent": f"RL Win/{game_version} gzip (x86_64-pc-win32) curl-7.67.0 Schannel"
    }

    def _fetch_lang_titles(lang_code: str) -> tuple[str, dict, list]:
        url = f"https://config.psynet.gg/v2/Config/BattleCars/{build_id}/Prod/Epic/{lang_code}/"
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                ptc = data.get("PlayerTitleConfig", {})
                cats = {c["ID"]: c for c in ptc.get("Categories", []) if c.get("ID")}
                return lang_code, cats, ptc.get("Titles", [])
        except Exception as exc:
            log.warning("Failed to fetch titles for %s: %s", lang_code, exc)
            return lang_code, {}, []

    lang_data = {}
    with ThreadPoolExecutor(max_workers=12) as executor:
        futures = {executor.submit(_fetch_lang_titles, l): l for l in ALL_LANGUAGES}
        for fut in as_completed(futures):
            l_code, cats, raw_t = fut.result()
            lang_data[l_code] = (cats, raw_t)

    int_cats, int_raw_titles = lang_data.get("INT", ({}, []))
    if not int_raw_titles:
        for cats, raw_t in lang_data.values():
            if raw_t:
                int_cats, int_raw_titles = cats, raw_t
                break

    if not int_raw_titles:
        return {"success": False, "error": "Empty PlayerTitleConfig from PsyNet"}

    title_translations: dict[str, dict[str, str]] = {}
    for l_code, (_, raw_t) in lang_data.items():
        for t in raw_t:
            tid = t.get("ID")
            text = t.get("Text")
            if tid and text:
                title_translations.setdefault(tid, {})[l_code] = text
                for alias, canon in LANGUAGE_ALIASES.items():
                    if canon == l_code and len(alias) == 2:
                        title_translations[tid][alias] = text

    processed_titles = []
    for t in int_raw_titles:
        tid = t.get("ID", "")
        text = t.get("Text", "")
        cat_id = t.get("Category", "")
        cat_info = int_cats.get(cat_id, {})
        translations = title_translations.get(tid, {})
        translations.setdefault("INT", text)
        translations.setdefault("en", text)

        processed_titles.append({
            "id": tid,
            "text": text,
            "category": cat_id,
            "color": t.get("Color") or cat_info.get("Color") or "",
            "glow": t.get("GlowColor") or cat_info.get("GlowColor") or "",
            "translations": translations,
        })

    categories_list = list(int_cats.values())
    clean_titles = [{k: v for k, v in t.items() if k != "translations"} for t in processed_titles]
    available_locales = list(ALL_LANGUAGES)
    payload = {
        "game_version": game_version,
        "category_count": len(categories_list),
        "title_count": len(clean_titles),
        "available_locales": available_locales,
        "categories": categories_list,
        "titles": clean_titles,
    }

    master_payload = {
        "game_version": game_version,
        "category_count": len(categories_list),
        "title_count": len(processed_titles),
        "available_locales": available_locales,
        "categories": categories_list,
        "titles": processed_titles,
    }
    try:
        (TITLES_FILE.parent / "titles_master.json").write_text(json.dumps(master_payload, indent=2), encoding="utf-8")
    except Exception:
        pass

    TITLES_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    for l_code in ALL_LANGUAGES:
        loc_titles = [
            {k: v for k, v in t.items() if k != "translations" and k != "text"} | {"text": t.get("translations", {}).get(l_code) or t["text"]}
            for t in processed_titles
        ]
        loc_payload = {
            "game_version": game_version,
            "language": l_code,
            "category_count": len(categories_list),
            "title_count": len(loc_titles),
            "available_locales": available_locales,
            "categories": categories_list,
            "titles": loc_titles,
        }
        (DATA_DIR / f"titles_{l_code}.json").write_text(json.dumps(loc_payload, indent=2), encoding="utf-8")

    log.info("Synced %d titles across %d categories from PsyNet", len(clean_titles), len(categories_list))
    return {
        "success": True,
        "title_count": len(processed_titles),
        "category_count": len(categories_list),
        "build_id": build_id,
        "game_version": game_version,
    }


def sync_rocket_league(delete_upks_after: bool = False, force: bool = False) -> dict[str, Any]:
    stat = get_legendary_status()
    GAMES_DIR.mkdir(parents=True, exist_ok=True)
    start_time = time.time()
    logs: list[str] = []

    def _log(msg: str):
        log.info(msg)
        logs.append(f"[{time.strftime('%X')}] {msg}")

    install_cmd = [
        LEGENDARY_BIN, "-y", "install", EPIC_APP_NAME,
        "--base-path", str(GAMES_DIR),
        "--prefix", "TAGame/CookedPCConsole",
        "--prefix", "Binaries/Win64/RocketLeague.exe",
        "--download-only", "--skip-dlcs",
    ]
    if force:
        install_cmd.append("--force")

    try:
        proc = subprocess.Popen(install_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in iter(proc.stdout.readline, ''):
            if line.strip() and any(k in line for k in ("%", "Progress", "Finished", "Error")):
                _log(line.strip())
        proc.wait(timeout=3600)
    except Exception as e:
        _log(f"Download failed: {e}")
        return {"success": False, "error": str(e), "logs": logs}

    for root, _, files in os.walk(GAMES_DIR):
        for f in files:
            f_lower = f.lower()
            if f_lower == "tagame.upk" or f_lower.startswith("coalesced_") or f_lower.endswith(".bin"):
                continue
            if not f_lower.endswith((".upk", ".exe", ".bin")):
                try:
                    os.remove(os.path.join(root, f))
                except OSError:
                    pass

    cooked_dirs = list(GAMES_DIR.rglob("CookedPCConsole"))
    target_cooked = cooked_dirs[0] if cooked_dirs else (GAMES_DIR / "TAGame" / "CookedPCConsole")
    target_cooked.mkdir(parents=True, exist_ok=True)

    ensure_tagame_assets(target_cooked, _log=_log)
    extracted_thumbnails = extract_thumbnails(target_cooked, THUMBNAILS_DIR)
    _log(f"Extracted {extracted_thumbnails} thumbnails.")

    ver_info = get_or_derive_build_id()
    new_version = ver_info.get("game_version") or stat.get("available_version") or stat.get("installed_version") or DEFAULT_GAME_VERSION
    new_version = new_version.strip()

    ITEMS_VER_FILE.parent.mkdir(parents=True, exist_ok=True)
    ITEMS_VER_FILE.write_text(new_version + "\n", encoding="utf-8")

    items_data = generate(ITEMS_FILE)
    if "meta" in items_data:
        items_data["meta"]["game_version"] = new_version
        ITEMS_FILE.write_text(json.dumps(items_data, indent=2), encoding="utf-8")

    if delete_upks_after:
        for root, _, files in os.walk(GAMES_DIR):
            for f in files:
                f_lower = f.lower()
                if f_lower == "tagame.upk" or f_lower.startswith("coalesced_") or f_lower.endswith(".bin"):
                    continue
                if f_lower.endswith(".upk"):
                    try:
                        os.remove(os.path.join(root, f))
                    except OSError:
                        pass

    titles_res = sync_titles_from_psynet(build_id=ver_info.get("build_id"))
    duration = round(time.time() - start_time, 2)
    sync_result = {
        "success": True,
        "timestamp": int(time.time()),
        "duration_s": duration,
        "thumbnails_extracted": extracted_thumbnails,
        "total_items": len(items_data.get("items", [])),
        "titles_count": titles_res.get("title_count", 0),
        "version": new_version,
        "build_id": ver_info.get("build_id"),
        "logs": logs
    }

    SYNC_MANIFEST_FILE.write_text(json.dumps(sync_result, indent=2), encoding="utf-8")
    return sync_result


async def hourly_sync_worker():
    hours = 0
    while True:
        try:
            await asyncio.sleep(3600)
            hours += 1
            stat = get_legendary_status()
            avail = stat.get("available_version")
            installed = stat.get("installed_version")
            if avail and installed and avail != installed:
                await asyncio.to_thread(sync_rocket_league)
            if hours % 24 == 0:
                sync_titles_from_psynet()
        except asyncio.CancelledError:
            break
        except Exception as e:
            log.error("Hourly sync worker error: %s", e)
