import os
import json
import time
import shutil
import logging
import struct
import zlib
import io
import base64
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from .rl_upk_editor import (
    DecryptionProvider, find_valid_key, decrypt_data, FCompressedChunk,
    BinaryReader, parse_decrypted_package, parse_serialized_properties,
    PKG_COOKED, COMPRESS_NONE
)
from .config import (
    PROJECT_ROOT, DATA_DIR, CACHE_DIR, GAMES_DIR,
    ITEMS_FILE, ITEMS_VER_FILE,
    ALL_LANGUAGES, LANGUAGE_ALIASES, resolve_lang,
    COALESCED_AES_KEY_B64
)
from .thumbnails import extract_thumbnails

log = logging.getLogger("openrlapi.extractor")

OUTPUT_FILE = ITEMS_FILE
COOKED_DIR = GAMES_DIR / "TAGame" / "CookedPCConsole"
if not COOKED_DIR.exists():
    COOKED_DIR = GAMES_DIR / "rocketleague" / "TAGame" / "CookedPCConsole"

TAGAME_UPK = COOKED_DIR / "TAGame.upk"
COALESCED_INT = COOKED_DIR / "Coalesced_INT.bin"
CACHE_TAGAME_DECOMPRESSED = CACHE_DIR / "tagame_decompressed.upk"
CACHE_COALESCED = CACHE_DIR / "Coalesced_INT.bin"

COALESCED_AES_KEY = base64.b64decode(COALESCED_AES_KEY_B64)

PAINTS = {
    0: "None", 1: "Crimson", 2: "Lime", 3: "Black", 4: "Sky Blue",
    5: "Cobalt", 6: "Burnt Sienna", 7: "Forest Green", 8: "Purple",
    9: "Pink", 10: "Orange", 11: "Grey", 12: "Titanium White",
    13: "Saffron", 14: "Gold", 15: "Rose Gold",
}

CERTIFICATIONS = {
    0: "None", 1: "Aviator", 2: "Playmaker", 3: "Show-off", 4: "Sniper",
    5: "Paragon", 6: "Goalkeeper", 7: "Guardian", 8: "Juggler",
    9: "Tactician", 10: "Scorer", 11: "Sweeper", 12: "Striker",
    13: "Turtle", 14: "Victor", 15: "Acrobat",
}

QUALITY_MAP = {
    "EPQ_Common": "Common", "EPQ_Uncommon": "Uncommon", "EPQ_Rare": "Rare",
    "EPQ_VeryRare": "VeryRare", "EPQ_Import": "Import", "EPQ_Exotic": "Exotic",
    "EPQ_BlackMarket": "BlackMarket", "EPQ_Premium": "Premium",
    "EPQ_Limited": "Limited", "EPQ_Legacy": "Legacy",
}

SLOT_MAP = {
    "Antenna": "Antenna", "AvatarBorder": "Avatar Border",
    "PlayerAvatarBorder": "Avatar Border", "Blueprint": "Blueprint",
    "Body": "Body", "Boost": "Rocket Boost", "Crate": "Crate",
    "PremiumInventory": "Crate", "Currency": "Currency",
    "Decal": "Decal", "Skin": "Decal", "EngineAudio": "Engine Audio",
    "GoalExplosion": "Goal Explosion", "PaintFinish": "Paint Finish",
    "PlayerAnthem": "Player Anthem", "MusicStingers": "Player Anthem",
    "PlayerBanner": "Player Banner", "Banner": "Player Banner",
    "PlayerTitle": "Player Title", "Hat": "Topper", "Topper": "Topper",
    "Trail": "Trail", "SupersonicTrail": "Trail", "Wheels": "Wheels",
}


def _read_unreal_string(reader: io.BytesIO) -> str:
    raw_len = reader.read(4)
    if len(raw_len) < 4:
        return ""
    length = struct.unpack("<i", raw_len)[0]
    if length < 0:
        # Negative length indicates UTF-16LE encoded string with trailing null
        return reader.read(-length * 2)[:-2].decode("utf-16-le", errors="ignore")
    elif length > 0:
        return reader.read(length)[:-1].decode("latin1", errors="ignore")
    return ""


