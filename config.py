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
REQUEST_DELAY_MIN = 2        # seconds — minimum inter-request delay
REQUEST_DELAY_MAX = 3        # seconds — maximum inter-request delay
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
HEALTH_CHECK_INTERVAL_DAYS = 2   # re-check every listing at least this often
HEALTH_CHECK_DELAY_MIN     = 3  # seconds between requests
HEALTH_CHECK_DELAY_MAX     = 1
HEALTH_CHECK_LIMIT         = 1000 # Maximum listings to check per health check run


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
    # ── SPECIFIC SUB-NEIGHBOURHOODS & ESTATES (Checked First) ───────────────────
    # Lagos - Estates / Sub-areas
    "Lekki Phase 1", "Lekki Phase 2", "Osapa London", "Osapa", "Oniru", "Agungi",
    "Idado", "Ikate", "Igbo Efon", "Ologolo", "Ilasan", "Jakande", "Maroko", "Elegushi",
    "Lafiaji", "Eko Atlantic", "Pinnock Beach Estate", "Victory Park Estate",
    "Victoria Garden City", "VGC", "Freedom Way", "Chevy View Estate", "Chevy View",
    "Nicon Town", "Oral Estate", "Alpha Beach", "Lekki Conservation", "Abijo", 
    "Shangisha", "Palmgrove", "Onipanu", "Pedro", "Ilupeju", "Akoka", "Abule Ijesha", 
    "Ikota", "Ojo", "Orchid", "Isolo", "Ikorodu", "Ejigbo", "Abule Egba", "Ipaja", "Iyana Ipaja", 
    "Ikotun", "Igando", "Ago Palace", "Okota", "Maryland", "Magodo", "Surulere", "Yaba", 
    "Gbagada", "Ojota", "Isale Eko", "Badagry", "Epe", "Sangotedo", "Ogombo", "Apapa", 
    "Orile", "Festac Town", "Amuwo Odofin", "Satellite Town", "Ojodu Berger", 
    "Omole Phase 1", "Omole Phase 2", "Isheri North", "Berger", "Ogba", "Ikeja GRA", 
    "Ikeja", "Allen Avenue", "Agidingbi", "Oregun", "Ogudu", "Ketu", "Alapere", 
    "Agboville", "Bariga", "Agege", "Alimosho", "Shomolu", "Somolu",
    
    # Abuja - Estates / Sub-areas
    "Maitama", "Asokoro", "Wuse 2", "Wuse", "Garki", "Jabi", "Utako", "Gwarinpa", 
    "Apo", "Lugbe", "Katampe", "Nbora", "Kuje", "Bwari", "Gwagwalada", "Life Camp", 
    "Kubwa", "Dutse", "Mpape", "Lokogoma", "Galadimawa", "Durumi", "Gudu", "Wumba", 
    "Kado", "Dawaki", "Guzape", "Mabushi", "Aminu Kano Crescent", "Jahi", "Wuye",
    "Gaduwa", "Karsana", "Idu",
    
    # Ibadan - Specific
    "Ring Road", "Dugbe", "Felele", "Akala", "Oluyole", "Jericho", "Sango",
    
    # Port Harcourt - Specific
    "GRA Port Harcourt", "Trans Amadi", "Rumuola", "Rumuigbo", "Eliozu", "Rumuokoro",
    
    # Ogun - Specific
    "Mowe", "Ewekoro", "Ijebu Ode", "Isiwo", "Magboro", "Shimawa", "Odogbolu",
    
    # Enugu - Specific
    "Enugu GRA", "Independence Layout",
    
    # Imo - Specific
    "Owerri", "Ohaji",
    
    # Edo / Delta - Specific
    "Okpanam",

    # ── GENERAL AREA & CITY FALLBACKS (Checked Last) ──────────────────────────
    "Ibeju-Lekki", "Ibeju Lekki", "Lekki", "Lagos Island", "Victoria Island", "Banana Island",
    "Ikoyi", "Port Harcourt", "Ibadan", "Enugu", "Benin City", "Benin", "Asaba"
]
