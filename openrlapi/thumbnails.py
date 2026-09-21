import os
import shutil
import logging
import subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

from .config import THUMBNAILS_DIR, CACHE_DIR

log = logging.getLogger("openrlapi.thumbnails")

ASSET_PREFIXES = (
    "body_", "skin_", "wheel_", "hat_", "antenna_", "boost_", "explosion_",
    "paintfinish_", "playerbanner_", "avatarborder_", "flag_", "countryflag_",
    "ss_", "anthem_", "engineaudio_", "pennant_"
)


def _extract_upk_batch(worker_index: int, package_names: list[str], cooked_dir: Path, staging_dir: Path, output_dir: Path) -> int:
    worker_workspace = staging_dir / f"w{worker_index}"
    worker_output = staging_dir / f"w{worker_index}_out"
    shutil.rmtree(worker_workspace, ignore_errors=True)
    shutil.rmtree(worker_output, ignore_errors=True)
    worker_workspace.mkdir(parents=True, exist_ok=True)
    worker_output.mkdir(parents=True, exist_ok=True)

    for package_name in package_names:
        symlink_target = worker_workspace / package_name
        try:
            symlink_target.symlink_to(cooked_dir / package_name)
        except OSError:
            pass

    for package_name in package_names:
        cmd = [
            "umodel",
            "-game=rocketleague",
            "-export",
            "-png",
            f"-out={worker_output}",
            f"-path={worker_workspace}",
            package_name
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        except (subprocess.SubprocessError, OSError):
            pass

    extracted_count = 0
    for image_path in worker_output.rglob("*.png"):
        raw_stem = image_path.parent.parent.name
        for suffix in ("_T_SF", "_t_sf", "_T", "_t", "_SF", "_sf"):
            if raw_stem.endswith(suffix):
                raw_stem = raw_stem[:-len(suffix)]
                break
        normalized_stem = raw_stem.lower()

        primary_dest = output_dir / f"{normalized_stem}_t.png"
        try:
            shutil.copy2(image_path, primary_dest)
            extracted_count += 1

            raw_dest = output_dir / image_path.name.lower()
            if not raw_dest.exists():
                raw_dest.symlink_to(primary_dest.name)

            for prefix in ASSET_PREFIXES:
                if normalized_stem.startswith(prefix):
                    stripped_stem = normalized_stem[len(prefix):]
                    stripped_dest = output_dir / f"{stripped_stem}_t.png"
                    if not stripped_dest.exists():
                        stripped_dest.symlink_to(primary_dest.name)
                    break
        except OSError:
            pass

    shutil.rmtree(worker_workspace, ignore_errors=True)
    shutil.rmtree(worker_output, ignore_errors=True)
    return extracted_count


def extract_thumbnails(cooked_dir: Path, output_dir: Path = THUMBNAILS_DIR) -> int:
    if not cooked_dir.exists():
        log.warning("Cooked directory %s does not exist", cooked_dir)
        return 0

    if not shutil.which("umodel"):
        log.error("umodel binary not found on PATH. Thumbnail extraction skipped.")
        return 0

    output_dir.mkdir(parents=True, exist_ok=True)
    staging_dir = CACHE_DIR / "tmp_extract_thumbs"
    shutil.rmtree(staging_dir, ignore_errors=True)
    staging_dir.mkdir(parents=True, exist_ok=True)

    packages = [
        f.name for f in cooked_dir.iterdir()
        if f.is_file() and (f.name.endswith("_T_SF.upk") or f.name.endswith("_t_sf.upk") or "_t_" in f.name.lower())
    ]
    log.info("Found %d thumbnail UPK packages in %s", len(packages), cooked_dir)

    worker_count = min(8, max(2, os.cpu_count() or 4))
    package_batches: list[list[str]] = [[] for _ in range(worker_count)]
    for index, package_name in enumerate(packages):
        package_batches[index % worker_count].append(package_name)

    total_extracted = 0
    with ProcessPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(_extract_upk_batch, i, package_batches[i], cooked_dir, staging_dir, output_dir)
            for i in range(worker_count)
            if package_batches[i]
        ]
        for future in futures:
            try:
                total_extracted += future.result()
            except Exception as exc:
                log.error("Worker extraction error: %s", exc)

    shutil.rmtree(staging_dir, ignore_errors=True)
    log.info("Extracted %d thumbnails into %s", total_extracted, output_dir)
    return total_extracted