def download_coalesced_if_missing(target_path: Path, lang: str = "INT") -> bool:
    lang_canon = resolve_lang(lang)
    cache_path = CACHE_DIR / f"Coalesced_{lang_canon}.bin"

    if target_path.exists() and target_path.stat().st_size > 100_000:
        return True

    if cache_path.exists() and cache_path.stat().st_size > 100_000:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(cache_path, target_path)
        log.info("Restored Coalesced_%s.bin from cache to %s", lang_canon, target_path)
        return True

    try:
        import concurrent.futures
        import urllib.request
        from legendary.models.manifest import Manifest
        from legendary.models.chunk import Chunk

        manifest_dir = Path.home() / ".config" / "legendary" / "manifests"
        manifests = sorted(manifest_dir.glob("Sugar_Windows_*.manifest"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not manifests:
            return False

        m = Manifest.read_all(manifests[0].read_bytes())
        rel_target = f"TAGame/CookedPCConsole/Coalesced_{lang_canon}.bin".lower()
        target = next((f for f in m.file_manifest_list.elements if f.filename.lower() == rel_target), None)
        if not target:
            return False

        cdl = {c.guid: c for c in m.chunk_data_list.elements}
        base_url = "https://egdownload.fastly-edge.com/Builds/Org/o-98larctxyhn55kqjq5xjb9wzjl9hf9/e6bcca5b37d0457ca881aec508205542/default"
        needed_guids = list(dict.fromkeys(part.guid for part in target.chunk_parts))
        downloaded_chunks = {}

        def download_chunk(guid):
            url = f"{base_url}/{cdl[guid].path}"
            req = urllib.request.Request(url, headers={"User-Agent": "OpenRLApi/2.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                return guid, Chunk.read_buffer(resp.read()).data

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            for guid, chunk_bytes in executor.map(download_chunk, needed_guids):
                downloaded_chunks[guid] = chunk_bytes

        out = bytearray(target.file_size)
        offset = 0
        for part in target.chunk_parts:
            part_data = downloaded_chunks[part.guid][part.offset : part.offset + part.size]
            out[offset : offset + part.size] = part_data
            offset += part.size

        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(out)
        cache_path.write_bytes(out)
        log.info("Downloaded Coalesced_%s.bin (%d bytes)", lang_canon, len(out))
        return True
    except Exception as e:
        log.warning("Failed to download Coalesced_%s.bin via manifest: %s", lang_canon, e)
        return False


def extract_localization(coalesced_path: Path) -> dict[str, dict[str, str]]:
    if not coalesced_path.exists() and not download_coalesced_if_missing(coalesced_path):
        raise FileNotFoundError(f"Coalesced file not found at {coalesced_path}")

    enc = coalesced_path.read_bytes()
    pad = len(enc) % 16
    if pad != 0:
        enc = enc[:-pad]

    cipher = Cipher(algorithms.AES(COALESCED_AES_KEY), modes.ECB(), backend=default_backend())
    dec = cipher.decryptor().update(enc)
    reader = io.BytesIO(dec)

    num_files = struct.unpack("<I", reader.read(4))[0]
    loc_sections: dict[str, dict[str, str]] = {}

    for _ in range(num_files):
        _read_unreal_string(reader)
        n_sec = struct.unpack("<I", reader.read(4))[0]
        for _ in range(n_sec):
            sname = _read_unreal_string(reader).lower()
            n_k = struct.unpack("<I", reader.read(4))[0]
            kvs = {}
            for _ in range(n_k):
                k = _read_unreal_string(reader)
                v = _read_unreal_string(reader)
                kvs[k] = v
            loc_sections.setdefault(sname, {}).update(kvs)

    return loc_sections


def extract_all_localizations(cooked_dir: Path) -> dict[str, dict[str, str]]:
    all_loc: dict[str, dict[str, str]] = {}

    for lang in ALL_LANGUAGES:
        c_path = cooked_dir / f"Coalesced_{lang}.bin"
        if not c_path.exists():
            download_coalesced_if_missing(c_path, lang=lang)

        if not c_path.exists():
            continue

        try:
            enc = c_path.read_bytes()
            pad = len(enc) % 16
            if pad != 0:
                enc = enc[:-pad]

            cipher = Cipher(algorithms.AES(COALESCED_AES_KEY), modes.ECB(), backend=default_backend())
            dec = cipher.decryptor().update(enc)
            reader = io.BytesIO(dec)

            num_files = struct.unpack("<I", reader.read(4))[0]
            prod_map = {}
            for _ in range(num_files):
                fname = _read_unreal_string(reader)
                n_sec = struct.unpack("<I", reader.read(4))[0]
                is_prod = "products." in fname.lower()
                for _ in range(n_sec):
                    sname = _read_unreal_string(reader)
                    n_k = struct.unpack("<I", reader.read(4))[0]
                    label = None
                    for _ in range(n_k):
                        k = _read_unreal_string(reader)
                        v = _read_unreal_string(reader)
                        if k.lower() in ("label", "longlabel"):
                            label = v
                    if is_prod and label:
                        prod_map[sname.lower()] = label
            all_loc[lang] = prod_map
        except Exception as e:
            log.warning("Failed to parse localization for %s: %s", lang, e)

    return all_loc


def decompress_tagame(upk_path: Path, output_path: Path, keys_path: Path | None = None) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_mtime >= upk_path.stat().st_mtime and output_path.stat().st_size > 100_000_000:
        return output_path

    if keys_path is None:
        keys_path = PROJECT_ROOT / "keys.txt"

    provider = DecryptionProvider(str(keys_path)) if keys_path.exists() else DecryptionProvider("")
    with open(upk_path, "rb") as src:
        summary, meta, _, _ = find_valid_key(upk_path, provider)
        src.seek(0)
        header_bytes = src.read(summary.name_offset)
        decrypted_header = decrypt_data(src, summary, meta, provider)

        raw = decrypted_header[meta.compressed_chunks_offset:]
        count = struct.unpack("<I", raw[:4])[0]
        chunks: list[FCompressedChunk] = []
        offset = 4
        for _ in range(count):
            u_off = struct.unpack("<q", raw[offset:offset+8])[0]
            u_sz = struct.unpack("<i", raw[offset+8:offset+12])[0]
            c_off = struct.unpack("<q", raw[offset+12:offset+20])[0]
            c_sz = struct.unpack("<i", raw[offset+20:offset+24])[0]
            offset += 36
            chunks.append(FCompressedChunk(u_off, u_sz, c_off, c_sz))

        final_size = chunks[-1].uncompressed_offset + chunks[-1].uncompressed_size
        log.info("Decompressing %d chunks to %s (%.1f MB)...", len(chunks), output_path, final_size / (1024 * 1024))

        with open(output_path, "wb+") as dst:
            dst.write(header_bytes)
            dst.write(decrypted_header)
            dst.truncate(final_size)
            dst.seek(chunks[0].uncompressed_offset)
            r = BinaryReader(src)
            for chunk in chunks:
                src.seek(chunk.compressed_offset)
                r.read_i32()
                r.read_i32()
                r.read_i32()
                total_uncomp = r.read_i32()
                sum_uncomp = 0
                blocks = []
                while sum_uncomp < total_uncomp:
                    comp_sz = r.read_i32()
                    uncomp_sz = r.read_i32()
                    blocks.append((comp_sz, uncomp_sz))
                    sum_uncomp += uncomp_sz
                for comp_sz, uncomp_sz in blocks:
                    compressed_block = r.read_exact(comp_sz)
                    dst.write(zlib.decompress(compressed_block))

            dst.seek(summary.package_flags_flags_offset)
            dst.write(struct.pack("<I", summary.package_flags & ~PKG_COOKED))
            dst.seek(summary.compression_flags_offset)
            dst.write(struct.pack("<I", COMPRESS_NONE))

    return output_path


def extract_items_from_tagame(
    decompressed_upk: Path,
    loc_all_languages: dict[str, dict[str, str]],
    existing_items: dict[int, dict[str, Any]]
) -> list[dict[str, Any]]:
    pkg = parse_decrypted_package(decompressed_upk)

    products_db_exp = next(
        (exp for exp in pkg.exports
         if pkg.export_class_name(exp) == "ProductDatabase_TA" and pkg.resolve_name(exp.object_name) == "ProductsDB"),
        None
    )
    if products_db_exp is None:
        raise ValueError("ProductsDB (ProductDatabase_TA) export not found in TAGame.upk")

    props = parse_serialized_properties(pkg, products_db_exp, None)
    prod_prop = next((p for p in props if p.name == "Products_New"), None)
    if not prod_prop:
        raise ValueError("Products_New property not found in ProductsDB")

    abs_off = products_db_exp.serial_offset + prod_prop.value_offset
    raw = pkg.file_bytes[abs_off : abs_off + prod_prop.size]
    count = struct.unpack("<I", raw[:4])[0]

    int_loc = loc_all_languages.get("INT", {})
    extracted_items = []

    for i in range(count):
        off = 4 + i * 4
        obj_idx = struct.unpack("<i", raw[off:off+4])[0]
        if obj_idx <= 0:
            continue

        target_exp = pkg.exports[obj_idx - 1]
        name = pkg.resolve_name(target_exp.object_name)
        n_lower = name.lower()

        tprops = {p.name: p for p in parse_serialized_properties(pkg, target_exp, None)}

        label = int_loc.get(n_lower)
        if not label:
            label = existing_items.get(i, {}).get("Product") or name.replace("_", " ").title()

        item_translations: dict[str, str] = {}
        for lang_code in ALL_LANGUAGES:
            l_val = loc_all_languages.get(lang_code, {}).get(n_lower)
            if l_val:
                item_translations[lang_code] = l_val
                for alias, canon in LANGUAGE_ALIASES.items():
                    if canon == lang_code and len(alias) == 2:
                        item_translations[alias] = l_val

        item_translations.setdefault("INT", label)
        item_translations.setdefault("en", label)

        slot_name = "Unknown"
        if "Slot" in tprops:
            s_val = str(tprops["Slot"].value)
            if "Export[" in s_val:
                raw_slot = s_val.split("] ")[-1].rstrip(")")
                slot_name = SLOT_MAP.get(raw_slot, raw_slot)
        if slot_name == "Unknown" and i in existing_items:
            slot_name = existing_items[i].get("Slot", "Unknown")

        quality_name = "Common"
        if "Quality" in tprops:
            q_val = str(tprops["Quality"].value)
            quality_name = QUALITY_MAP.get(q_val, q_val.replace("EPQ_", ""))
        elif i in existing_items:
            quality_name = existing_items[i].get("Quality", "Common")

        unlock_method = "UnlockMethod_Online"
        if "UnlockMethod" in tprops:
            unlock_method = str(tprops["UnlockMethod"].value)
        elif i in existing_items:
            unlock_method = existing_items[i].get("UnlockMethod", "UnlockMethod_Online")

        paintable = False
        if "Attributes" in tprops:
            attr_prop = tprops["Attributes"]
            a_off = target_exp.serial_offset + attr_prop.value_offset
            a_raw = pkg.file_bytes[a_off : a_off + attr_prop.size]
            cnt = struct.unpack("<I", a_raw[:4])[0]
            for a_idx in range(cnt):
                ref = struct.unpack("<i", a_raw[4+a_idx*4:4+(a_idx+1)*4])[0]
                if ref > 0 and "Paint" in pkg.export_class_name(pkg.exports[ref-1]):
                    paintable = True
                    break
        elif i in existing_items:
            paintable = existing_items[i].get("Paintable", False)

        asset_pkg = str(tprops["AssetPackageName"].value) if "AssetPackageName" in tprops else ""
        asset_path = str(tprops["AssetPath"].value) if "AssetPath" in tprops else ""
        if not asset_pkg and i in existing_items:
            asset_pkg = existing_items[i].get("AssetPackage", "")
        if not asset_path and i in existing_items:
            asset_path = existing_items[i].get("AssetPath", "")

        record = {
            "ID": i,
            "Product": label,
            "Slot": slot_name,
            "Quality": quality_name,
            "UnlockMethod": unlock_method,
            "Paintable": paintable,
            "AssetPackage": asset_pkg,
            "AssetPath": asset_path,
            "translations": item_translations,
        }

        if i in existing_items:
            old = existing_items[i]
            if "LongLabel" in old and old["LongLabel"] != label:
                record["LongLabel"] = old["LongLabel"]
            if "Paints" in old:
                record["Paints"] = old["Paints"]

        extracted_items.append(record)

    extracted_items.sort(key=lambda x: x["ID"])
    return extracted_items


def get_game_version() -> str:
    if ITEMS_VER_FILE.exists():
        ver = ITEMS_VER_FILE.read_text(encoding="utf-8").strip()
        if ver:
            return ver
    return "260825.79374.526531"


def extract_catalog(output_file: Path = OUTPUT_FILE) -> dict[str, Any]:
    existing_items = {}
    if output_file.exists():
        try:
            cached_data = json.loads(output_file.read_text(encoding="utf-8"))
            for item in cached_data.get("items", []) or cached_data.get("Items", []):
                item_id = item.get("id") if item.get("id") is not None else item.get("ID")
                if item_id is not None:
                    existing_items[int(item_id)] = item
        except Exception:
            pass

    game_ver = get_game_version()
    has_upk = TAGAME_UPK.exists() and TAGAME_UPK.stat().st_size > 1_000_000
    has_coalesced = COALESCED_INT.exists() or download_coalesced_if_missing(COALESCED_INT)

    if has_upk and has_coalesced:
        try:
            log.info("Starting UPK and localization extraction...")
            t0 = time.time()
            loc_all_languages = extract_all_localizations(COOKED_DIR)
            decompressed_upk = decompress_tagame(TAGAME_UPK, CACHE_TAGAME_DECOMPRESSED)
            items = extract_items_from_tagame(decompressed_upk, loc_all_languages, existing_items)
            log.info("Extracted %d items across %d languages in %.2fs", len(items), len(loc_all_languages), time.time() - t0)

            payload = {
                "Items": items,
                "items": items,
                "meta": {
                    "game_version": game_ver,
                    "dump_fingerprint": "openrl_tagame_upk",
                    "generated_at": int(time.time()),
                    "total_items": len(items),
                    "languages": list(loc_all_languages.keys()),
                    "categories": {}
                }
            }

            output_file.parent.mkdir(parents=True, exist_ok=True)
            output_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")

            for lang_code in ALL_LANGUAGES:
                localized_items = []
                for it in items:
                    tr_name = it.get("translations", {}).get(lang_code) or it.get("Product") or it.get("name") or ""
                    localized_items.append({**it, "Product": tr_name, "name": tr_name})

                loc_payload = {
                    "Items": localized_items,
                    "items": localized_items,
                    "meta": {
                        "game_version": game_ver,
                        "language": lang_code,
                        "generated_at": int(time.time()),
                        "total_items": len(localized_items),
                    }
                }
                (DATA_DIR / f"items_{lang_code}.json").write_text(json.dumps(loc_payload, indent=2), encoding="utf-8")

            return payload
        except Exception as e:
            log.error("UPK extraction failed, falling back to existing data: %s", e)

    if existing_items:
        items = list(existing_items.values())
        payload = {
            "Items": items,
            "items": items,
            "meta": {
                "game_version": game_ver,
                "dump_fingerprint": "openrl_fallback",
                "generated_at": int(time.time()),
                "total_items": len(items),
                "categories": {}
            }
        }
        output_file.parent.mkdir(parents=True, exist_ok=True)
        output_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return payload

    skeleton = {
        "meta": {
            "game_version": game_ver,
            "dump_fingerprint": "openrl_initial",
            "generated_at": int(time.time()),
            "total_items": 0,
            "categories": {}
        },
        "items": [],
        "Items": []
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    output_file.write_text(json.dumps(skeleton, indent=2), encoding="utf-8")
    return skeleton

generate = extract_catalog
