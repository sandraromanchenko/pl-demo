"""Env-driven config: every endpoint comes from the environment so one image
runs locally (compose service names) and on AWS (private IPs)."""
import os
from functools import lru_cache

# Model -> vector index. bge-small=TEI, others=Ollama.
MODEL_INDEXES = {
    "bge-small": "vec_bge_small",
    "nomic-embed-text": "vec_nomic",
    "bge-m3": "vec_bge_m3",
}


def enabled_models() -> list[str]:
    """Enabled models from EMBED_MODELS."""
    raw = os.environ.get("EMBED_MODELS", "bge-small")
    return [m.strip() for m in raw.split(",") if m.strip() in MODEL_INDEXES]


class Settings:
    def __init__(self):
        self.mongo_uri: str = os.environ.get(
            "MONGO_URI",
            "mongodb://root:root@mongod:27017/?authSource=admin&directConnection=true",
        )
        self.mongo_db: str = os.environ.get("MONGO_DB", "boardgames")
        self.mongo_collection: str = os.environ.get("MONGO_COLLECTION", "games")
        self.text_index: str = os.environ.get("TEXT_INDEX", "text_index")
        # Enabled model -> vector index name.
        self.vector_indexes: dict[str, str] = {m: MODEL_INDEXES[m] for m in enabled_models()}
        # First enabled model unless DEFAULT_MODEL is set and actually enabled.
        enabled = list(self.vector_indexes)
        requested = os.environ.get("DEFAULT_MODEL", "").strip()
        self.default_model: str = (
            requested if requested in self.vector_indexes else (enabled[0] if enabled else "bge-small")
        )
        # Full-text searched fields.
        self.text_fields: list[str] = ["name", "description", "categories", "mechanics"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
