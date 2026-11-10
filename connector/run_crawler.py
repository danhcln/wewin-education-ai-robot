"""
CLI entry point to execute WeWIN website crawling and rebuild search index.
Usage:
    python run_crawler.py
"""
import sys
import io
from pathlib import Path

# Fix Windows console UTF-8 output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.config import settings
from src.utils.logger import logger
from src.crawler.sitemap_crawler import WeWinCrawler
from src.storage.db import get_db

def main():
    logger.info("Starting WeWIN Website Crawler & Indexer...")
    crawler = WeWinCrawler()
    knowledge_base = crawler.run()

    logger.info("Indexing knowledge base into SQLite FTS5 search engine...")
    db = get_db()
    db.index_records(knowledge_base)

    logger.info("Crawler and Indexing completed successfully!")
    logger.info(f"Knowledge JSON: {settings.KNOWLEDGE_JSON_PATH}")
    logger.info(f"FTS5 Database: {settings.DATABASE_PATH}")

if __name__ == "__main__":
    main()
