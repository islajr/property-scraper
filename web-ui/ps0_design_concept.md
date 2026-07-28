# Visual Concept: `ps0.akinmokun.com` (Updated Monospace Stack)

Here is the updated visual mockup featuring **Menlo / Hack** as the primary monospace font stack for all telemetry counters, JSON terminals, and operational metrics:

![ps0.akinmokun.com Dashboard UI Mockup (Menlo / Hack)](/home/isla-jr/.gemini/antigravity-cli/brain/3028f937-17a6-481b-9211-86247760e3d0/ps0_dashboard_menlo_1785238838633.png)

---

## Updated Design System Tokens

### 1. Typography Triad
* **Serif (`Playfair Display`)**: Primary page header (`PS-0 PropertyScraper`) with warm gold gradient.
* **Sans (`Inter`)**: Page body, navigational links, and card descriptions.
* **Monospace (`Menlo` / `Hack`)**: 
  * Replaces JetBrains Mono for a crisp, classic developer terminal aesthetic.
  * Used for big gold counters (`43,648`, `194`), timestamps, status badges, and the side-by-side JSON data transformation terminal.

### 2. Pure Black Canvas (`#000000`) & Warm Gold Accents (`#c9a84c` / `#e0c070`)
* **Background**: `#000000` (Pure obsidian black matching `akinmokun.com`).
* **Card Containers**: `#111111` surface fill with thin `#1e1e1e` borders.
* **Gold Highlights**: Primary metrics, hero title, and normalized JSON schema field keys (`"price_usd"`, `"formatted_address"`).

### 3. Font Stack CSS Specification
```css
font-family: Menlo, Hack, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
```
