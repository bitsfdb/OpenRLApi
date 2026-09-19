import os
import json
import gzip
import time
import logging
import threading
import asyncio
from pathlib import Path
from typing import Any
from collections import defaultdict
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from .config import (
    PORT, RATE_LIMIT_PER_MINUTE, CORS_ORIGINS,
    DATA_DIR, THUMBNAILS_DIR,
    ITEMS_FILE, TITLES_FILE, ITEMS_VER_FILE,
    ALL_LANGUAGES, resolve_lang
)
from .models import (
    ProductResponse, ProductsListResponse,
    TitleResponse, TitlesListResponse,
    HealthResponse
)
from .extractor import generate
from .updater import sync_titles_from_psynet, hourly_sync_worker

log = logging.getLogger("openrlapi")

_items_cache_by_lang: dict[str, tuple[bytes, bytes, float]] = {}
_items_lock = threading.Lock()

_titles_cache_by_lang: dict[str, tuple[bytes, bytes, float]] = {}
_v2_titles_by_lang: dict[str, tuple[bytes, bytes, float]] = {}
_titles_lock = threading.Lock()

_data_cache: dict[str, Any] | None = None
_cache_mtime: float = 0.0
_items_by_id: dict[str, dict[str, Any]] = {}
_reload_lock = threading.Lock()

_titles_cache: dict[str, Any] | None = None
_titles_cache_mtime: float = 0.0
_titles_by_id: dict[str, dict[str, Any]] = {}
_titles_by_text: dict[str, dict[str, Any]] = {}
_titles_reload_lock = threading.Lock()

_QUALITY_NORMALIZE = {"VeryRare": "Very Rare", "BlackMarket": "Black Market"}


def client_accepts_gzip(request: Request) -> bool:
    ae = request.headers.get("accept-encoding", "")
    if not ae:
        return False
    for part in ae.split(","):
        part = part.strip().lower()
        if not part:
            continue
        enc = part.split(";")[0].strip()
        if enc in ("gzip", "*"):
            if ";q=0" in part.replace(" ", ""):
                return False
            return True
    return False


def _resolve_lang_file(base_name: str, lang_code: str, fallback_file: Path) -> Path:
    if lang_code == "INT":
        return fallback_file
    for candidate in (f"{base_name}_{lang_code}.json", f"{base_name}_{lang_code.lower()}.json"):
        p = DATA_DIR / candidate
        if p.exists():
            return p
    return fallback_file


def _get_cached_gzip(
    cache: dict[str, tuple[bytes, bytes, float]],
    file_path: Path,
    lang_code: str,
    lock: threading.Lock,
    fallback_code: str | None = None,
    force: bool = False
) -> tuple[bytes, bytes]:
    try:
        mtime = file_path.stat().st_mtime
    except OSError:
        mtime = 0.0

    entry = cache.get(lang_code)
    if not force and entry and mtime == entry[2] and mtime != 0.0:
        return entry[0], entry[1]

    with lock:
        entry = cache.get(lang_code)
        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            mtime = 0.0

        if not force and entry and mtime == entry[2] and mtime != 0.0:
            return entry[0], entry[1]

        if not file_path.exists() or mtime == 0.0:
            if fallback_code and fallback_code != lang_code:
                fb_file = _resolve_lang_file(file_path.stem.split("_")[0], fallback_code, ITEMS_FILE if "items" in file_path.name else TITLES_FILE)
                return _get_cached_gzip(cache, fb_file, fallback_code, lock, force=force)
            return b"{}", b""

        raw = file_path.read_bytes()
        gz = gzip.compress(raw, compresslevel=9)
        cache[lang_code] = (raw, gz, mtime)
        return raw, gz


def _get_items_cache_for_lang(lang_code: str, force: bool = False) -> tuple[bytes, bytes]:
    path = _resolve_lang_file("items", lang_code, ITEMS_FILE)
    return _get_cached_gzip(_items_cache_by_lang, path, lang_code, _items_lock, fallback_code="INT", force=force)


def _get_titles_cache_for_lang(lang_code: str, force: bool = False) -> tuple[bytes, bytes]:
    path = _resolve_lang_file("titles", lang_code, TITLES_FILE)
    return _get_cached_gzip(_titles_cache_by_lang, path, lang_code, _titles_lock, fallback_code="INT", force=force)


