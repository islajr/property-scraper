"""
config.py — Central configuration loader for PS-0 PropertyScraper.

Reads from environment variables. In local development, populate a .env file.
In GitHub Actions, these are injected as repository secrets.

Required secrets:
  DATABASE_URL          — Supabase PostgreSQL connection string
  TELEGRAM_BOT_TOKEN    — Telegram bot token for run summaries
  TELEGRAM_CHAT_ID      — Telegram chat/channel ID to receive summaries
"""

import os
from dotenv import load_dotenv

load_dotenv()  # no-op in GitHub Actions where vars are already in env

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.environ["DATABASE_URL"]   # will raise immediately if missing

# ── Telegram ──────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# —— Nominatim —————————————————————————————————————————————————————————————————
NOMINATIM_CONTACT_EMAIL = os.environ.get("NOMINATIM_CONTACT_EMAIL")

# ── Scraper behaviour ─────────────────────────────────────────────────────────
REQUEST_DELAY_MIN = 0.5        # seconds — minimum inter-request delay
REQUEST_DELAY_MAX = 1.0        # seconds — maximum inter-request delay
MAX_RETRIES       = 3          # per-request retry limit
RETRY_BACKOFF_BASE = 2.0       # seconds — exponential backoff base

# Deduplication short-circuit: stop paginating a portal's search results when
# this many consecutive listings are already known in the database.
PAGINATION_STOP_AFTER_KNOWN = 10

# Missed-run threshold before a listing is flipped to REMOVED.
# 3 consecutive misses = listing is gone (not just a portal blip).
MISSED_RUN_REMOVAL_THRESHOLD = 3

# Health checker — three-day individual URL verification.
# Runs as a separate mode (./run.sh --health-check).
HEALTH_CHECK_INTERVAL_DAYS = 3   # re-check every listing at least this often
HEALTH_CHECK_DELAY_MIN     = 0.5  # seconds between requests
HEALTH_CHECK_DELAY_MAX     = 0.1

# Suspected-sold: minimum days a listing must have been active before removal
# can be classified as a likely transaction.
SUSPECTED_SOLD_MIN_DAYS = 30

# DB write batch size
UPSERT_BATCH_SIZE = 200

# Page cap per listing feed
MAX_PAGES_PER_FEED = 10

# ── Neighbourhood canonical list ───────────────────────────────────────────────
# Seeded from P0 — PropertyDataGenerator. DO NOT edit without updating P0 first.
# This is the shared vocabulary between the synthetic and real data pipelines.
CANONICAL_NEIGHBOURHOODS = [
    # Lagos
    "Lekki Phase 1", "Lekki Phase 2", "Victoria Island", "Ikoyi",
    "Banana Island", "Ajah", "Chevron", "Ikeja GRA", "Maryland",
    "Magodo", "Surulere", "Yaba", "Gbagada", "Ojota", "Isale Eko",
    "Badagry", "Epe", "Ibeju-Lekki", "Sangotedo", "Ogombo",
    "Oniru", "Osapa London", "Agungi", "Idado", "Ikate",
    "Lekki Expressway", "Jakande", "Igbo Efon", "Ologolo",
    "Ilasan", "Maroko", "Elegushi", "Lafiaji", "Eko Atlantic",
    "Lagos Island", "Apapa", "Orile", "Festac Town", "Amuwo Odofin",
    "Satellite Town", "Ojodu Berger", "Omole Phase 1", "Omole Phase 2",
    "Isheri North", "Berger", "Ogba", "Ikeja", "Allen Avenue",
    "Agidingbi", "Oregun", "Ogudu", "Ketu", "Alapere",
    "Agboville", "Bariga", "Akoka", "Abule Ijesha", "Agege", "Alimosho", "Ikota", 
    "Ojo", "Orchid", "VGC", "Isolo", "Ikorodu", "Ejigbo", "Abule Egba", "Wuye", ""
    # Abuja
    "Maitama", "Asokoro", "Wuse 2", "Wuse", "Garki",
    "Jabi", "Utako", "Gwarinpa", "Apo", "Lugbe",
    "Katampe", "Nbora", "Kuje", "Bwari", "Gwagwalada",
    "Life Camp", "Kubwa", "Dutse", "Mpape", "Lokogoma",
    "Galadimawa", "Durumi", "Gudu", "Wumba", "Kado",
    "Dawaki", "Guzape", "Mabushi", "Aminu Kano Crescent", "Jahi",
    # Ibadan
    "Ring Road", "Dugbe", "Felele", "Ibadan", "Akala", "Oluyole", 
    "Jericho", "Sango", ""
    # Port Harcourt
    "GRA Port Harcourt", "Trans Amadi", "Rumuola", "Rumuigbo",
    "Eliozu", "Rumuokoro", "Enugu GRA", "Independence Layout",
    # Ogun
    "Mowe", "Ewekoro", 
    # Enugu
    "Enugu", 
    # Imo
    "Owerri", "Ohaji", 
    
]