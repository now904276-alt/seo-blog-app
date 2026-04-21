import os
import traceback

from flask import Flask, render_template, abort, Response, request, jsonify
from models import get_db, init_db
from config import SITE_URL, SITE_NAME
from datetime import datetime


def create_app():
    app = Flask(__name__)
    app.config["SITE_URL"] = SITE_URL
    app.config["SITE_NAME"] = SITE_NAME

    with app.app_context():
        init_db()

    @app.route("/")
    def index():
        conn = get_db()
        articles = conn.execute(
            "SELECT slug, title, meta_description, category, published_at "
            "FROM articles WHERE status='published' "
            "ORDER BY published_at DESC LIMIT 20"
        ).fetchall()
        conn.close()
        return render_template("index.html", articles=articles)

    @app.route("/<slug>")
    def article(slug):
        conn = get_db()
        row = conn.execute(
            "SELECT * FROM articles WHERE slug=? AND status='published'",
            (slug,),
        ).fetchone()
        conn.close()
        if not row:
            abort(404)
        return render_template("article.html", article=row)

    @app.route("/category/<category>")
    def category_page(category):
        conn = get_db()
        articles = conn.execute(
            "SELECT slug, title, meta_description, published_at "
            "FROM articles WHERE status='published' AND category=? "
            "ORDER BY published_at DESC",
            (category,),
        ).fetchall()
        conn.close()
        return render_template(
            "category.html", category=category, articles=articles
        )

    @app.route("/sitemap.xml")
    def sitemap():
        conn = get_db()
        articles = conn.execute(
            "SELECT slug, updated_at FROM articles WHERE status='published' "
            "ORDER BY updated_at DESC"
        ).fetchall()
        conn.close()
        xml = render_template(
            "sitemap.xml", articles=articles, site_url=SITE_URL
        )
        return Response(xml, mimetype="application/xml")

    @app.route("/robots.txt")
    def robots():
        txt = f"User-agent: *\nAllow: /\nSitemap: {SITE_URL}/sitemap.xml\n"
        return Response(txt, mimetype="text/plain")

    @app.route("/internal/daily-publish", methods=["POST"])
    def internal_daily_publish():
        secret = os.environ.get("CRON_SECRET")
        if not secret or request.headers.get("X-Cron-Secret") != secret:
            abort(403)
        try:
            from pipeline.daily_publisher import run_daily_publish
            result = run_daily_publish()
            return jsonify(result), 200
        except Exception as e:
            tb = traceback.format_exc()
            print(f"[daily_publish] FAILED:\n{tb}", flush=True)
            app.logger.error("daily_publish failed: %s", tb)
            return jsonify({
                "status": "error",
                "error_type": type(e).__name__,
                "message": str(e),
            }), 500

    @app.route("/about")
    def about():
        return render_template("about.html")

    @app.route("/privacy")
    def privacy():
        return render_template("privacy.html")

    @app.context_processor
    def inject_globals():
        return {
            "site_name": SITE_NAME,
            "site_url": SITE_URL,
            "current_year": datetime.utcnow().year,
        }

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=True)
