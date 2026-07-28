# Handoff Blueprint: `ps0.akinmokun.com` (PS-0 PropertyScraper Telemetry Dashboard)

## Executive Summary & Target Scope
* **Target Subdomain**: `ps0.akinmokun.com`
* **Target Repository**: `/home/isla-jr/Documents/se-workspace/property-scraper`
* **Deployment Target**: Cloudflare Pages (Asset directory: `web/`)
* **Purpose**: Public Data Engineering Telemetry & Pipeline Health Dashboard for `PS-0 PropertyScraper`. Showcases multi-portal harvesting, data cleansing, deduplication, and ingestion volume without cannibalizing `reports.akinmokun.com` (monthly economics) or `propertyintel.akinmokun.com` (end-user web app).

---

## Design System Tokens & Typography

### Canvas & Surface Palette (Deep Obsidian Dark Mode)
```css
:root {
  --bg:          #000000;   /* Pure black canvas (matches akinmokun.com) */
  --surface:     #111111;   /* Card surface background */
  --surface-2:   #161616;   /* Subtext container fill */
  --border:      #1e1e1e;   /* Subtle container border */
  --border-2:    #2a2a2a;   /* Active / hover border */
  --text:        #f0f0f0;   /* Primary text */
  --text-dim:    #a3a3a3;   /* Secondary text */
  --text-muted:  #555555;   /* Labels & captions */
  
  /* Accent Colors */
  --gold:        #c9a84c;   /* Primary gold accent */
  --gold-light:  #e0c070;   /* Bright gold for headlines & JSON keys */
  --gold-tint:   rgba(201, 168, 76, 0.04); /* Card hover tint */
  --gold-border: rgba(201, 168, 76, 0.3);  /* Card hover border */
  --live:        #4ade80;   /* Operational status pulse green */
}
```

### Font Triad Specification
```css
/* Primary Editorial Serif (Headings & Page Title) */
font-family: var(--font-playfair), "Playfair Display", Georgia, serif;

/* Body & Navigation (Sans-Serif) */
font-family: var(--font-inter), "Inter", -apple-system, sans-serif;

/* Operational Monospace (Metrics, Code Payloads, Timestamps, Badges) */
font-family: Menlo, Hack, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
```
> **Cross-Platform Menlo Note**: The CSS font stack leads with `Menlo` and `Hack`. To ensure 100% pixel-identical `Menlo` rendering on non-Apple devices (Windows/Linux/Android), embed a base64 `@font-face` declaration for `Menlo.woff2` or `Hack.woff2` directly inside `templates/style.css` (following the embedded font pattern in `property-reports`).

---

## Core Dashboard Content Modules

1. **Hero Header & Live Status Pill**:
   * Title: `PS-0 PropertyScraper` in `Playfair Display` with a warm gold text gradient (`#e0c070`).
   * Live Status Pill: Glowing green `● OPERATIONAL` indicator.
   * Sticky top navbar matching `akinmokun.com` (with responsive mobile hamburger drawer).

2. **Big Monospace Telemetry Counters**:
   * **Total Records Ingested**: e.g., `43,648` (rendered in `Menlo` monospace with warm gold `#c9a84c`).
   * **Active Unique Listings**: e.g., `12,131`.
   * **Spatial Coverage**: `8 Cities · 194 Neighbourhoods`.

3. **Source Portal Health Matrix**:
   * Table displaying per-portal extraction telemetry (Portal Name, Last Harvest Listing Count, HTTP Success Rate %, Average Latency).

4. **Data Transformation & Sanitization Showcase (Raw vs. Cleaned JSON)**:
   * Side-by-side dark code blocks comparing raw messy scraped listing HTML/JSON vs. PS-0's normalized schema.
   * Normalized keys (`"price_ngn"`, `"normalized_location"`, `"dedup_hash"`) highlighted in warm gold (`#e0c070`).

5. **Deduplication & Data Hygiene Guardrails**:
   * Deduplication rate stats (e.g. *14.2% duplicate listings merged across portals*).
   * Outlier detection stats (e.g. *42 price anomalies flagged & filtered this month*).

---

## Repository & Pipeline Architecture

```text
property-scraper/
├── data/
│   ├── neighbourhood_snapshots.csv
│   └── telemetry.json             <-- Auto-generated post-run stats
├── templates/
│   ├── dashboard.html.j2          <-- Jinja2 template for ps0.akinmokun.com
│   └── style.css                  <-- Embedded Menlo & CSS variables
├── scripts/
│   ├── generate_telemetry.py      <-- Extracts stats from Supabase/CSV
│   └── render_dashboard.py        <-- Renders HTML + sitemap.xml + robots.txt
├── web/                           <-- Static export target (Cloudflare Pages)
│   ├── index.html
│   ├── sitemap.xml
│   └── robots.txt
└── wrangler.jsonc                 <-- Cloudflare Pages assets dir: "web"
```

---

## Step-by-Step Action Checklist for Development

- [ ] **Step 1: Workspace Setup**:
  * Open `/home/isla-jr/Documents/se-workspace/property-scraper`.
  * Create `templates/`, `scripts/`, and `web/` directories.
- [ ] **Step 2: Design System Stylesheet**:
  * Create `templates/style.css` using the pure black canvas (`#000000`), warm gold accents (`#c9a84c`), and the `Playfair Display / Inter / Menlo` font triad.
- [ ] **Step 3: Jinja2 Dashboard Template**:
  * Create `templates/dashboard.html.j2` containing the hero section, status pill, big monospace counter cards, source portal table, and JSON transformer widget.
- [ ] **Step 4: Telemetry Generator Script**:
  * Create `scripts/generate_telemetry.py` to calculate listing totals, last run timestamps, and deduplication stats, outputting to `data/telemetry.json`.
- [ ] **Step 5: Dashboard Compiler Script**:
  * Create `scripts/render_dashboard.py` to render `web/index.html` and automatically generate `web/sitemap.xml` and `web/robots.txt`.
- [ ] **Step 6: Local Verification**:
  * Execute `python3 scripts/render_dashboard.py` and inspect `web/index.html` locally.
- [ ] **Step 7: Cloudflare Deployment**:
  * Configure `wrangler.jsonc` pointing `assets.directory` to `"web"`, commit to `master`, and deploy `ps0.akinmokun.com`.
