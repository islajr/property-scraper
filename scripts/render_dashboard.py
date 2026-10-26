#!/usr/bin/env python3
"""
PS-0 Dashboard Compiler Script
Compiles templates/dashboard.html.j2 + templates/style.css + data/telemetry.json
into static export web/index.html, web/sitemap.xml, and web/robots.txt
Includes SHA-256 hash checking to skip unchanged builds.
"""

import json
import os
import sys
import hashlib
from datetime import datetime, timezone
try:
    import jinja2
except ImportError:
    import subprocess
    print("⚠️ jinja2 package not found. Auto-installing jinja2...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "jinja2"])
    import jinja2

from generate_telemetry import generate_telemetry

def compute_metrics_hash(telemetry_data):
    """Compute SHA-256 hash of telemetry metrics, ignoring volatile timestamp."""
    data_copy = dict(telemetry_data)
    data_copy.pop("last_updated", None)
    serialized = json.dumps(data_copy, sort_keys=True)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()

def render_dashboard(force=False, cached=False):
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    templates_dir = os.path.join(base_dir, "templates")
    data_dir = os.path.join(base_dir, "data")
    web_dir = os.path.join(base_dir, "web")
    
    telemetry_file = os.path.join(data_dir, "telemetry.json")
    hash_file = os.path.join(data_dir, ".telemetry_hash")
    style_file = os.path.join(templates_dir, "style.css")
    template_file = os.path.join(templates_dir, "dashboard.html.j2")

    os.makedirs(web_dir, exist_ok=True)

    # 1. Generate/load telemetry data
    if cached:
        with open(telemetry_file, encoding='utf-8') as f:
            telemetry_data = json.load(f)
    else:
        telemetry_data = generate_telemetry()
    # Design changes must rebuild even when the dataset has not changed.
    fingerprint = hashlib.sha256(compute_metrics_hash(telemetry_data).encode('utf-8'))
    for source in (template_file, style_file):
        with open(source, 'rb') as f:
            fingerprint.update(f.read())
    current_hash = fingerprint.hexdigest()
    previous_hash = ""

    if os.path.exists(hash_file):
        with open(hash_file, 'r', encoding='utf-8') as f:
            previous_hash = f.read().strip()

    # If metrics hash is unchanged and force is not set, skip build
    if current_hash == previous_hash and not force and os.path.exists(os.path.join(web_dir, "index.html")):
        print("ℹ️ Telemetry metrics unchanged — static dashboard build skipped.")
        return False

    # 2. Read style.css
    with open(style_file, 'r', encoding='utf-8') as f:
        style_css = f.read()

    # 3. Setup Jinja2 environment and render dashboard
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(templates_dir),
        autoescape=jinja2.select_autoescape(['html', 'xml', 'j2'])
    )
    
    template = env.get_template("dashboard.html.j2")
    rendered_html = template.render(
        telemetry=telemetry_data,
        style_css=style_css
    )

    # 4. Save web/index.html
    index_path = os.path.join(web_dir, "index.html")
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(line.rstrip() for line in rendered_html.splitlines()) + '\n')
    print(f"✅ Generated static dashboard: {index_path}")

    # 5. Generate web/sitemap.xml
    now_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    sitemap_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://ps0.akinmokun.com/</loc>
    <lastmod>{now_date}</lastmod>
    <changefreq>daily</changefreq>
    <priority>1.0</priority>
  </url>
</urlset>
"""
    sitemap_path = os.path.join(web_dir, "sitemap.xml")
    with open(sitemap_path, 'w', encoding='utf-8') as f:
        f.write(sitemap_content.strip())
    print(f"✅ Generated sitemap: {sitemap_path}")

    # 6. Generate web/robots.txt
    robots_content = f"""User-agent: *
Allow: /

Sitemap: https://ps0.akinmokun.com/sitemap.xml
"""
    robots_path = os.path.join(web_dir, "robots.txt")
    with open(robots_path, 'w', encoding='utf-8') as f:
        f.write(robots_content.strip())
    print(f"✅ Generated robots.txt: {robots_path}")

    # Save new hash
    with open(hash_file, 'w', encoding='utf-8') as f:
        f.write(current_hash)

    print("🚀 Build completed successfully for ps0.akinmokun.com static export!")
    return True

if __name__ == "__main__":
    force_build = "--force" in sys.argv
    render_dashboard(force=force_build, cached="--cached" in sys.argv)
