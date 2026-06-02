---
name: trade-show-exhibitor-scraper
description: Scrape exhibitor data from trade show websites like NEPCON Japan (GraphQL API) and electronica (ColdFusion/AJAX). Handles AJAX lazy-loading pagination, cookie-based API auth, and ColdFusion CMS pages. Outputs Excel with Chinese exhibitors classified by region (Shenzhen/Xiamen/Guangdong/Fujian/Other).
agent_created: true
---

# Trade Show Exhibitor Scraper

## Overview

This skill handles end-to-end scraping of trade show exhibitor directories, supporting two major website architectures:

1. **GraphQL API** (NEPCON-style) — Direct async API calls with httpx, cookie-based auth
2. **CMS/AJAX** (electronica-style) — Playwright Python for AJAX-lazy-loaded list pages + httpx async batch-scraping of detail pages

Output: Region-classified Excel sheets (13+ fields per exhibitor) + JSON backup.

## Workflow Decision Tree

```
Is there a direct API (check browser devtools network tab)?
├── YES → Use "GraphQL API Workflow"
└── NO  → Check if XLS download exists?
    ├── YES → Try downloading via browser session
    └── NO  → Use "CMS/AJAX Workflow"
```

## Workflow 1: GraphQL API (NEPCON Japan style)

**Use when**: The site loads exhibitor data via fetch/XHR calls to a GraphQL or REST API.

### Step 1: Find Event Edition ID

1. Open the exhibitor list page in playwright-cli
2. Click on any exhibitor detail to trigger the API call
3. Find the POST request to the API endpoint:
   ```
   playwright-cli requests | grep "graphql"
   playwright-cli request-body <ID> | grep eventEditionId
   ```

### Step 2: Extract All Exhibitor UUIDs

From the list page, extract all detail page hrefs containing `directory-details.org-[UUID].html`:

```bash
playwright-cli --raw eval "JSON.stringify(Array.from(document.querySelectorAll('a[href*=\"directory-details.\"]')).filter(a => a.href.match(/org-([a-f0-9-]+)/)).map(a => {const m = a.href.match(/org-([a-f0-9-]+)\.html/); return m?m[1]:null;}).filter(Boolean).filter((v,i,s)=>s.indexOf(v)===i))" > links_raw.json
```

For AJAX-lazy-loaded pages, scroll to bottom to trigger loading of all items. Use a loop:
```js
(async () => {
    let prev = 0;
    for (let i = 0; i < 20; i++) {
        window.scrollTo(0, document.body.scrollHeight);
        await new Promise(r => setTimeout(r, 3000));
        // check count
    }
})()
```

### Step 3: Parallel API Calls

Python async + httpx with semaphore (25-30 concurrent):

```python
headers = {"x-clientid": "<ClientId from cookie>"}
cookies = {"ClientId": "...", "id_token": "..."}  # from browser session
```

Key notes:
- `--raw` output from playwright-cli is **double-encoded** — parse JSON twice
- The JSON file from `--raw` may need `utf-8-sig` encoding
- Some exhibitors may return null data (no `exhibitingOrganisation`)

### Step 4: Parse Multilingual Data

Look for `multilingual[locale=en-gb]` for English data; fall back to first entry:

```python
en = None
for m in org_data.get("multilingual", []):
    if m.get("locale", "").lower() == "en-gb": en = m; break
if not en and org_data.get("multilingual"): en = org_data["multilingual"][0]
```

## Workflow 2: CMS/AJAX Pages (electronica style)

**Use when**: The site renders exhibitor data via server-side CMS (ColdFusion/PHP) with AJAX pagination and no direct API.

### Step 1: Install Playwright Browser

```bash
PLAYWRIGHT_BROWSERS_PATH="D:/path/to/browsers" python -m playwright install chromium
```

Set the env var to avoid C: disk space issues.

### Step 2: List Page Extraction

1. Open the list page with Playwright Python
2. Set maximum items per page (usually 60 via clicking `.pg_rppOpt[data-option="60"]`)
3. Navigate to page 1
4. Loop through all pages, clicking next button each time
5. Extract data from exhibitor card divs using `innerText` (preserves line breaks):

