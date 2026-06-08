---
name: trade-show-exhibitor-scraper
description: Scrape exhibitor data from trade show websites. Supports 6 architectures: GraphQL API (Reed Expo/NEPCON), Algolia Search API (NuernbergMesse Next.js like EUROGUSS), REST API with API Key (Messe Frankfurt), CMS/AJAX (electronica), Elementor Static HTML (FastenerExpo), and Django REST API + Referer Auth Bypass (Palexpo/INDEX). Outputs Excel with Chinese exhibitors classified by region.
agent_created: true
---

# Trade Show Exhibitor Scraper

## Overview

This skill handles end-to-end scraping of trade show exhibitor directories, supporting four major website architectures:

1. **GraphQL API** (NEPCON-style / Reed Expo) — Async httpx, cookie-based auth, high concurrency
2. **Algolia Search API** (EUROGUSS-style / NuernbergMesse Next.js) — Direct Algolia REST API, one-request fetch all, no auth needed
3. **REST API** (Light+Building-style / Messe Frankfurt) — Sync requests, API Key header auth, paginated
4. **CMS/AJAX** (electronica-style) — Playwright for list pages + httpx async for detail pages

Output: Region-classified Excel sheets (12+ fields per exhibitor) + JSON backup.

## Workflow Decision Tree

```
Is there a direct API (check browser devtools network tab)?
├── YES → What kind?
│   ├── POST to algolianet.com or algolia.net → Use "Workflow 4: Algolia Search API"
│   ├── POST with GraphQL query body          → Use "Workflow 1: GraphQL API"
│   └── GET with ?pageNumber=                 → Use "Workflow 3: REST API with API Key"
└── NO  → Check if XLS download exists?
    ├── YES → Try downloading via browser session
    └── NO  → Use "Workflow 2: CMS/AJAX Workflow"
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

## Workflow 4: Algolia Search API (NuernbergMesse Next.js style)

**Use when**: The site is a NuernbergMesse event (euroguss.de, pcimeurope.com, etc.) built with Next.js + Sitecore. Look for POST requests to `algolianet.com` or `algolia.net` in devtools Network tab.

**Why this is the best workflow**: Algolia stores ALL exhibitor data including contact details, descriptions, products, and employee info in a single index. Usually one API call fetches everything (no detail page scraping needed).

### Step 1: Find API Credentials

Open devtools → Network → filter by `algolia`. Find a POST to `/1/indexes/*/queries`:

```
Application ID: x-algolia-application-id header value
API Key:        x-algolia-api-key header value  
Index Name:     From request body → "indexName" field
Site Filter:    From request body → "filters" field (e.g., "site:guss")
```

### Step 2: Fetch All Exhibitors

NuernbergMesse events typically have <1000 exhibitors, so set `hitsPerPage=1000`:

```python
import requests

API_URL = "https://{appid}-2.algolianet.com/1/indexes/*/queries"
HEADERS = {
    "x-algolia-api-key": "<key>",
    "x-algolia-application-id": "<appid>",
    "content-type": "text/plain",
}

payload = {
    "requests": [{
        "indexName": "prod_website_companies_en",
        "params": "distinct=true&filters=site%3Aguss&hitsPerPage=1000&page=0&query="
    }]
}
resp = requests.post(API_URL, json=payload, headers=HEADERS)
hits = resp.json()["results"][0]["hits"]  # All exhibitors!
```

### Step 3: Fields Available in Algolia

| Algolia Field | Description |
|---|---|
| `companyName` | Company name |
| `country` | Country (English) |
| `booth[{boothHall, boothNumber}]` | Hall & booth number |
| `streetno, postcode, city` | Address |
| `email` | Company email |
| `companyDescription` | HTML description (use `clean_text()`) |
| `companyType` | Type (Manufacturer/Supplier/etc) |
| `logo` | Logo image URL |
| `url` | Detail page path (e.g. `/en/exhibitors/2a-spa-2520174`) |
| `employee[{firstName,lastName,function,email}]` | Contact persons |
| `products[]` | Product list |
| `keyword[]` | Keyword tags |
| `coExhibitors[]` | Co-exhibitor names |
| `filternomenclature_DEF/BERUF/BRANCHE` | Product categories |
| `objectID` | Unique ID |

**Known gaps vs. detail page**: Website URL and phone number are NOT in Algolia but ARE on the detail page. If needed, selectively scrape detail pages for those 2 fields.

### Step 4: Detail Pages (if needed)

Detail page URL pattern: `https://{domain}{url}` where `url` comes from Algolia.

