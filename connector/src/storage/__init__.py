"""
Storage module using SQLite FTS5 for fast full-text search and caching.
"""
from .db import DatabaseManager, get_db

__all__ = ["DatabaseManager", "get_db"]
