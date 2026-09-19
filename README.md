# OpenRLApi

A standalone, open-source Rocket League metadata, localized item catalog, player title, and asset API.

OpenRLApi extracts game data directly from cooked Unreal Engine UPK packages and decrypted Coalesced binary files, synchronizes player titles from Psyonix's PsyNet services, and serves them over an HTTP API with in-memory gzip caching.

## Features

- **Game extraction**: Parses items, qualities, slots, paint finishes, and archetypes directly from `TAGame.upk` and decrypted `Coalesced_*.bin`.
- **12 languages**: Localization support for `INT` (English), `DEU`, `DUT`, `ESN`, `FRA`, `ITA`, `JPN`, `KOR`, `POL`, `PTB`, `RUS`, `TRK` via the `?l=` parameter.
- **In-memory gzip delivery**: Pre-compressed catalog responses served directly from memory in <1ms.
- **PsyNet player titles**: Synchronizes player title definitions, categories, and hex colors from PsyNet.
- **Thumbnail pipeline**: Batch extracts and normalizes PNG renders from `_T_SF.upk` packages using umodel.
- **Preserving updater**: Downloads binary updates from Epic CDN manifests and syncs `items.ver` without deleting existing game files.

## Quickstart

### Docker

```bash
git clone https://github.com/bitsfdb/OpenRLApi.git
cd OpenRLApi
docker compose up -d
```

The API starts on `http://localhost:8000`.

### Local Setup

```bash
git clone https://github.com/bitsfdb/OpenRLApi.git
cd OpenRLApi

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -e .

openrlapi serve --port 8000
```

## API Endpoints

### Items & Products

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/items.json` | Master catalog in any language (`?l=ESN`, `?l=PL`, etc.) |
| `GET` | `/items.ver` | Current items manifest version string |
| `GET` | `/v2/rl/items.json` | Alias for `/items.json` |
| `GET` | `/v2/rl/products` | Paginated products with search and category filters |
| `GET` | `/v2/rl/products/{id}` | Single product by ID |
| `GET` | `/v2/rl/categories` | Product categories with counts |
| `GET` | `/v2/rl/attributes` | Paint finishes and certifications |
| `GET` | `/thumbnails/{file}.png` | Static item render thumbnail |

### Player Titles

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/titles.json` | Master player titles catalog |
| `GET` | `/v2/rl/titles` | Paginated player titles with glow and hex colors |
| `GET` | `/v2/rl/titles/{id}` | Single player title by ID or text |
| `GET` | `/v2/rl/titles/categories` | Title categories and default colors |

### Examples

```bash
# Query Spanish catalog with gzip
curl -s "http://localhost:8000/items.json?l=ESN" -H "Accept-Encoding: gzip"

# Lookup single item in Polish
curl -s "http://localhost:8000/v2/rl/products/358?l=PL"

# Search player titles in Spanish
curl -s "http://localhost:8000/v2/rl/titles/CRL_Analyst?l=ESN"
```

## CLI Usage

```bash
# Start server
openrlapi serve --port 8000 --workers 4

# Extract items from game files
openrlapi extract --upk /path/to/TAGame.upk --coalesced /path/to/CookedPCConsole/

# Sync player titles from PsyNet
openrlapi sync-titles

# Extract PNG thumbnails from UPKs
openrlapi extract-thumbs --cooked-dir /path/to/CookedPCConsole/ --out ./thumbnails/

# Run update pipeline
openrlapi update
```

## Configuration

Settings can be set via environment variables or a `.env` file:

| Variable | Default | Description |
| :--- | :--- | :--- |
| `OPENRL_HOST` | `0.0.0.0` | Bind host |
| `OPENRL_PORT` | `8000` | Bind port |
| `OPENRL_WORKERS` | `1` | Uvicorn worker count |
| `OPENRL_RATE_LIMIT` | `300` | Requests per minute per IP |
| `OPENRL_DATA_DIR` | `./data` | Directory for JSON databases |
| `OPENRL_THUMBNAILS_DIR` | `./thumbnails` | Directory for PNG thumbnails |
| `OPENRL_GAMES_DIR` | `./games` | Directory for downloaded game files |
| `COALESCED_AES_KEY` | `14wySp...` | AES-256 key for Coalesced files |

## Testing

```bash
pytest tests/
```

## License

MIT