```python
items = await page.evaluate("""() => {
    const divs = document.querySelectorAll('div[id^="ceId_807_"]');
    return Array.from(divs).map(d => d.innerText.split('\\n'));
}""")
```

Each exhibitor card has: Line 1=Company, Line 2=Address, Line 3=Description, Line 4=Booth.

### Step 3: Detail Page Batch Scraping

Use httpx async with 50+ concurrent requests — the detail pages are static HTML:

```python
async with httpx.AsyncClient(headers={"User-Agent": "..."}) as client:
    sem = asyncio.Semaphore(50)
    async def fetch_one(url):
        async with sem:
            r = await client.get(url)
            return parse_detail(r.text)
```

Key HTML class selectors for electronica-style pages:
- `ce_phone` → phone number (inside `<a>` tag)
- `ce_mobile` → mobile (append to phone)
- `ce_email` → email (inside `<a>` tag)  
- `ce_website` → website (from `href` attribute)
- `ce_addr` → address
- `ce_text` → description (first one, before nested elements)
- `ce_cntct` → contact person section (check for `ce_topic` to distinguish from company section)
  - `ce_topic` → contact role (e.g., "Contact sales")
  - `ce_head` → person name (e.g., "Ms. Fiona Dai")
  - `ce_pstn` → position (e.g., "Sales")

**Critical parsing technique**: Nested divs make `(.*?)</div>` unreliable. Instead, extract from `<a>` tags:
```python
re.search(r'class="ce_phone[^"]*">.*?<a[^>]*>([^<]+)</a>', html, re.DOTALL)
```

## Region Classification

Use these regex patterns to classify Chinese exhibitors by region:

```python
CHINA_PATTERN = re.compile(r'(?:中国|china|\+86)', re.IGNORECASE)
REGION_PATTERNS = {
    "shenzhen": re.compile(r'\b(?:shenzhen|深圳|755)\b', re.IGNORECASE),
    "xiamen": re.compile(r'\b(?:xiamen|厦门|592)\b', re.IGNORECASE),
    "guangdong": re.compile(
        r'\b(?:dongguan|huizhou|guangzhou|zhongshan|foshan|shunde|zhuhai|'
        r'东莞|惠州|广州|中山|佛山|顺德|珠海|769|752|020|760|757|756)\b',
        re.IGNORECASE
    ),
    "fujian": re.compile(
        r'\b(?:fuzhou|xiamen|putian|sanming|quanzhou|zhangzhou|nanping|longyan|ningde|'
        r'福州|厦门|莆田|三明|泉州|漳州|南平|龙岩|宁德|'
        r'591|592|594|598|595|596|599|597|593)\b',
        re.IGNORECASE
    )
}
```

Priority order: Shenzhen > Xiamen > Guangdong > Fujian > China (other).

Combine all text fields (name, address, city, country, phone, email, website, description) before matching.

## Excel Output

Save to region-separated sheets (Shenzhen / Xiamen / Guangdong / Fujian / China Other / Overseas) plus a Summary sheet.

**Sanitization**: Remove control characters that break openpyxl:
```python
sanitized = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', value)
```

**Temp directory**: Set `TEMP` and `TMP` env vars if C: drive is full.

## Reference Scripts

The scripts are provided as reference implementations, not for direct execution (paths, cookies, and event IDs are session-specific):
- `scripts/reference_nepcon.py` — NEPCON Japan GraphQL API approach  
- `scripts/reference_electronica.py` — electronica CMS/AJAX approach

## Common Pitfalls

1. **C: drive full** — Set `PLAYWRIGHT_BROWSERS_PATH`, `TEMP`, `TMP` to D: drive
2. **Double-encoded JSON** — playwright-cli `--raw` output needs `json.loads(json.loads(data))`
3. **`<a>` tag extraction** — for nested divs, always extract from `<a>` tags, not `</div>` boundaries
4. **AJAX lazy loading** — must scroll to bottom to trigger all items
5. **Mixed locale countries** — country names can be in Japanese/Chinese/English; classification must search all text fields
