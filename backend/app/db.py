"""MongoDB client wiring (directConnection: reach mongod regardless of the
replica set's container-local advertised hostname)."""
from functools import lru_cache

from pymongo import MongoClient
from pymongo.collection import Collection

from .config import get_settings


@lru_cache
def get_client() -> MongoClient:
    settings = get_settings()
    # Short timeout so /health fails fast instead of hanging.
    return MongoClient(settings.mongo_uri, serverSelectionTimeoutMS=5000)


def get_collection() -> Collection:
    settings = get_settings()
    return get_client()[settings.mongo_db][settings.mongo_collection]


def ping() -> bool:
    get_client().admin.command("ping")
    return True
