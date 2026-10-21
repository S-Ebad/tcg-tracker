"""Scrapy settings. Anything deployment-specific comes from the environment (see .env.example)."""
import os

BOT_NAME = "tcg_tracker"
SPIDER_MODULES = ["tcg_tracker.spiders"]
NEWSPIDER_MODULE = "tcg_tracker.spiders"

# Politeness: identify ourselves with a contact address, one request at a time, a couple of runs per day.
CONTACT_EMAIL = os.environ.get("TCG_CONTACT_EMAIL", "")
USER_AGENT = f"tcg-tracker/0.1 (Canadian Yu-Gi-Oh price tracker; contact: {CONTACT_EMAIL or 'unset'})"
ROBOTSTXT_OBEY = True
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 0.5
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 0.5
AUTOTHROTTLE_MAX_DELAY = 30
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
COOKIES_ENABLED = False

RETRY_ENABLED = True
RETRY_TIMES = 3
RETRY_HTTP_CODES = [429, 500, 502, 503, 504, 522, 524, 408]
DOWNLOADER_MIDDLEWARES = {
    # runs before RetryMiddleware (550) on the way back, so the retry happens after the wait
    "tcg_tracker.middlewares.RetryAfterMiddleware": 560,
}

ITEM_PIPELINES = {
    "tcg_tracker.pipelines.PostgresPipeline": 300,
}
DATABASE_URL = os.environ.get("DATABASE_URL", "")
DB_BATCH_SIZE = 500

# Trinity Hobby (Hotyon "Ultimate Search & Filter"). The API key is discovered from the collection page every run;
# this public frontend key is only a last-resort fallback and using it logs a loud warning.
TRINITY_FALLBACK_API_KEY = os.environ.get("TRINITY_FALLBACK_API_KEY", "04572457-312a-4a58-b5e9-6aff246ee39f")
TRINITY_MAX_PAGES = 100
TRINITY_COUNT_TOLERANCE = 0.005  # fail the run if the item count is off data.total by more than 0.5%

TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO")
