import os

DATABASE_PATH = os.environ.get("DATABASE_PATH", "data/blog.db")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
SITE_URL = os.environ.get("SITE_URL", "http://localhost:5000")
SITE_NAME = os.environ.get("SITE_NAME", "AI Tool Pilot")
ARTICLES_PER_DAY = int(os.environ.get("ARTICLES_PER_DAY", "1"))
