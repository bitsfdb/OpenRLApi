import argparse
import logging
import uvicorn
from pathlib import Path

from .config import HOST, PORT, WORKERS, ITEMS_FILE, GAMES_DIR, THUMBNAILS_DIR
from .extractor import extract_catalog
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
    output_path = Path(args.output) if args.output else ITEMS_FILE
    log.info("Extracting Rocket League items catalog to %s...", output_path)
    catalog = extract_catalog(output_path)
    log.info("Extraction complete! Total items: %d", len(catalog.get("items", [])))


def cmd_sync_titles(args):
    log.info("Syncing player titles from config.psynet.gg...")
    result = sync_titles_from_psynet(build_id=args.build_id)
    if result.get("success"):
        log.info("Synced %d titles across %d categories", result.get("title_count"), result.get("category_count"))
    else:
        log.error("Sync failed: %s", result.get("error"))


def cmd_extract_thumbs(args):
    cooked_dir = Path(args.cooked_dir) if args.cooked_dir else (GAMES_DIR / "TAGame" / "CookedPCConsole")
    output_dir = Path(args.out_dir) if args.out_dir else THUMBNAILS_DIR
    log.info("Extracting thumbnails from %s to %s...", cooked_dir, output_dir)
    extracted_count = extract_thumbnails(cooked_dir, output_dir)
    log.info("Extracted %d thumbnails", extracted_count)


def cmd_update(args):
    log.info("Checking Rocket League game updates and syncing...")
    result = sync_rocket_league(force=args.force)
    log.info("Update finished: %s", result.get("success"))


def main():
    parser = argparse.ArgumentParser(prog="openrlapi", description="OpenRLApi: Open-Source Rocket League API CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    serve_parser = subparsers.add_parser("serve", help="Start the FastAPI web server")
    serve_parser.add_argument("--host", default=None, help=f"Bind host (default: {HOST})")
    serve_parser.add_argument("--port", type=int, default=None, help=f"Bind port (default: {PORT})")
    serve_parser.add_argument("--workers", type=int, default=None, help=f"Uvicorn workers (default: {WORKERS})")
    serve_parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    serve_parser.set_defaults(func=cmd_serve)

    extract_parser = subparsers.add_parser("extract", help="Extract item catalog from UPKs and localization files")
    extract_parser.add_argument("--output", default=None, help="Output JSON path (default: items.json in data dir)")
    extract_parser.set_defaults(func=cmd_extract)

    titles_parser = subparsers.add_parser("sync-titles", help="Sync player titles from PsyNet in all 12 languages")
    titles_parser.add_argument("--build-id", default=None, help="Explicit PsyNet build ID")
    titles_parser.set_defaults(func=cmd_sync_titles)

    thumbs_parser = subparsers.add_parser("extract-thumbs", help="Extract thumbnail PNGs with umodel")
    thumbs_parser.add_argument("--cooked-dir", default=None, help="Path to TAGame/CookedPCConsole")
    thumbs_parser.add_argument("--out-dir", default=None, help="Path to output thumbnails directory")
    thumbs_parser.set_defaults(func=cmd_extract_thumbs)

    update_parser = subparsers.add_parser("update", help="Run update check and sync pipeline")
    update_parser.add_argument("--force", action="store_true", help="Force re-download and re-extract")
    update_parser.set_defaults(func=cmd_update)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    main()
