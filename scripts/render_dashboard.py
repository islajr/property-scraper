#!/usr/bin/env python3
"""
PS-0 Dashboard Compiler Script
Compiles templates/dashboard.html.j2 + templates/style.css + data/telemetry.json
into static export web/index.html, web/sitemap.xml, and web/robots.txt
"""

import json
import os
import sys
from datetime import datetime, timezone
import jinja2

from generate_telemetry import generate_telemetry

def render_dashboard():
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    templates_dir = os.path.join(base_dir, "templates")
    data_dir = os.path.join(base_dir, "data")
    web_dir = os.path.join(base_dir, "web")
    
    telemetry_file = os.path.join(data_dir, "telemetry.json")
    style_file = os.path.join(templates_dir, "style.css")
    template_file = os.path.join(templates_dir, "dashboard.html.j2")

    os.makedirs(web_dir, exist_ok=True)

    # 1. Ensure telemetry data exists
    if not os.path.exists(telemetry_file):
        telemetry_data = generate_telemetry()
    else:
        with open(telemetry_file, 'r', encoding='utf-8') as f:
            telemetry_data = json.load(f)

    # 2. Read style.css
    with open(style_file, 'r', encoding='utf-8') as f:
        style_css = f.read()

    # 3. Setup Jinja2 environment and render dashboard
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(templates_dir),
        autoescape=jinja2.select_autoescape(['html', 'xml'])
    )
    
    template = env.get_template("dashboard.html.j2")
    rendered_html = template.render(
        telemetry=telemetry_data,
        style_css=style_css
    )

    # 4. Save web/index.html
    index_path = os.path.join(web_dir, "index.html")
    with open(index_path, 'w', encoding='utf-8') as f:
        f.write(rendered_html)
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

    print("🚀 Build completed successfully for ps0.akinmokun.com static export!")

if __name__ == "__main__":
    render_dashboard()