def _get_v2_titles_cache_for_lang(lang_code: str, force: bool = False) -> tuple[bytes, bytes]:
    file_path = _resolve_lang_file("titles", lang_code, TITLES_FILE)
    try:
        mtime = file_path.stat().st_mtime
    except OSError:
        mtime = 0.0

    entry = _v2_titles_by_lang.get(lang_code)
    if not force and entry and mtime == entry[2] and mtime != 0.0:
        return entry[0], entry[1]

    with _titles_lock:
        entry = _v2_titles_by_lang.get(lang_code)
        try:
            mtime = file_path.stat().st_mtime
        except OSError:
            mtime = 0.0

        if not force and entry and mtime == entry[2] and mtime != 0.0:
            return entry[0], entry[1]

        if file_path.exists() and mtime != 0.0:
            loaded = json.loads(file_path.read_text(encoding="utf-8"))
        else:
            loaded = _load_titles()

        titles_list = loaded.get("titles", [])
        v2_payload = {
            "meta": {
                "returned": len(titles_list),
                "total_filtered": len(titles_list),
                "total_titles": len(titles_list),
                "limit": 0,
                "offset": 0,
            },
            "titles": titles_list,
            "categories": loaded.get("categories", []),
        }
        v2_raw = json.dumps(v2_payload).encode("utf-8")
        v2_gz = gzip.compress(v2_raw, compresslevel=9)
        _v2_titles_by_lang[lang_code] = (v2_raw, v2_gz, mtime)
        return v2_raw, v2_gz


def _load_items() -> dict[str, Any]:
    global _data_cache, _cache_mtime, _items_by_id
    try:
        mtime = ITEMS_FILE.stat().st_mtime
    except FileNotFoundError:
        mtime = 0.0

    if _data_cache is not None and mtime == _cache_mtime and mtime != 0.0:
        return _data_cache

    with _reload_lock:
        try:
            mtime = ITEMS_FILE.stat().st_mtime
        except FileNotFoundError:
            mtime = 0.0

        if _data_cache is not None and mtime == _cache_mtime and mtime != 0.0:
            return _data_cache

        if mtime == 0.0 or not ITEMS_FILE.exists():
            data = generate(ITEMS_FILE)
            mtime = ITEMS_FILE.stat().st_mtime
        else:
            data = json.loads(ITEMS_FILE.read_text(encoding="utf-8"))

        if "items" not in data and "Items" in data:
            data["items"] = data["Items"]

        items_map = {}
        for itm in data.get("items", []):
            item_id = itm.get("id") if itm.get("id") is not None else itm.get("ID")
            if item_id is not None:
                items_map[str(item_id).strip().lower()] = itm

        _items_by_id = items_map
        _data_cache = data
        _cache_mtime = mtime
        return _data_cache


def _load_titles() -> dict[str, Any]:
    global _titles_cache, _titles_cache_mtime, _titles_by_id, _titles_by_text
    try:
        mtime = TITLES_FILE.stat().st_mtime
    except FileNotFoundError:
        mtime = 0.0

    if _titles_cache is not None and mtime == _titles_cache_mtime:
        return _titles_cache

    with _titles_reload_lock:
        try:
            mtime = TITLES_FILE.stat().st_mtime
        except FileNotFoundError:
            mtime = 0.0

        if _titles_cache is not None and mtime == _titles_cache_mtime:
            return _titles_cache

        if not TITLES_FILE.exists():
            _titles_by_id = {}
            _titles_by_text = {}
            return {"source": "PlayerTitleConfig", "category_count": 0, "title_count": 0, "categories": [], "titles": []}

        loaded = json.loads(TITLES_FILE.read_text(encoding="utf-8"))
        by_id = {}
        by_text = {}
        for title in loaded.get("titles", []):
            if "id" in title and title["id"]:
                by_id[str(title["id"]).strip().lower()] = title
            if "text" in title and title["text"]:
                by_text[str(title["text"]).strip().lower()] = title

        _titles_by_id = by_id
        _titles_by_text = by_text
        _titles_cache = loaded
        _titles_cache_mtime = mtime
        return _titles_cache


_existing_thumbnails_cache: set[str] | None = None
_thumbnails_mtime: float = 0.0


def _get_existing_thumbnails() -> set[str]:
    global _existing_thumbnails_cache, _thumbnails_mtime
    try:
        mtime = THUMBNAILS_DIR.stat().st_mtime
    except FileNotFoundError:
        mtime = 0.0
    if _existing_thumbnails_cache is not None and mtime == _thumbnails_mtime:
        return _existing_thumbnails_cache
    try:
        _existing_thumbnails_cache = {f.name.lower() for f in os.scandir(THUMBNAILS_DIR)}
        _thumbnails_mtime = mtime
    except OSError:
        _existing_thumbnails_cache = set()
    return _existing_thumbnails_cache