Website extraction from detail page:
```python
# Look for <a> with "Website" label
re.search(r'Website.*?href="([^"]+)"', html, re.DOTALL)
```

Phone extraction:
```python
# Phone is in <a href="tel:+39..."> tag
re.search(r'href="tel:([^"]+)"', html)
```

## Workflow 3: REST API with API Key (Messe Frankfurt style)

**Use when**: The site uses a REST API with `?pageNumber=N` pagination and an API Key in headers.

### Step 1: Find API Endpoint & Key

Open browser devtools → Network → XHR/Fetch tab. Look for requests to `api.*.com` with these characteristics:

- GET request with `pageNumber` parameter
- Response shape: `{"result": {"hits": [...], "total": N}}`
- Header: `apikey: <base64-looking-string>`

### Step 2: Configure & Test Single Page

```python
CONFIG = {
    "API_ENDPOINT": "https://api.messefrankfurt.com/service/esb_api/exhibitor-service/api/2.1/public/exhibitor/search",
    "HEADERS": {
        "apikey": "<key from browser>",
        "origin": "https://show-name.messefrankfurt.com",
        "referer": "https://show-name.messefrankfurt.com/",
        "accept": "application/json",
    },
    "PARAMS": {
        "language": "en-GB",
        "pageSize": 30,
        "findEventVariable": "LIGHTBUILDING",  # show-specific
    }
}
```

### Step 3: Sync Loop with Delay + Retry

Messe Frankfurt APIs typically support only serial requests (no high concurrency). Use **`tenacity`** for robust retry:

```python
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(10),
    retry=retry_if_exception_type((ConnectionError, Timeout)),
    reraise=True
)
def fetch_page(page):
    resp = requests.get(url, headers=HEADERS, params={**PARAMS, "pageNumber": page}, timeout=15, allow_redirects=False)
    resp.raise_for_status()
    return resp.json()
```

**Critical**: Use `allow_redirects=False` to catch API key expiry (Messe Frankfurt returns 302 redirect to login page when key expires).

### Step 4: Add Anti-Detection Delay

```python
import random, time

for page in range(1, max_pages + 1):
    data = fetch_page(page)
    # process data...
    delay = 1.5 + random.uniform(0.5, 1.5)  # 1.5–3.0s random jitter
    time.sleep(delay)
```

### Step 5: Detect & Handle API Key Expiry

```python
except Exception as e:
    if "401" in str(e) or "Unauthorized" in str(e) or "302" in str(e):
        logger.critical("API key expired! Update CONFIG['HEADERS']['apikey']")
        break
```

### Step 6: Construct Detail Page URLs

Messe Frankfurt detail pages use a specific URL pattern derived from the API response:

```python
links = exhibitor.get("presentationLinks", [])
if links and links[0].get("exhibitorUrlRewrite"):
    url = f"https://{show}.messefrankfurt.com/frankfurt/en/exhibitor-search.detail.html/{rewrite}.html"
```

## Best Practices (all workflows)

### Text Cleaning Pipeline

Always chain these in order when processing scraped text:

```python
def _clean(text):
    if not text: return ""
    text = str(text)
    text = re.sub(r'<[^>]+>', '', text)       # 1. strip HTML tags
    text = re.sub(r'&[a-z0-9]+;', '', text)   # 2. strip HTML entities (&nbsp; etc)
    text = re.sub(r'\s+', ' ', text).strip()   # 3. collapse whitespace
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)  # 4. strip control chars
    return text
```

