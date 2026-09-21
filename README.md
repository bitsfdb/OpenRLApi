# OpenRLApi

A standalone, high-performance, open-source Rocket League metadata, localized item catalog, player title, and asset API.

OpenRLApi is used by the [VelocityRL](https://github.com/bitsfdb/VelocityRL) project to power item catalogs, paint finishes, certifications, player titles, and asset previews.

OpenRLApi extracts game data directly from cooked Unreal Engine UPK packages and decrypted Coalesced binary files, synchronizes player title definitions and colors from Psyonix's PsyNet services, and serves them over an asynchronous HTTP API with zero-copy in-memory gzip caching (<1ms response times).

---

## Table of Contents

- [Features](#features)
- [Interactive Demo](#interactive-demo)
  - [Live Demo](#live-demo)
  - [Local Demo Quickstart](#local-demo-quickstart)
  - [Quick Interactive Examples](#quick-interactive-examples)
  - [Python & Node.js Demo Clients](#python--nodejs-demo-clients)
- [Rate Limiting](#rate-limiting)
- [Language Localization](#language-localization)
- [API Reference](#api-reference)
  - [Health & Diagnostics](#health--diagnostics)
  - [Catalogs](#catalogs)
  - [Products & Items](#products--items)
  - [Player Titles](#player-titles)
  - [Metadata & Attributes](#metadata--attributes)
  - [Thumbnails & Static Assets](#thumbnails--static-assets)
  - [Catalog Management](#catalog-management)
- [Configuration & Environment Variables](#configuration--environment-variables)
- [CLI Reference](#cli-reference)
- [Data Extraction & Update Pipeline](#data-extraction--update-pipeline)
- [Testing](#testing)
- [License](#license)

---

## Features

- **Game Extraction Engine**: Directly parses items, qualities, slots, paint finishes, and archetypes from `TAGame.upk` and decrypted `Coalesced_*.bin` archives.
- **12 Supported Languages**: Full localization for `INT` (English), `DEU` (German), `DUT` (Dutch), `ESN` (Spanish), `FRA` (French), `ITA` (Italian), `JPN` (Japanese), `KOR` (Korean), `POL` (Polish), `PTB` (Portuguese-Brazil), `RUS` (Russian), and `TRK` (Turkish).
- **Sub-Millisecond In-Memory Gzip**: Pre-compressed Level-9 gzip buffers served straight from memory with zero copy overhead.
- **PsyNet Synchronization**: Syncs all player titles, glow effects, and hex color codes directly from Psyonix PsyNet backend services.
- **Thumbnail Pipeline**: Automated batch texture extraction and normalization from `_T_SF.upk` packages into optimized PNG renders via umodel.
- **Preserving Auto-Updater**: Syncs binary updates from Epic Games CDN manifests and detects `GPsyonixBuildID` from PE headers without re-downloading or overwriting existing game files.

---

## Interactive Demo

### Live Demo

You can try out OpenRLApi immediately on the public demo instance:

- **Base URL**: `https://api.velocityrl.tech`
- **Interactive Swagger UI**: `https://api.velocityrl.tech/docs`
- **ReDoc Documentation**: `https://api.velocityrl.tech/redoc`
- **Health Endpoint**: `https://api.velocityrl.tech/health`

### Local Demo Quickstart

You can also launch a self-contained demo locally in seconds using Docker or Python:

#### Option A: Docker Compose (Recommended)
```bash
git clone https://github.com/bitsfdb/OpenRLApi.git
cd OpenRLApi
docker compose up -d
```
The API and documentation UI will be available at `http://localhost:8000/docs`.

#### Option B: Local Python Environment
```bash
git clone https://github.com/bitsfdb/OpenRLApi.git
cd OpenRLApi

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .

openrlapi serve --host 127.0.0.1 --port 8000
```
Open `http://127.0.0.1:8000/docs` in your browser to explore every endpoint interactively.

---

### Quick Interactive Examples

#### 1. Check API Status & Data Counts
```bash
curl -s "https://api.velocityrl.tech/health"
```
*Response:*
```json
{
  "status": "ok",
  "version": "260825.79374.526531",
  "items_count": 9295,
  "titles_count": 1420,
  "languages_supported": 12
}
```

#### 2. Query Item Details in Spanish (e.g., Goldstone Wheels ID 358)
```bash
curl -s "https://api.velocityrl.tech/v2/rl/products/358?l=ESN"
```
*Response:*
```json
{
  "id": 358,
  "name": "Venturina (Premio Alfa)",
  "category": "Wheels",
  "quality": "Limited",
  "internal_name": "wheel_goldstone",
  "thumbnail_url": "/thumbnails/wheel_goldstone_t.png"
}
```

#### 3. Search Products with Pagination
```bash
curl -s "https://api.velocityrl.tech/v2/rl/products?search=Octane&category=Body&limit=2"
```

#### 4. Query Player Titles with Glow & Custom Colors
```bash
curl -s "https://api.velocityrl.tech/v2/rl/titles/CRL_Analyst?l=ESN"
```
*Response:*
```json
{
  "id": "CRL_Analyst",
  "text": "Analista CRL",
  "category": "Esports",
  "color": "#00d9ff",
  "glow": "#0055ff"
}
```

#### 5. Download Pre-Compressed Master Catalog with Gzip
```bash
curl -s "https://api.velocityrl.tech/items.json?l=INT" \
  -H "Accept-Encoding: gzip" \
  --output items_INT.json.gz
```

---

### Python & Node.js Demo Clients

#### Python Demo (`demo.py`)
```python
import requests

BASE_URL = "https://api.velocityrl.tech"

# 1. Health check
health = requests.get(f"{BASE_URL}/health").json()
print(f"API Online! Version: {health['version']}, Items: {health['items_count']}")

# 2. Search items in French
params = {"search": "Fennec", "limit": 3, "l": "FRA"}
products = requests.get(f"{BASE_URL}/v2/rl/products", params=params).json()
for prod in products["products"]:
    print(f"[{prod['id']}] {prod['name']} ({prod['quality']} {prod['category']})")

# 3. Lookup Player Title in German
title = requests.get(f"{BASE_URL}/v2/rl/titles/Grand_Champion?l=DEU").json()
print(f"Title: {title['text']} | Color: {title.get('color')}")
```

#### Node.js / JavaScript Demo (`demo.mjs`)
```javascript
const BASE_URL = "https://api.velocityrl.tech";

async function runDemo() {
  // Check health
  const healthRes = await fetch(`${BASE_URL}/health`);
  const health = await healthRes.json();
  console.log(`OpenRLApi version: ${health.version}, Items: ${health.items_count}`);

  // Fetch product in Japanese
  const itemRes = await fetch(`${BASE_URL}/v2/rl/products/358?l=JPN`);
  const item = await itemRes.json();
  console.log(`Item #358 in Japanese: ${item.name} (${item.quality})`);
}

runDemo();
```

---

## Rate Limiting

To maintain high availability and prevent resource exhaustion, OpenRLApi enforces client IP rate limiting through an integrated sliding-window middleware (`RateLimiterMiddleware`).

### Rate Limit Specification

| Parameter | Value | Details |
| :--- | :--- | :--- |
| **Default Threshold** | `300 requests / minute` | Configurable per instance via `OPENRL_RATE_LIMIT` |
| **Sliding Window** | `60 seconds` | Tracked dynamically in memory per IP |
| **Exempt Endpoints** | `/`, `/health` | Health checks and root probes bypass limits |
| **IP Detection** | `CF-Connecting-IP` &rarr; `X-Forwarded-For` &rarr; Client Socket | Correctly resolves client IPs behind Cloudflare and reverse proxies |

### HTTP 429 Response Format

When a client IP exceeds the allowed threshold within the 60-second sliding window, the API immediately returns HTTP status code `429 Too Many Requests`:

```http
HTTP/1.1 429 Too Many Requests
Content-Type: application/json

{
  "detail": "Rate limit exceeded"
}
```

### Best Practices for API Consumers

1. **Use HTTP Compression**: Always supply `Accept-Encoding: gzip` when fetching `/items.json` or `/titles.json`. Master catalogs are served as pre-compressed Level-9 gzip payloads straight from memory.
2. **Respect Cache Headers**: Catalogs include `Cache-Control: public, max-age=86400, s-maxage=604800` headers. Cache responses locally to avoid unnecessary round-trips.
3. **Check Version Manifest**: Poll `/items.ver` (a lightweight string such as `260825.79374.526531`) before deciding to invalidate and re-download full catalog dumps.
4. **Use Targeted Endpoints**: Use `/v2/rl/products/{id}` or paginated queries (`/v2/rl/products?search=...&limit=25`) rather than downloading the entire multi-megabyte catalog for single lookups.

---

## Language Localization

OpenRLApi provides native localization across 12 languages. The language can be specified on any item or title endpoint via the `?l=` or `?lang=` query parameter.

| Code | Language | Supported Aliases |
| :---: | :--- | :--- |
| `INT` | English (International / Default) | `int`, `en`, `eng`, `english` |
| `DEU` | German (*Deutsch*) | `deu`, `de`, `ger`, `german` |
| `DUT` | Dutch (*Nederlands*) | `dut`, `nl`, `nld`, `dutch` |
| `ESN` | Spanish (*Español*) | `esn`, `es`, `spa`, `spanish` |
| `FRA` | French (*Français*) | `fra`, `fr`, `fre`, `french` |
| `ITA` | Italian (*Italiano*) | `ita`, `it`, `italian` |
| `JPN` | Japanese (*日本語*) | `jpn`, `ja`, `jp`, `japanese` |
| `KOR` | Korean (*한국어*) | `kor`, `ko`, `kr`, `korean` |
| `POL` | Polish (*Polski*) | `pol`, `pl`, `polish` |
| `PTB` | Portuguese - Brazil (*Português*) | `ptb`, `por`, `pt`, `br`, `portuguese` |
| `RUS` | Russian (*Русский*) | `rus`, `ru`, `russian` |
| `TRK` | Turkish (*Türkçe*) | `trk`, `tur`, `tr`, `turkish` |

*Note: If an unrecognized code is passed, the API safely defaults to `INT` (English).*

---

## API Reference

### Health & Diagnostics

#### `GET /health`
Returns service status, catalog item counts, title counts, and build version.
- **Tags**: Health
- **Rate Limited**: No
- **Response `200 OK`**:
```json
{
  "status": "ok",
  "version": "260825.79374.526531",
  "items_count": 9295,
  "titles_count": 1420,
  "languages_supported": 12
}
```

#### `GET /items.ver`
Returns the current items manifest version string.
- **Tags**: Items
- **Rate Limited**: Yes (300 rpm)
- **Response `200 OK`** (`text/plain`):
```text
260825.79374.526531
```

---

### Catalogs

#### `GET /items.json` / `GET /v2/rl/items.json`
Returns the complete Rocket League item catalog in the specified language.
- **Tags**: Items
- **Query Parameters**:
  - `l` / `lang` *(optional, string)*: Language code or alias (e.g. `ESN`, `PL`, `FRA`). Defaults to `INT`.
- **Headers Handled**:
  - `Accept-Encoding: gzip`: Serves pre-compressed Level-9 gzip bytes directly from RAM.
- **Response `200 OK`**: Master catalog payload containing `items`, `slots`, and metadata.

#### `GET /titles.json` / `GET /v2/rl/titles.json`
Returns the complete PsyNet player title catalog.
- **Tags**: Titles
- **Query Parameters**:
  - `l` / `lang` *(optional, string)*: Language code or alias. Defaults to `INT`.
- **Headers Handled**:
  - `Accept-Encoding: gzip`: Serves pre-compressed gzip bytes directly from RAM.
- **Response `200 OK`**: Titles catalog including categories and player title items.

---

### Products & Items

#### `GET /v2/rl/products`
Paginated, searchable product list with category filters and localization.
- **Tags**: Products
- **Query Parameters**:
  - `category` *(optional, string)*: Filter by slot or category (e.g., `Wheels`, `Body`, `Decal`, `Boost`, `Goal Explosion`).
  - `search` *(optional, string)*: Text search matching product names, internal asset package names, or translations.
  - `l` / `lang` *(optional, string)*: Language code or alias.
  - `limit` *(optional, int)*: Page size (1 to 250, default `50`).
  - `offset` *(optional, int)*: Number of items to skip (default `0`).
  - `full` *(optional, bool)*: When `true`, includes full translation dictionary for all languages.
  - `all` *(optional, bool)*: When `true`, returns all matching items bypassing pagination.
- **Response `200 OK`**:
```json
{
  "meta": {
    "returned": 1,
    "total_filtered": 1,
    "limit": 50,
    "offset": 0
  },
  "products": [
    {
      "id": 358,
      "name": "(Alpha Reward) Goldstone",
      "category": "Wheels",
      "quality": "Limited",
      "internal_name": "wheel_goldstone",
      "thumbnail_url": "/thumbnails/wheel_goldstone_t.png"
    }
  ]
}
```

#### `GET /v2/rl/products/{product_id}`
Retrieves a single product by numeric item ID.
- **Tags**: Products
- **Path Parameters**:
  - `product_id` *(required, string/int)*: The unique item identifier (e.g., `358`, `23`).
- **Query Parameters**:
  - `l` / `lang` *(optional, string)*: Language code or alias.
  - `full` *(optional, bool)*: If `true`, includes raw translations mapping.
- **Response `200 OK`**: Product object.
- **Response `404 Not Found`**: Returned if product ID does not exist in catalog.

---

### Player Titles

#### `GET /v2/rl/titles`
Paginated PsyNet player titles with visual glow and color attributes.
- **Tags**: Titles
- **Query Parameters**:
  - `category` *(optional, string)*: Filter by title category (e.g., `Rank`, `Esports`, `Competitive`, `Special`).
  - `search` *(optional, string)*: Filter by title text or ID identifier.
  - `has_glow` *(optional, bool)*: Filter by whether the title has glow metadata.
  - `has_color` *(optional, bool)*: Filter by whether the title has custom hex coloring.
  - `l` / `lang` *(optional, string)*: Localization language.
  - `limit` *(optional, int)*: Result limit (default `0` returns all).
  - `offset` *(optional, int)*: Pagination offset.
  - `full` *(optional, bool)*: Include full translations object.
- **Response `200 OK`**:
```json
{
  "meta": {
    "returned": 1,
    "total_filtered": 1,
    "total_titles": 1420,
    "limit": 50,
    "offset": 0
  },
  "titles": [
    {
      "id": "CRL_Analyst",
      "text": "CRL Analyst",
      "category": "Esports",
      "color": "#00d9ff",
      "glow": "#0055ff"
    }
  ]
}
```

#### `GET /v2/rl/titles/{title_id}`
Lookup a single title by unique identifier or text name.
- **Tags**: Titles
- **Path Parameters**:
  - `title_id` *(required, string)*: Title ID (e.g. `CRL_Analyst`) or literal text.
- **Query Parameters**:
  - `l` / `lang` *(optional, string)*: Language code or alias.
  - `full` *(optional, bool)*: Include all translations.
- **Response `200 OK`**: Title object.
- **Response `404 Not Found`**: If title identifier is not found.

#### `GET /v2/rl/titles/categories`
List title categories and their configured styling defaults.
- **Tags**: Titles
- **Response `200 OK`**:
```json
{
  "category_count": 14,
  "categories": [
    {"id": "Rank", "label": "Rank Titles"},
    {"id": "Esports", "label": "Esports Titles"}
  ]
}
```

---

### Metadata & Attributes

#### `GET /v2/rl/categories`
Returns all unique item category slots and total item counts per category.
- **Tags**: Metadata
- **Response `200 OK`**:
```json
{
  "categories": {
    "Antenna": 1245,
    "Body": 156,
    "Decal": 3120,
    "Goal Explosion": 240,
    "Paint Finish": 85,
    "Player Banner": 890,
    "Player Title": 1420,
    "Rocket Boost": 710,
    "Topper": 1105,
    "Wheels": 1324
  }
}
```

#### `GET /v2/rl/attributes`
Returns Rocket League paint finishes and certifications dictionaries.
- **Tags**: Metadata
- **Response `200 OK`**:
```json
{
  "paints": {
    "0": "None",
    "1": "Crimson",
    "2": "Lime",
    "3": "Black",
    "4": "Cobalt",
    "5": "Flirtatious",
    "6": "Titanium White",
    "7": "Grey",
    "8": "Pink",
    "9": "Purple",
    "10": "Burnt Sienna",
    "11": "Forest Green",
    "12": "Sky Blue",
    "13": "Saffron",
    "14": "Gold"
  },
  "certifications": {
    "0": "None",
    "1": "Aviator",
    "2": "Juggler",
    "3": "Paragon",
    "4": "Playmaker",
    "5": "Scorer",
    "6": "Show-off",
    "7": "Sniper",
    "8": "Striker",
    "9": "Sweeper",
    "10": "Tactician",
    "11": "Turtle",
    "12": "Victor",
    "13": "Goalkeeper",
    "14": "Guardian"
  }
}
```

---

### Thumbnails & Static Assets

#### `GET /thumbnails/{file}.png`
Delivers high-resolution static PNG renders for item icons and previews.
- **Path Parameters**:
  - `file`: The thumbnail asset key (e.g. `wheel_goldstone_t.png`, `body_octane_t.png`).
- **Response `200 OK`**: Binary image PNG data with long-term client caching (`max-age=2592000`).

---

### Catalog Management

#### `POST /v2/rl/refresh`
Triggers an in-memory catalog refresh from local game files and invalidates gzip cache buffers.
- **Tags**: Admin
- **Response `200 OK`**: `{"status": "ok", "items_count": 9295}`

---

## Configuration & Environment Variables

OpenRLApi can be configured using environment variables or a `.env` file located in the project root:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `OPENRL_HOST` | `0.0.0.0` | Listen host interface |
| `OPENRL_PORT` | `8000` | Listen port |
| `OPENRL_WORKERS` | `1` | Uvicorn worker process count |
| `OPENRL_RATE_LIMIT` | `300` | Sliding window rate limit (requests per minute per IP) |
| `OPENRL_CORS_ORIGINS` | `*` | Comma-separated allowed CORS origin domains |
| `OPENRL_DATA_DIR` | `./data` | Directory containing JSON databases and `items.ver` |
| `OPENRL_THUMBNAILS_DIR`| `./thumbnails` | Directory containing extracted PNG item renders |
| `OPENRL_GAMES_DIR` | `./games` | Directory holding downloaded game manifests & UPK files |
| `COALESCED_AES_KEY` | *(256-bit AES)* | AES-256 base64 key used to decrypt Coalesced localization files |
| `DEFAULT_PSYNET_BUILD_ID`| `-1887694083`| Default build identifier for querying Psyonix PsyNet APIs |
| `DEFAULT_GAME_VERSION` | `260825.79374.526531` | Fallback version string when `items.ver` is missing |
| `EPIC_APP_NAME` | `Sugar` | Epic Games CDN catalog application identifier |

---

## CLI Reference

The `openrlapi` CLI provides commands for running the server, extracting game data, synchronizing titles, and updating binaries.

```bash
# Start the HTTP API server
openrlapi serve --host 0.0.0.0 --port 8000 --workers 4

# Extract items and translations from local game files
openrlapi extract --upk /path/to/TAGame.upk --coalesced /path/to/CookedPCConsole/ --out ./data/

# Synchronize player titles from PsyNet
openrlapi sync-titles --build-id -1887694083

# Extract thumbnail textures from UPKs using umodel
openrlapi extract-thumbs --cooked-dir /path/to/CookedPCConsole/ --out ./thumbnails/

# Run updater pipeline to check Epic CDN and sync manifests
openrlapi update --app Sugar
```

---

## Data Extraction & Update Pipeline

```
  Cooked Unreal Packages (TAGame.upk)
                   +
      Decrypted Coalesced_*.bin              PsyNet Title API
                   |                                |
                   v                                v
         openrlapi extract                openrlapi sync-titles
                   |                                |
                   +----------------+---------------+
                                    |
                                    v
                           Master Data Catalog
                      (data/items.json, titles.json)
                                    |
                                    v
                       In-Memory Gzip Buffer Cache
                         (<1ms Level-9 Delivery)
                                    |
                                    v
                        VelocityRL & Public Clients
```

1. **UPK Extraction**: Reads the serialized object table in `TAGame.upk` to identify all product definitions, slots, qualities, paint rules, and thumbnail asset pointers.
2. **Coalesced Decryption & Parsing**: Decrypts the game's localized binary strings for all 12 languages using the AES-256 key, mapping localized names to item IDs.
3. **PsyNet Sync**: Connects to Psyonix PsyNet services using the extracted `GPsyonixBuildID` to retrieve titles, categories, glow flags, and hex colors.
4. **Thumbnail Processing**: Uses `umodel` to unpack textures from `_T_SF.upk` packages into PNG thumbnails.
5. **Fast Delivery**: The API caches compressed JSON buffers in memory, serving large catalogs instantly to clients like VelocityRL with sub-millisecond overhead.

---

## Testing

Run the test suite using `pytest`:

```bash
pytest tests/
```

The test suite validates:
- API root and health diagnostic endpoints
- Multi-language catalog retrieval and localization resolution
- Single product retrieval and search filters
- Player title queries with glow/color metadata
- Category and attribute dictionary schemas

---

## License

Distributed under the [MIT License](LICENSE).

*Rocket League is a registered trademark of Psyonix LLC and Epic Games, Inc. OpenRLApi is an independent, community-driven open-source project and is not affiliated with, endorsed by, or sponsored by Psyonix LLC or Epic Games, Inc.*