def _thumbnail_url(item: dict[str, Any]) -> str | None:
    existing = _get_existing_thumbnails()
    if not existing:
        return None

    pkg = (item.get("AssetPackage") or item.get("asset_package") or item.get("internal_name") or "").strip()
    if pkg:
        stem = pkg.lower()
        for sfx in (".upk", "_sf"):
            if stem.endswith(sfx):
                stem = stem[:-len(sfx)]
        for cand in (f"{stem}_t.png", f"{stem}.png"):
            if cand in existing:
                return f"/thumbnails/{cand}"
    return None


def format_product(item: dict[str, Any], lang_key: str, full: bool = False) -> dict[str, Any]:
    exclude = {"thumbnail_asset", "thumbnail_package", "thumbnail_base64"}
    if not full:
        exclude.add("translations")
    formatted = {k: v for k, v in item.items() if k not in exclude}

    item_id = item.get("id") if item.get("id") is not None else item.get("ID")
    raw_name = item.get("name") or item.get("label") or item.get("Product") or ""
    category = item.get("category") or item.get("slot") or item.get("Slot") or ""
    internal_name = item.get("internal_name") or item.get("asset_package") or item.get("AssetPackage") or ""
    quality_raw = item.get("quality_label") or item.get("quality") or item.get("Quality") or ""

    translations = item.get("translations", {})
    localized_name = translations.get(lang_key) or translations.get(lang_key.lower()) or raw_name

    formatted["id"] = item_id
    formatted["name"] = localized_name
    if "Product" in formatted or "Product" in item:
        formatted["Product"] = localized_name
    formatted["category"] = category
    formatted["internal_name"] = internal_name
    formatted["quality"] = _QUALITY_NORMALIZE.get(quality_raw, quality_raw)
    formatted["thumbnail_url"] = _thumbnail_url(item)

    return formatted


class RateLimiterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, requests_per_minute: int = 300):
        super().__init__(app)
        self.rpm = requests_per_minute
        self.hits = defaultdict(list)
        self.lock = threading.Lock()

    async def dispatch(self, request: Request, call_next):
        if request.url.path in ("/health", "/"):
            return await call_next(request)

        ip = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for") or (request.client.host if request.client else "127.0.0.1")
        ip = ip.split(",")[0].strip()

        now = time.time()
        with self.lock:
            window = [t for t in self.hits[ip] if now - t < 60]
            if len(window) >= self.rpm:
                return Response(
                    content=json.dumps({"detail": "Rate limit exceeded"}),
                    status_code=429,
                    media_type="application/json"
                )
            window.append(now)
            self.hits[ip] = window

        return await call_next(request)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _load_items()
    _load_titles()
    _get_items_cache_for_lang("INT")
    _get_titles_cache_for_lang("INT")
    _get_v2_titles_cache_for_lang("INT")

    update_task = asyncio.create_task(hourly_sync_worker())
    yield
    update_task.cancel()


app = FastAPI(
    title="OpenRLApi",
    version="2.0.0",
    description="Rocket League metadata, localized catalogs, player titles, and thumbnail API",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimiterMiddleware, requests_per_minute=RATE_LIMIT_PER_MINUTE)

if THUMBNAILS_DIR.exists():
    app.mount("/thumbnails", StaticFiles(directory=str(THUMBNAILS_DIR)), name="thumbnails")


@app.get("/", include_in_schema=False)
def root():
    return {"name": "OpenRLApi", "version": "2.0.0", "status": "online", "docs": "/docs"}


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health():
    data = _load_items()
    titles = _load_titles()
    ver = ITEMS_VER_FILE.read_text(encoding="utf-8").strip() if ITEMS_VER_FILE.exists() else "unknown"
    return {
        "status": "ok",
        "version": ver,
        "items_count": len(data.get("items", [])),
        "titles_count": len(titles.get("titles", [])),
        "languages_supported": len(ALL_LANGUAGES),
    }


@app.get("/items.ver", response_class=PlainTextResponse, tags=["Items"])
@app.head("/items.ver", include_in_schema=False)
def get_items_version():
    if ITEMS_VER_FILE.exists():
        try:
            return ITEMS_VER_FILE.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    return "260825.79374.526531"