### Retry Strategy

Use `tenacity` library instead of manual `for _ in range(N)` loops:

```python
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

@retry(stop=stop_after_attempt(3), wait=wait_fixed(10),
       retry=retry_if_exception_type((ConnectionError, Timeout)))
def robust_request(url, **kwargs):
    return requests.get(url, timeout=15, **kwargs)
```

### Logging Setup

Always configure dual logging (file + console) for long-running scrapes:

```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("scrape.log", encoding='utf-8'),
              logging.StreamHandler()]
)
```

## Region Classification

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
- `scripts/reference_lightbuilding.py` — Light+Building REST API approach (Messe Frankfurt)
- `scripts/reference_euroguss.py` — EUROGUSS Algolia API approach (NuernbergMesse Next.js)

## Common Pitfalls

1. **C: drive full** — Set `PLAYWRIGHT_BROWSERS_PATH`, `TEMP`, `TMP` to D: drive
2. **Double-encoded JSON** — playwright-cli `--raw` output needs `json.loads(json.loads(data))`
3. **`<a>` tag extraction** — for nested divs, always extract from `<a>` tags, not `</div>` boundaries
4. **AJAX lazy loading** — must scroll to bottom to trigger all items
5. **Mixed locale countries** — country names can be in Japanese/Chinese/English; classification must search all text fields
6. **API key expiry** — use `allow_redirects=False` to detect 302 redirect (Messe Frankfurt sends you to login page when key expires)
7. **Rate limiting** — REST APIs often have anti-scraping thresholds; always add 1.5–3s random delay between pages
8. **Skipped `raise_for_status()`** — always call `resp.raise_for_status()` before parsing JSON to catch auth errors early

## 经验更新 2026-06-02

### Algolia 单次全量抓取
- EUROGUSS 2026：hitsPerPage=1000 一次请求获取 728 家参展商全部数据（无需翻页）
- NuernbergMesse 展会规模通常 ≤1000，推荐先用 hitsPerPage=1000 试探，不够再加 page=1

### 区域分组用户反馈
- 用户期望 Excel 按区域分独立工作表，而非单一 sheet。修复：`save_excel()` 改为逐区域调用 `write_sheet()`，最后添加 Summary 汇总页
- 不同展会的中国展商区域分布差异大（EUROGUSS：浙江12/江苏6/台湾5/香港4；NEPCON：深圳/广东为主），需按展会调整区域关键词

### 详情页补充字段
- Algolia API 缺失 Website 和 Phone，需额外抓取详情页。Website 用 `re.search(r'Website.*?href="([^"]+)"', html)`，Phone 用 `re.search(r'href="tel:([^"]+)"', html)`

## 经验更新 2026-06-08

### FastenerExpo 2026 — Elementor 标题定位父容器提取法（新增 Workflow 5）
- **适用**: 静态 HTML (Elementor/WordPress)，字段无 class/id，嵌套 `<div>` 无分隔标记
- **核心方案**: `extract_field(soup, heading_text)` — 找到标题元素 → 逐级上溯父容器 → 取第一个文本长度超过标题的容器 → 去掉标题得值
- **原因**: `find_next()` 遍历 DOM 会导致字段交叉污染（Booth 含 Country，Country 含 Type）；正则切分无分隔符不可靠。103/103 (100%) 成功

### INDEX26 2026 — Django REST API + Referer 认证绕过（新增 Workflow 6）
- **架构**: Nuxt.js/Vue 前端 → `catalog-admin.palexpo.ch` Django REST API 后端
- **端点**: `GET /index/exhibitors_for_website/{event_id}` 获取展商；`GET /index/segments_categories_formatted_for_website/` 获取分类/国家映射
- **认证绕过**: 设 `Referer` 和 `Origin` 头为前端域名（如 `https://www.indexnonwovens.com/`）即可绕过 JWT 登录
- **关键坑**: Python httpx/requests 直接访问 `catalog-admin.palexpo.ch` 会卡住，需用 curl 或浏览器上下文 fetch
