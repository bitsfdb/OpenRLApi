import os
import shutil
import logging
import subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

from .config import THUMBNAILS_DIR, CACHE_DIR

log = logging.getLogger("openrlapi.thumbnails")

PREFIXES = (
    "body_", "skin_", "wheel_", "hat_", "antenna_", "boost_", "explosion_",
    "paintfinish_", "playerbanner_", "avatarborder_", "flag_", "countryflag_",
    "ss_", "anthem_", "engineaudio_", "pennant_"
)


def _worker_extract_job(worker_id: int, upk_list: list[str], cooked_dir: Path, work_base: Path, output_dir: Path) -> int:
    w_dir = work_base / f"w{worker_id}"
    w_out = work_base / f"w{worker_id}_out"
    shutil.rmtree(w_dir, ignore_errors=True)
    shutil.rmtree(w_out, ignore_errors=True)
    w_dir.mkdir(parents=True, exist_ok=True)
    w_out.mkdir(parents=True, exist_ok=True)

    for name in upk_list:
        target = w_dir / name
        try:
            target.symlink_to(cooked_dir / name)
        except OSError:
            pass

    for name in upk_list:
        cmd = [
            "umodel",
            "-game=rocketleague",
            "-export",
            "-png",
            f"-out={w_out}",
            f"-path={w_dir}",
            name
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except (subprocess.SubprocessError, OSError):
            pass

    extracted_count = 0
    for p in w_out.rglob("*.png"):
        stem = p.parent.parent.name
        for suffix in ("_T_SF", "_t_sf", "_T", "_t", "_SF", "_sf"):
            if stem.endswith(suffix):
                stem = stem[:-len(suffix)]
                break
        stem_lower = stem.lower()

        primary_dest = output_dir / f"{stem_lower}_t.png"
        try:
            shutil.copy2(p, primary_dest)
            extracted_count += 1

            raw_dest = output_dir / p.name.lower()
            if not raw_dest.exists():
                raw_dest.symlink_to(primary_dest.name)

            for prefix in PREFIXES:
                if stem_lower.startswith(prefix):
                    stripped = stem_lower[len(prefix):]
                    stripped_dest = output_dir / f"{stripped}_t.png"
                    if not stripped_dest.exists():
                        stripped_dest.symlink_to(primary_dest.name)
                    break
        except OSError:
            pass

    shutil.rmtree(w_dir, ignore_errors=True)
    shutil.rmtree(w_out, ignore_errors=True)
    return extracted_count


def extract_thumbnails(cooked_dir: Path, output_dir: Path = THUMBNAILS_DIR) -> int:
    if not cooked_dir.exists():
        log.warning("Cooked directory %s does not exist", cooked_dir)
        return 0

    if not shutil.which("umodel"):
        log.error("umodel binary not found on PATH. Thumbnail extraction skipped.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    work_base = CACHE_DIR / "tmp_extract_thumbs"
    shutil.rmtree(work_base, ignore_errors=True)
    work_base.mkdir(parents=True, exist_ok=True)

    upk_files = [
        f.name for f in cooked_dir.iterdir()
        if f.is_file() and (f.name.endswith("_T_SF.upk") or f.name.endswith("_t_sf.upk") or "_t_" in f.name.lower())
    ]
    log.info("Found %d thumbnail UPK packages in %s", len(upk_files), cooked_dir)

    num_workers = min(8, max(2, os.cpu_count() or 4))
    chunks: list[list[str]] = [[] for _ in range(num_workers)]
    for i, name in enumerate(upk_files):
        chunks[i % num_workers].append(name)

    total_extracted = 0
    with ProcessPoolExecutor(max_workers=num_workers) as executor:
        futures = [
            executor.submit(_worker_extract_job, i, chunks[i], cooked_dir, work_base, output_dir)
            for i in range(num_workers)
            if chunks[i]
        ]
        for f in futures:
            try:
                total_extracted += f.result()
            except Exception as e:
                log.error("Worker extraction error: %s", e)

    shutil.rmtree(work_base, ignore_errors=True)
    log.info("Extracted %d thumbnails into %s", total_extracted, output_dir)
    return total_extracted