@app.get("/items.json", tags=["Items"])
@app.head("/items.json", include_in_schema=False)
@app.get("/v2/rl/items.json", tags=["Items"])
@app.head("/v2/rl/items.json", include_in_schema=False)
async def get_items_catalog(
    request: Request,
    l: str | None = Query(None),
    lang: str | None = Query(None),
):
    target_lang = resolve_lang(l or lang)
    raw_bytes, gz_bytes = _get_items_cache_for_lang(target_lang)

    is_head = request.method == "HEAD"
    supports_gzip = client_accepts_gzip(request)

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "public, max-age=86400, s-maxage=604800",
        "Vary": "Accept-Encoding",
        "Access-Control-Allow-Origin": "*",
    }

    if supports_gzip and gz_bytes:
        headers["Content-Encoding"] = "gzip"
        headers["Content-Length"] = str(len(gz_bytes))
        body = b"" if is_head else gz_bytes
    else:
        headers["Content-Length"] = str(len(raw_bytes))
        body = b"" if is_head else raw_bytes

    return Response(content=body, status_code=200, headers=headers, media_type="application/json")


@app.get("/v2/rl/products", response_model=ProductsListResponse, tags=["Products"])
def get_products(
    category: str | None = Query(None),
    search: str | None = Query(None),
    l: str | None = Query(None),
    lang: str | None = Query(None),
    limit: int | None = Query(50, ge=1, le=250),
    offset: int = Query(0, ge=0),
    full: bool = Query(False),
    all: bool = Query(False),
):
    data = _load_items()
    items = data.get("items", [])
    lang_key = resolve_lang(l or lang)

    if category:
        cat_lower = category.lower()
        items = [i for i in items if (i.get("category_id") or i.get("slot") or i.get("Slot") or "").lower() == cat_lower]

    if search:
        q = search.lower()
        def _matches(itm: dict) -> bool:
            trans = itm.get("translations", {})
            loc_n = trans.get(lang_key) or trans.get(lang_key.lower()) or ""
            if q in loc_n.lower():
                return True
            default_n = itm.get("Product") or itm.get("name") or itm.get("label") or ""
            if q in default_n.lower():
                return True
            pkg = itm.get("AssetPackage") or itm.get("asset_package") or itm.get("internal_name") or ""
            if q in pkg.lower():
                return True
            for tr_val in trans.values():
                if isinstance(tr_val, str) and q in tr_val.lower():
                    return True
            return False

        items = [i for i in items if _matches(i)]

    total = len(items)
    if all:
        used_limit = total
        offset = 0
    else:
        used_limit = limit or 50
        if offset:
            items = items[offset:]
        if used_limit:
            items = items[:used_limit]

    return {
        "meta": {
            "returned": len(items),
            "total_filtered": total,
            "limit": used_limit,
            "offset": offset,
        },
        "products": [format_product(i, lang_key, full=full) for i in items],
    }


@app.get("/v2/rl/products/{product_id}", response_model=ProductResponse, tags=["Products"])
def get_product(
    product_id: str,
    l: str | None = Query(None),
    lang: str | None = Query(None),
    full: bool = Query(False),
):
    _load_items()
    lang_key = resolve_lang(l or lang)
    pid = product_id.strip().lower()
    item = _items_by_id.get(pid)
    if item is not None:
        return format_product(item, lang_key, full=full)
    raise HTTPException(status_code=404, detail=f"Product '{product_id}' not found")


@app.get("/titles.json", tags=["Titles"])
@app.head("/titles.json", include_in_schema=False)
@app.get("/v2/rl/titles.json", tags=["Titles"])
@app.head("/v2/rl/titles.json", include_in_schema=False)
async def get_titles_catalog(
    request: Request,
    l: str | None = Query(None),
    lang: str | None = Query(None),
):
    target_lang = resolve_lang(l or lang)
    raw_bytes, gz_bytes = _get_titles_cache_for_lang(target_lang)

    is_head = request.method == "HEAD"
    supports_gzip = client_accepts_gzip(request)

    headers = {
        "Content-Type": "application/json",
        "Cache-Control": "public, max-age=86400, s-maxage=604800",
        "Vary": "Accept-Encoding",
        "Access-Control-Allow-Origin": "*",
    }

    if supports_gzip and gz_bytes:
        headers["Content-Encoding"] = "gzip"
        headers["Content-Length"] = str(len(gz_bytes))
        body = b"" if is_head else gz_bytes
    else:
        headers["Content-Length"] = str(len(raw_bytes))
        body = b"" if is_head else raw_bytes

    return Response(content=body, status_code=200, headers=headers, media_type="application/json")


