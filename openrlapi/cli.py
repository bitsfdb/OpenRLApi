import argparse
import logging
import uvicorn
from pathlib import Path

from .config import HOST, PORT, WORKERS, ITEMS_FILE, GAMES_DIR, THUMBNAILS_DIR
from .extractor import generate
from .updater import sync_titles_from_psynet, sync_rocket_league
from .thumbnails import extract_thumbnails

log = logging.getLogger("openrlapi.cli")


def cmd_serve(args):
    host = args.host or HOST
    port = args.port or PORT
    workers = args.workers or WORKERS
    log.info("Starting OpenRLApi on http://%s:%d (workers: %d)...", host, port, workers)
    uvicorn.run("openrlapi.main:app", host=host, port=port, workers=workers, reload=args.reload)


def cmd_extract(args):
    out = Path(args.output) if args.output else ITEMS_FILE
    log.info("Extracting Rocket League items catalog to %s...", out)
    res = generate(out)
    log.info("Extraction complete! Total items: %d", len(res.get("items", [])))


def cmd_sync_titles(args):
    log.info("Syncing player titles from config.psynet.gg...")
    res = sync_titles_from_psynet(build_id=args.build_id)
    if res.get("success"):
        log.info("Synced %d titles across %d categories", res.get("title_count"), res.get("category_count"))
    else:
        log.error("Sync failed: %s", res.get("error"))


def cmd_extract_thumbs(args):
    cooked = Path(args.cooked_dir) if args.cooked_dir else (GAMES_DIR / "TAGame" / "CookedPCConsole")
    out = Path(args.out_dir) if args.out_dir else THUMBNAILS_DIR
    log.info("Extracting thumbnails from %s to %s...", cooked, out)
    count = extract_thumbnails(cooked, out)
    log.info("Extracted %d thumbnails", count)


def cmd_update(args):
    log.info("Checking Rocket League game updates and syncing...")
    res = sync_rocket_league(force=args.force)
    log.info("Update finished: %s", res.get("success"))


def main():
    parser = argparse.ArgumentParser(prog="openrlapi", description="OpenRLApi: Open-Source Rocket League API CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    p_serve = subparsers.add_parser("serve", help="Start the FastAPI web server")
    p_serve.add_argument("--host", default=None, help=f"Bind host (default: {HOST})")
    p_serve.add_argument("--port", type=int, default=None, help=f"Bind port (default: {PORT})")
    p_serve.add_argument("--workers", type=int, default=None, help=f"Uvicorn workers (default: {WORKERS})")
    p_serve.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    p_serve.set_defaults(func=cmd_serve)

    p_extract = subparsers.add_parser("extract", help="Extract item catalog from UPKs and localization files")
    p_extract.add_argument("--output", default=None, help="Output JSON path (default: items.json in data dir)")
    p_extract.set_defaults(func=cmd_extract)

    p_titles = subparsers.add_parser("sync-titles", help="Sync player titles from PsyNet in all 12 languages")
    p_titles.add_argument("--build-id", default=None, help="Explicit PsyNet build ID")
    p_titles.set_defaults(func=cmd_sync_titles)

    p_thumbs = subparsers.add_parser("extract-thumbs", help="Extract thumbnail PNGs with umodel")
    p_thumbs.add_argument("--cooked-dir", default=None, help="Path to TAGame/CookedPCConsole")
    p_thumbs.add_argument("--out-dir", default=None, help="Path to output thumbnails directory")
    p_thumbs.set_defaults(func=cmd_extract_thumbs)

    p_update = subparsers.add_parser("update", help="Run update check and sync pipeline")
    p_update.add_argument("--force", action="store_true", help="Force re-download and re-extract")
    p_update.set_defaults(func=cmd_update)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    main()
