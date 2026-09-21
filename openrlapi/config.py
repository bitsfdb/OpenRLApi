import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.getenv("OPENRL_DATA_DIR", PROJECT_ROOT / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)

CACHE_DIR = Path(os.getenv("OPENRL_CACHE_DIR", PROJECT_ROOT / ".cache"))
CACHE_DIR.mkdir(parents=True, exist_ok=True)

THUMBNAILS_DIR = Path(os.getenv("OPENRL_THUMBNAILS_DIR", PROJECT_ROOT / "thumbnails"))
THUMBNAILS_DIR.mkdir(parents=True, exist_ok=True)

GAMES_DIR = Path(os.getenv("OPENRL_GAMES_DIR", PROJECT_ROOT / "games"))

ITEMS_FILE = DATA_DIR / "items.json"
TITLES_FILE = DATA_DIR / "titles.json"
ITEMS_VER_FILE = DATA_DIR / "items.ver"
SYNC_MANIFEST_FILE = DATA_DIR / "sync_manifest.json"

HOST = os.getenv("OPENRL_HOST", "0.0.0.0")
PORT = int(os.getenv("OPENRL_PORT", "8000"))
WORKERS = int(os.getenv("OPENRL_WORKERS", "1"))
RATE_LIMIT_PER_MINUTE = int(os.getenv("OPENRL_RATE_LIMIT", "300"))
CORS_ORIGINS = [orig.strip() for orig in os.getenv("OPENRL_CORS_ORIGINS", "*").split(",") if orig.strip()]

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")
ENABLE_REDIS = os.getenv("OPENRL_ENABLE_REDIS", "false").lower() in ("true", "1", "yes")

COALESCED_AES_KEY_STATIC = "14wySpRClDxtZc6YgYVMQWiZIgzHoUZAk5uWPJMqb68="
COALESCED_AES_KEY_B64 = os.getenv("COALESCED_AES_KEY", COALESCED_AES_KEY_STATIC)
COALESCED_AES_KEY = COALESCED_AES_KEY_B64
DEFAULT_PSYNET_BUILD_ID = os.getenv("DEFAULT_PSYNET_BUILD_ID", "-1887694083")
DEFAULT_GAME_VERSION = os.getenv("DEFAULT_GAME_VERSION", "260825.79374.526531")
EPIC_APP_NAME = os.getenv("EPIC_APP_NAME", "Sugar")

ALL_LANGUAGES = [
    "INT", "DEU", "DUT", "ESN", "FRA", "ITA", "JPN", "KOR", "POL", "PTB", "RUS", "TRK"
]

LANGUAGE_ALIASES = {
    "int": "INT", "en": "INT", "eng": "INT", "english": "INT",
    "deu": "DEU", "de": "DEU", "ger": "DEU", "german": "DEU",
    "dut": "DUT", "nl": "DUT", "nld": "DUT", "dutch": "DUT",
    "esn": "ESN", "es": "ESN", "spa": "ESN", "spanish": "ESN",
    "fra": "FRA", "fr": "FRA", "fre": "FRA", "french": "FRA",
    "ita": "ITA", "it": "ITA", "italian": "ITA",
    "jpn": "JPN", "ja": "JPN", "jp": "JPN", "japanese": "JPN",
    "kor": "KOR", "ko": "KOR", "kr": "KOR", "korean": "KOR",
    "pol": "POL", "pl": "POL", "polish": "POL",
    "ptb": "PTB", "por": "PTB", "pt": "PTB", "br": "PTB", "portuguese": "PTB",
    "rus": "RUS", "ru": "RUS", "russian": "RUS",
    "trk": "TRK", "tur": "TRK", "tr": "TRK", "turkish": "TRK",
}

def resolve_language_code(code: str | None) -> str:
    if not code:
        return "INT"
    return LANGUAGE_ALIASES.get(code.strip().lower(), "INT")

resolve_lang = resolve_language_code