@app.get("/v2/rl/titles", tags=["Titles"])
@app.head("/v2/rl/titles", include_in_schema=False)
def get_titles(
    request: Request,
    category: str | None = Query(None),
    search: str | None = Query(None),
    has_glow: bool | None = Query(None),
    has_color: bool | None = Query(None),
    l: str | None = Query(None),
    lang: str | None = Query(None),
    limit: int = Query(0, ge=0),
    offset: int = Query(0, ge=0),
    full: bool = Query(False),
):
    lang_code = resolve_lang(l or lang)

    # Fast-path for unfiltered query
    if not category and not search and has_glow is None and has_color is None and not limit and not offset and not full:
        v2_raw, v2_gz = _get_v2_titles_cache_for_lang(lang_code)
        is_head = request.method == "HEAD"
        supports_gzip = client_accepts_gzip(request)
        headers = {
            "Content-Type": "application/json",
            "Cache-Control": "public, max-age=86400, s-maxage=604800",
            "Vary": "Accept-Encoding",
            "Access-Control-Allow-Origin": "*",
        }
        if supports_gzip and v2_gz:
            headers["Content-Encoding"] = "gzip"
            headers["Content-Length"] = str(len(v2_gz))
            return Response(content=b"" if is_head else v2_gz, status_code=200, headers=headers, media_type="application/json")
        elif v2_raw:
            headers["Content-Length"] = str(len(v2_raw))
            return Response(content=b"" if is_head else v2_raw, status_code=200, headers=headers, media_type="application/json")

    data = _load_titles()
    raw_titles = data.get("titles", [])

    titles = []
    for t in raw_titles:
        tr_text = (
            t.get("translations", {}).get(lang_code)
            or t.get("translations", {}).get(lang_code.lower())
            or t.get("text", "")
        )
        item_copy = {k: v for k, v in t.items() if full or k != "translations"}
        item_copy["text"] = tr_text
        titles.append(item_copy)

    if category:
        cat_lower = category.strip().lower()
        titles = [t for t in titles if (t.get("category") or "").strip().lower() == cat_lower]

    if search:
        q = search.strip().lower()
        titles = [t for t in titles if q in (t.get("text") or "").lower() or q in (t.get("id") or "").lower()]

    if has_glow is not None:
        titles = [t for t in titles if bool(t.get("glow")) == has_glow]

    if has_color is not None:
        titles = [t for t in titles if bool(t.get("color")) == has_color]

    total = len(titles)
    if offset:
        titles = titles[offset:]
    if limit:
        titles = titles[:limit]

    return {
        "meta": {
            "returned": len(titles),
            "total_filtered": total,
            "total_titles": len(data.get("titles", [])),
            "limit": limit,
            "offset": offset,
        },
        "titles": titles,
    }


@app.get("/v2/rl/titles/categories", tags=["Titles"])
def get_title_categories():
    data = _load_titles()
    return {
        "category_count": len(data.get("categories", [])),
        "categories": data.get("categories", []),
    }


@app.get("/v2/rl/titles/{title_id}", tags=["Titles"])
def get_title(
    title_id: str,
    l: str | None = Query(None),
    lang: str | None = Query(None),
    full: bool = Query(False),
):
    _load_titles()
    lang_code = resolve_lang(l or lang)
    tid = title_id.strip().lower()
    title = _titles_by_id.get(tid) or _titles_by_text.get(tid)
    if title is not None:
        tr_text = (
            title.get("translations", {}).get(lang_code)
            or title.get("translations", {}).get(lang_code.lower())
            or title.get("text", "")
        )
        res = {k: v for k, v in title.items() if full or k != "translations"}
        res["text"] = tr_text
        return res
    raise HTTPException(status_code=404, detail=f"Title '{title_id}' not found")


@app.get("/v2/rl/categories", tags=["Metadata"])
def get_categories():
    data = _load_items()
    counts: dict[str, int] = defaultdict(int)
    for i in data.get("items", []):
        slot = i.get("slot") or i.get("category_id") or i.get("Slot") or "Unknown"
        counts[slot] += 1
    return {"categories": dict(sorted(counts.items()))}


@app.get("/v2/rl/attributes", tags=["Metadata"])
def get_attributes():
    from .extractor import PAINTS, CERTIFICATIONS
    return {
        "paints": PAINTS,
        "certifications": CERTIFICATIONS,
    }


@app.post("/v2/rl/refresh", tags=["Admin"])
def refresh_catalog():
    data = generate(ITEMS_FILE)
    _load_items()
    _get_items_cache_for_lang("INT", force=True)
    return {"status": "ok", "items_count": len(data.get("items", []))}
