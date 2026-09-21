# OpenRLApi - Complete API Specification & Developer Guide

OpenRLApi is an open-source, high-performance Rocket League metadata, localized item catalog, player title, and asset API used by the [VelocityRL](https://github.com/bitsfdb/VelocityRL) project.

---

## 1. Overview & Architecture

OpenRLApi provides zero-copy, sub-millisecond retrieval of Rocket League items, categories, paint finishes, certifications, player titles, and thumbnail renders. It powers client applications such as VelocityRL by indexing:

1. **Unreal Engine Packages (`TAGame.upk`)**: Extracted product definitions, archetype classes, and slot associations.
2. **Decrypted Coalesced Binary Files (`Coalesced_*.bin`)**: 12 language localizations decrypted via AES-256.
3. **Psyonix PsyNet Services**: Live title definitions, categories, and custom hex glow styling.
4. **Thumbnail Assets**: High-resolution PNG renders extracted from `_T_SF.upk` textures.

---

## 2. Interactive Demo & Quickstart

### Public Live Demo
- **API Base URL**: `https://api.velocityrl.tech`
- **Interactive Swagger UI**: `https://api.velocityrl.tech/docs`
- **ReDoc Viewer**: `https://api.velocityrl.tech/redoc`

### Interactive Testing with cURL

```bash
# 1. Probe health & verify catalog counts
curl -s "https://api.velocityrl.tech/health"

# 2. Get manifest version string
curl -s "https://api.velocityrl.tech/items.ver"

# 3. Retrieve single product in Spanish (Goldstone Wheels, ID 358)
curl -s "https://api.velocityrl.tech/v2/rl/products/358?l=ESN"

# 4. Filter products by search and category
curl -s "https://api.velocityrl.tech/v2/rl/products?search=Octane&category=Body&limit=5"

# 5. Fetch single title with custom glow & hex colors
curl -s "https://api.velocityrl.tech/v2/rl/titles/CRL_Analyst?l=ESN"

# 6. Stream pre-compressed master catalog with Gzip (<1ms latency)
curl -s "https://api.velocityrl.tech/items.json?l=INT" \
  -H "Accept-Encoding: gzip" \
  --output catalog_INT.json.gz
```

---

## 3. API Rate Limiting

To guarantee uninterrupted service and protect system resources, all public API requests pass through the sliding-window `RateLimiterMiddleware`.

### Rate Limit Specification
- **Default Threshold**: 300 requests per minute per IP address.
- **Sliding Window**: 60 seconds rolling window.
- **Client IP Resolution**:
  1. `CF-Connecting-IP` (Cloudflare CDN header)
  2. `X-Forwarded-For` (Reverse proxy header, first IP in list)
  3. Client remote socket host
- **Exempt Routes**: `/` (Root ping) and `/health` (Health probe).
- **HTTP 429 Error Response**:
  ```json
  {
    "detail": "Rate limit exceeded"
  }
  ```

### Caching and Performance Best Practices
- **Enable Gzip**: Master catalogs (`/items.json`, `/titles.json`) are stored pre-compressed in RAM using gzip level 9. Always send `Accept-Encoding: gzip`.
- **Cache-Control**: Catalogs are tagged with `Cache-Control: public, max-age=86400, s-maxage=604800`.
- **Version Checking**: Inspect `/items.ver` before downloading the full catalog. If the version hash matches local cache, no re-download is needed.

---

## 4. Supported Languages & Localization

Use `?l=<CODE>` or `?lang=<CODE>` on any catalog, product, or title endpoint:

| Code | Language | Common Aliases |
| :---: | :--- | :--- |
| `INT` | English (Default) | `int`, `en`, `eng`, `english` |
| `DEU` | German | `deu`, `de`, `ger`, `german` |
| `DUT` | Dutch | `dut`, `nl`, `nld`, `dutch` |
| `ESN` | Spanish | `esn`, `es`, `spa`, `spanish` |
| `FRA` | French | `fra`, `fr`, `fre`, `french` |
| `ITA` | Italian | `ita`, `it`, `italian` |
| `JPN` | Japanese | `jpn`, `ja`, `jp`, `japanese` |
| `KOR` | Korean | `kor`, `ko`, `kr`, `korean` |
| `POL` | Polish | `pol`, `pl`, `polish` |
| `PTB` | Portuguese (Brazil) | `ptb`, `por`, `pt`, `br`, `portuguese` |
| `RUS` | Russian | `rus`, `ru`, `russian` |
| `TRK` | Turkish | `trk`, `tur`, `tr`, `turkish` |

---

## 5. Endpoints Reference

### Diagnostics

#### `GET /health`
- **Description**: Returns health status, uptime version, catalog item count, title count, and language count.
- **Rate Limited**: No.

#### `GET /items.ver`
- **Description**: Returns the active game version / manifest string (e.g. `260825.79374.526531`).
- **Rate Limited**: Yes.

### Catalogs

#### `GET /items.json` and `GET /v2/rl/items.json`
- **Description**: Master catalog with full item database for the specified language.
- **Query Parameters**:
  - `l` / `lang` *(string, optional)*: Language code.
- **Headers**:
  - `Accept-Encoding: gzip` returns compressed binary payload.

#### `GET /titles.json` and `GET /v2/rl/titles.json`
- **Description**: Master player titles catalog containing all PsyNet title records and categories.
- **Query Parameters**:
  - `l` / `lang` *(string, optional)*: Language code.

### Products & Items

#### `GET /v2/rl/products`
- **Description**: Query and search products with pagination.
- **Query Parameters**:
  - `search` *(string, optional)*: Text search matching product names, internal asset package names, or translations.
  - `category` *(string, optional)*: Filter by slot/category (e.g., `Wheels`, `Body`, `Decal`).
  - `limit` *(int, optional, 1-250, default: 50)*: Number of items per page.
  - `offset` *(int, optional, default: 0)*: Number of items to skip.
  - `l` / `lang` *(string, optional)*: Localization code.
  - `full` *(bool, optional, default: false)*: When `true`, includes all language translations.
  - `all` *(bool, optional, default: false)*: When `true`, bypasses pagination and returns all matches.

#### `GET /v2/rl/products/{product_id}`
- **Description**: Fetch single item metadata by numeric ID.
- **Path Parameters**:
  - `product_id` *(int/string, required)*: The item ID.
- **Query Parameters**:
  - `l` / `lang` *(string, optional)*: Language code.
  - `full` *(bool, optional)*: Include translation dictionary.

### Player Titles

#### `GET /v2/rl/titles`
- **Description**: Search and list PsyNet player titles.
- **Query Parameters**:
  - `category` *(string, optional)*: Filter by title category (e.g., `Rank`, `Esports`).
  - `search` *(string, optional)*: Search in title text or ID.
  - `has_glow` *(bool, optional)*: Filter titles having glow styling.
  - `has_color` *(bool, optional)*: Filter titles having custom hex colors.
  - `limit` *(int, optional)*: Pagination limit.
  - `offset` *(int, optional)*: Pagination offset.
  - `l` / `lang` *(string, optional)*: Language code.
  - `full` *(bool, optional)*: Include translation dictionary.

#### `GET /v2/rl/titles/{title_id}`
- **Description**: Fetch a single title by unique identifier or text string.
- **Path Parameters**:
  - `title_id` *(string, required)*: Title ID (e.g., `CRL_Analyst`, `Grand_Champion`).

#### `GET /v2/rl/titles/categories`
- **Description**: List all player title category definitions.

### Metadata & Thumbnails

#### `GET /v2/rl/categories`
- **Description**: Returns all item slots and total items in each category.

#### `GET /v2/rl/attributes`
- **Description**: Returns paint finishes and certification mapping tables.

#### `GET /thumbnails/{file}.png`
- **Description**: Static PNG renders for item icons. Cached for 30 days.

#### `POST /v2/rl/refresh`
- **Description**: Reloads data files and clears in-memory caches.

---

## 6. Configuration Reference

| Environment Variable | Default | Purpose |
| :--- | :--- | :--- |
| `OPENRL_HOST` | `0.0.0.0` | Host binding interface |
| `OPENRL_PORT` | `8000` | Port binding |
| `OPENRL_WORKERS` | `1` | Number of worker processes |
| `OPENRL_RATE_LIMIT` | `300` | Requests per minute per client IP |
| `OPENRL_CORS_ORIGINS` | `*` | Allowed CORS origins |
| `OPENRL_DATA_DIR` | `./data` | Path to data JSON files |
| `OPENRL_THUMBNAILS_DIR`| `./thumbnails` | Path to PNG thumbnails |
| `OPENRL_GAMES_DIR` | `./games` | Game manifests and UPK files |
| `COALESCED_AES_KEY` | `14wySp...` (Static) | Static AES-256 base64 key built into code; universal and identical across all game installations and platforms. |
| `DEFAULT_PSYNET_BUILD_ID`| `-1887694083` | Default build ID for PsyNet title requests |
| `DEFAULT_GAME_VERSION` | `260825.79374.526531` | Fallback version string |
