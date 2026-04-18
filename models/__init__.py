import sqlite3
import os
from config import DATABASE_PATH


def get_db():
    os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS articles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            meta_description TEXT,
            content_html TEXT NOT NULL,
            content_markdown TEXT NOT NULL,
            category TEXT NOT NULL,
            target_keyword TEXT NOT NULL,
            secondary_keywords TEXT,
            status TEXT DEFAULT 'draft',
            published_at DATETIME,
            updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            word_count INTEGER,
            schema_type TEXT DEFAULT 'Article',
            affiliate_links TEXT,
            performance_score REAL DEFAULT 0,
            last_reviewed_at DATETIME,
            rewrite_count INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS performance_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            article_id INTEGER NOT NULL REFERENCES articles(id),
            date DATE NOT NULL,
            impressions INTEGER DEFAULT 0,
            clicks INTEGER DEFAULT 0,
            ctr REAL DEFAULT 0,
            position REAL DEFAULT 0,
            source TEXT DEFAULT 'gsc',
            UNIQUE(article_id, date, source)
        );

        CREATE TABLE IF NOT EXISTS keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT UNIQUE NOT NULL,
            search_volume INTEGER,
            difficulty TEXT,
            intent TEXT,
            status TEXT DEFAULT 'pool',
            assigned_article_id INTEGER,
            discovered_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            source TEXT
        );

        CREATE TABLE IF NOT EXISTS affiliate_programs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tool_name TEXT NOT NULL,
            program TEXT NOT NULL,
            affiliate_url TEXT NOT NULL,
            commission_type TEXT,
            commission_rate TEXT,
            cookie_days INTEGER,
            status TEXT DEFAULT 'active'
        );

        CREATE INDEX IF NOT EXISTS idx_articles_slug ON articles(slug);
        CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
        CREATE INDEX IF NOT EXISTS idx_articles_category ON articles(category);
        CREATE INDEX IF NOT EXISTS idx_keywords_status ON keywords(status);
        CREATE INDEX IF NOT EXISTS idx_performance_logs_article ON performance_logs(article_id, date);
    """)
    conn.commit()
    conn.close()
