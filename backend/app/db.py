"""MongoDB client wiring (directConnection: reach mongod regardless of the
replica set's container-local advertised hostname)."""
from functools import lru_cache

from pymongo import MongoClient
from pymongo.collection import Collection

from .config import get_settings


@lru_cache
def get_client() -> MongoClient:
    settings = get_settings()
    # Short selection timeout so /health fails fast; longer socket timeout for
    # CPU-side auto-embed vector queries. Pool + compressors cut connection churn
    # and wire size under concurrent UI traffic.
    return MongoClient(
        settings.mongo_uri,
        serverSelectionTimeoutMS=5000,
        connectTimeoutMS=5000,
        socketTimeoutMS=30000,
        maxPoolSize=20,
        minPoolSize=1,
        retryReads=True,
        compressors="zstd,snappy,zlib",
    )


@lru_cache
def get_collection() -> Collection:
    settings = get_settings()
    return get_client()[settings.mongo_db][settings.mongo_collection]


def ping() -> bool:
    get_client().admin.command("ping")
    return True
