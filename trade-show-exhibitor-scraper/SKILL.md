---
name: trade-show-exhibitor-scraper
description: Scrape exhibitor data from trade show websites. Supports 10 architectures: GraphQL API (Reed Expo/NEPCON), Algolia Search API (NuernbergMesse/EUROGUSS), REST API with API Key (Messe Frankfurt), CMS/AJAX (electronica), VIS API (Messe Düsseldorf/drupa), Elementor Static HTML (FastenerExpo), Django REST API + Referer Bypass (INDEX/Palexpo), Canton Fair REST API, ActionChains Hover Infinite Scroll (Intersolar series), and JSON-LD Structured Data. Outputs Excel with Chinese exhibitors classified by region.
agent_created: true
---

# Trade Show Exhibitor Scraper

## Overview

This skill handles end-to-end scraping of trade show exhibitor directories, supporting ten major website architectures:

1. **GraphQL API** (NEPCON-style / Reed Expo) — Async httpx, cookie-based auth, high concurrency
2. **Algolia Search API** (EUROGUSS-style / NuernbergMesse Next.js) — Direct Algolia REST API, one-request fetch all, no auth needed
3. **REST API with API Key** (Light+Building-style / Messe Frankfurt) — Sync requests, API Key header auth, paginated
4. **CMS/AJAX** (electronica-style) — Playwright for list pages + httpx async for detail pages
5. **VIS API** (drupa/K-Online / Messe Düsseldorf) — Guest ticket + `X-Vis-Domain` header; `requests` directly
6. **Elementor Static HTML** (FastenerExpo) — `find_parent_container()` heading anchor method
7. **Django REST API + Referer Bypass** (INDEX/Palexpo) — `Referer`/`Origin` header bypass JWT
8. **Canton Fair REST API** (广交会) — `productShops/searchByVariables` + `shopExt/searchByVariables` two-step API
9. **ActionChains Hover Infinite Scroll** (Intersolar/Smarter E/ees/Power2Drive) — Selenium ActionChains mouse hover trigger lazy load
10. **JSON-LD Structured Data** — `<script type="application/ld+json">` zero-XPath extraction

## Workflow Decision Tree

```
Is there a direct API (check browser devtools network tab)?
├── YES → What kind?
│   ├── POST to algolianet.com or algolia.net     → Use "Workflow 4: Algolia Search API"
│   ├── POST with GraphQL query body              → Use "Workflow 1: GraphQL API"
│   ├── GET ?_rows=N&f_type=profile (vis-api)     → Use "Workflow 5: VIS API (Messe Düsseldorf)"
│   ├── POST productShops/searchByVariables       → Use "Workflow 8: Canton Fair REST API"
│   ├── POST /index/exhibitors_for_website/       → Use "Workflow 7: Django REST API + Referer Bypass"
│   └── GET with ?pageNumber=                     → Use "Workflow 3: REST API with API Key"
├── Static HTML with Elementor/WordPress?         → Use "Workflow 6: Elementor Static HTML"
├── Has <script type="application/ld+json">?      → Use "Workflow 10: JSON-LD Structured Data"
├── Lazy-loaded cards with hover effect?          → Use "Workflow 9: ActionChains Hover Infinite Scroll"
└── Server-rendered CMS/AJAX?                     → Use "Workflow 2: CMS/AJAX Workflow"
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

## Workflow 5: VIS API (Messe Düsseldorf)

**Use when**: Messe Düsseldorf 旗下展会（K-Online/K展、drupa、interpack、MEDICA、caravan-salon 等），使用 `vis-api` 前缀的 REST API，`ticket=g_u_e_s_t` 匿名访客访问。

### 架构特征
- API 域名: `https://www.{show}.com/vis-api/vis/v3/en/search`
- 认证方式: `ticket=g_u_e_s_t` URL参数（无需cookie/session）
- 必带 header: `X-Vis-Domain: www.{show}.com`（**大写 X**，大小写敏感）
- 必带 header: `User-Agent`（模拟浏览器）

### ⚠️ 防限流 — 必须串行抓取，禁止并行
- **严禁使用 `ThreadPoolExecutor`、`asyncio.gather` 或任何形式的并发** — 已实测并行会导致 API 限流返回非 JSON 响应
- 必须串行逐个请求，每 5 个请求后等待 0.5–1 秒
- 每个请求加 3 秒重试（`@retry(stop_max_attempt_number=3, wait_fixed=3000)`）
- 展会规模参考：K展 ~3200 家，drupa ~1600 家

### Step 1: 搜索 API（获取展商列表）

```python
import requests

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "X-Vis-Domain": "www.k-online.com",  # 替换为目标展会域名
}

# 获取总数量
url = "https://www.k-online.com/vis-api/vis/v3/en/search?_rows=1&_start=0&f_type=profile&ticket=g_u_e_s_t"
resp = requests.get(url, headers=HEADERS, timeout=30)
total = resp.json().get("meta", {}).get("total", 0)

# 分页获取（最多 100 条/页）
PAGE_SIZE = 100
all_docs = []
for start in range(0, total, PAGE_SIZE):
    url = f"https://www.k-online.com/vis-api/vis/v3/en/search?_rows={PAGE_SIZE}&_start={start}&f_type=profile&ticket=g_u_e_s_t"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    all_docs.extend(resp.json().get("docs", []))
    import time
    time.sleep(0.3)

# 每条 doc 含：
# - id: "profile=k2025.3004160" → exh = "k2025.3004160"（Profile API 需要）
# - exhName: "1 BLOW SAS"
# - exhSeoId: "FxyAD9wuS56RhFG6pwE5Yw"（详情页链接用）
# - location: "Hall 14 / B70"
```

### Step 2: Profile API（公司详情）

```python
from retrying import retry

@retry(stop_max_attempt_number=3, wait_fixed=3000)
def fetch_profile(exh_id):
    url = f"https://www.k-online.com/vis-api/vis/v1/en/exhibitors/{exh_id}/slices/profile?ticket=g_u_e_s_t"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}")
    return resp.json()
```

#### Profile 字段映射

| API 字段 | Excel 列 | 提取方式 |
|---|---|---|
| `name` | Company Name | `data.get("name", "")` |
| `email` | Email | `data.get("email", "")` |
| `getInTouchEmail` | Alt Email | `data.get("getInTouchEmail", "")` |
| `phone.phone` | Phone | `data.get("phone", {}).get("phone", "")` |
| `profileAddress.address[]` | Address | `"; ".join(str(a) for a in addrs if a)`（数组可能含 None） |
| `profileAddress.city` | City | `data["profileAddress"].get("city", "")` |
| `profileAddress.zip` | ZIP | `data["profileAddress"].get("zip", "")` |
| `profileAddress.country` | Country | `data["profileAddress"].get("country", "")` |
| `profileAddress.countryCode` | Country Code | `data["profileAddress"].get("countryCode", "")` |
| `links[type=link].link` | Website | 遍历 links 数组取第一个 `type=link` 的 link |
| `text` | Description | `re.sub(r'<[^>]+>', '', html)` strip HTML |
| `categories[].label` | Categories | 每个分类的 label，逗号拼接 |
| `categories[].hierarchy` | Category Path | `" > ".join(h.get("label","") for h in hierarchy)` |
| `locations[].{area,stand}` | Booth | Hall + Stand |
| `socialMedia[].{network,link}` | Social Media | LinkedIn, YouTube 等 |
| `businessData[].{title,values}` | Business Data | 销售额、员工数、成立年份 |
| `exhSeoId` | Detail URL | 构造 `https://www.{domain}/vis/v1/en/exhprofiles/{exhSeoId}` |

### Step 3: Contacts List API（联系人列表 — 仅姓名+职位）

```python
def fetch_contacts(exh_id):
    url = f"https://www.k-online.com/vis-api/vis/v1/en/exhibitors/{exh_id}/slices/contacts?parentModule=profile&parentModule=stand&ticket=g_u_e_s_t"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    return resp.json()
# 返回: [{"id": "contact=xxx", "firstName": "Olivier", "lastName": "Perche", "position": "Sales director"}]
# ⚠️ 不包含个人邮箱和电话！
```

### Step 4: Contact Detail API（联系人个人联系方式 — 额外请求）

```python
def fetch_contact_detail(exh_id, contact_id):
    url = f"https://www.k-online.com/vis-api/vis/v1/en/exhibitors/{exh_id}/slices/contacts/{contact_id}?ticket=g_u_e_s_t"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    return resp.json()

# 返回字段:
# fields: [{id: "first_name", values: ["Olivier"]}, {id: "phone", values: ["+33..."]}, ...]
info = {}
for f in detail.get("fields", []):
    vals = f.get("values", [])
    info[f["id"]] = vals[0] if vals else ""
# info 含: first_name, last_name, position, phone, email, department, gender
```

### Step 5: 批量串行抓取 + 断点续传

```python
import time, json

results = []
exh_ids = [doc.get("exh") for doc in all_docs]

for idx, exh_id in enumerate(exh_ids):
    try:
        profile = fetch_profile(exh_id)
        contacts = fetch_contacts(exh_id)

        parsed = parse_profile(profile, contacts)

        # 联系人详情（也串行）
        for contact in contacts or []:
            cid = contact.get("id")
            if cid:
                detail = fetch_contact_detail(exh_id, cid)
                # 合并 phone/email 到 contact

        parsed["region"] = classify_region(parsed)
        results.append(parsed)
    except Exception as e:
        logger.warning(f"[FAIL] {exh_id}: {e}")

    if idx % 5 == 0:
        time.sleep(0.5)
    # 每 10 家保存一次进度
    if idx % 10 == 0:
        with open("progress.json", "w") as f:
            json.dump(results, f, ensure_ascii=False)
```

### 常见问题
1. **Header 大小写敏感**: `X-Vis-Domain`（大写 X），不是 `x-vis-domain`
2. **直接用 requests 即可**: 已验证 requests 库可直接调用，无需 curl subprocess
3. **地址数组可能含 None**: join 前需 `str(a) for a in addrs if a` 过滤
4. **联系人个人联系方式需额外请求**: 列表 API 只返回姓名+职位，个人 phone/email 需额外调 `/contacts/{contactId}`
5. **断点续传**: 每个 exh_id 作为 key，每 10 家保存一次进度 JSON
6. **串行抓取性能参考**: K展 ~3200 家约 2.5–3 小时；drupa ~1600 家约 1.5 小时
7. **详情页链接**: `detailUrl = f"https://www.{domain}/vis/v1/en/exhprofiles/{exhSeoId}"`

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

## Workflow 8: Canton Fair REST API（广交会）

**适用**: 广交会官网 `cantonfair.org.cn`，使用两层 REST API 获取展商数据。

### Step 1: 识别架构

打开 devtools → Network → XHR。寻找以下特征的请求：
- `POST /productShops/searchByVariables` — 按行业类别搜索商店列表
- `POST /shopExt/searchByVariables?shopCode={id}` — 获取单个商店详细信息

### Step 2: Headers 配置

```python
HEADERS = {
    "User-Agent": "Mozilla/5.0 ...",
    "X-Requested-With": "XMLHttpRequest",
    "X-User-Lan": "zh-CN",
    "Referer": "https://www.cantonfair.org.cn/",
    "Cookie": "_authI=...; auth-server-sid=...; tgw_l7_route=..."  # 从浏览器复制
}
```

Cookie 需要在浏览器中登录后获取。

### Step 3: 分行业分页搜索

```python
import requests

# 行业分类映射
CATEGORIES = {
    "电子家电": {"categoryId": "xxx", "pageSize": 40, "pages": 50},
    "工业制造": {"categoryId": "yyy", "pageSize": 40, "pages": 50},
    # ... 7个行业
}

for cat_name, cfg in CATEGORIES.items():
    for page in range(cfg["pages"]):
        payload = {
            "categoryId": cfg["categoryId"],
            "page": page,
            "size": cfg["pageSize"],
        }
        resp = requests.post(
            "https://www.cantonfair.org.cn/api/productShops/searchByVariables",
            json=payload, headers=HEADERS, timeout=30
        )
        shops = resp.json()["_embedded"]["b2b:shops"]
        for shop in shops:
            shop_code = shop["shopCode"]
            # Step 4: 获取详情
```

### Step 4: 获取商店详情

```python
detail_resp = requests.post(
    f"https://www.cantonfair.org.cn/api/shopExt/searchByVariables?shopCode={shop_code}",
    json={}, headers=HEADERS, timeout=30
)
detail = detail_resp.json()
# 字段: fullAddress, contactName, phone, mobile, email, website, keywords
```

### Step 5: 字段提取（带容错）

```python
def safe_get(d, *keys, default=""):
    for k in keys:
        if isinstance(d, dict):
            d = d.get(k, {})
        else:
            return default
    return d if isinstance(d, str) else default

name = shop.get("companyName", "")
address = safe_get(shop, "address", "fullAddress")
contact = shop.get("contactName", "")
phone = shop.get("phone", "") or shop.get("mobile", "")
email = shop.get("email", "")
website = shop.get("website", "")
```

### 关键坑

1. **Cookie 时效性**：广交会 Cookie 约 2-4 小时过期，需重新登录获取
2. **两层 API 区别**：列表 API 返回基础字段，详情 API 返回 UDF 字段（企业类型/注册资本/企业规模等）
3. **行业 ID 需从页面抓取**：`categoryId` 会随届数变化，从页面 JS 或 Network 中获取

## Workflow 9: ActionChains Hover Infinite Scroll（Intersolar 系列）

**适用**: Intersolar / The Smarter E / ees Europe / Power2Drive 等同一展会平台。列表页使用 CSS `teaser-container condensed` 卡片，鼠标悬停触发懒加载。

### Step 1: 识别特征

- 列表页卡片 class 含 `teaser-container condensed`
- 页面无传统分页，鼠标滚动/悬停加载更多
- 详情页使用 `content-data-headline` 定位公司名称
- 平台域名模式: `{show}.de`（如 `intersolar.de`, `thesmartere.de`）

### Step 2: Selenium + ActionChains 配置

```python
from selenium import webdriver
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
import time

chrome_options = Options()
chrome_options.add_argument('--headless')
chrome_options.add_argument('--no-sandbox')
chrome_options.add_argument('--disable-gpu')
chrome_options.add_argument('--hide-scrollbars')
chrome_options.add_argument('blink-settings=imagesEnabled=false')

# 反检测：隐藏 webdriver 属性
chrome_options.add_argument('--disable-blink-features=AutomationControlled')
chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
chrome_options.add_experimental_option('useAutomationExtension', False)

wb = webdriver.Chrome(options=chrome_options)

# JS 注入：覆盖 navigator.webdriver
wb.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
    'source': 'Object.defineProperty(navigator, "webdriver", {get: () => undefined})'
})
```

### Step 3: ActionChains 悬停无限滚动

```python
from retrying import retry

@retry(stop_max_attempt_number=9, wait_fixed=5000)
def load_page(url):
    wb.get(url)
    time.sleep(5)

wb.get("https://www.intersolar.de/exhibitors")

# 悬停滚动触发懒加载（通常 30-50 次足够）
for _ in range(34):  # 循环次数根据展会规模调整
    try:
        elements = wb.find_elements(By.CSS_SELECTOR, ".teaser-container.condensed")
        if elements:
            last_elm = elements[-1]
            action = ActionChains(wb)
            action.move_to_element(last_elm).perform()
            time.sleep(1.5)
    except Exception:
        time.sleep(2)
```

### Step 4: 提取链接 + Requests 抓详情

```python
import requests
from lxml import etree

# 提取所有展商链接
cards = wb.find_elements(By.CSS_SELECTOR, ".teaser-container.condensed a")
url_list = list(set(card.get_attribute("href") for card in cards if card.get_attribute("href")))

# 详情页用 requests（无需 Selenium）
for url in url_list:
    resp = requests.get(url, headers={"User-Agent": "Mozilla/5.0 ..."}, timeout=30)
    html = etree.HTML(resp.text)
    
    name = html.xpath('//h5[text()="Individual company presentation"]/../preceding-sibling::*[1]//text()')
    address_parts = html.xpath('//b[contains(text(),"Address")]/../text()')
    phone = html.xpath('//b[contains(text(),"Phone")]/../text()')
    email = html.xpath('//a[contains(@href,"mailto:")]/@href')
    website = html.xpath('//b[contains(text(),"Website")]/../a/@href')
```

### 关键坑

1. **反检测必需**：平台检测 `navigator.webdriver`，不隐藏会封 IP
2. **悬停不是滚动**：`move_to_element` 不是 `scrollIntoView`，必须用 ActionChains
3. **悬停次数**：每个页面最多展示约1500个卡片，34次悬停可覆盖（intersolar 参考值）
4. **详情页用 requests**：详情页无 JS 渲染，用 requests 比 Selenium 快 10 倍
5. **平台通用性**：换展会只需改域名，其他代码不变（已验证 4 个展会）

## Workflow 10: JSON-LD Structured Data Extraction

**适用**: 详情页包含 `<script type="application/ld+json">` 结构化数据的任何展会。无需 XPath 逐个字段定位，一次解析拿到所有结构化信息。

**代表展会**: MEDICA、COMPAMED、部分 Messe Düsseldorf 展会。

### Step 1: 识别 JSON-LD

打开详情页 → 查看源代码 → 搜索 `application/ld+json`：

```html
<script type="application/ld+json">
{
  "@context": "http://schema.org",
  "@type": "Organization",
  "name": "ABC Company",
  "telephone": "+49 123 456789",
  "email": "info@abc.com",
  "url": "https://www.abc.com",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "Main Street 1",
    "postalCode": "12345",
    "addressLocality": "Berlin",
    "addressCountry": "Germany"
  },
  "employee": [
    {"@type": "Person", "name": "John Doe", "jobTitle": "Sales Manager",
     "email": "john@abc.com", "telephone": "+49 123 456780"}
  ]
}
</script>
```

### Step 2: XPath 提取 + JSON 解析

```python
from lxml import etree
import json

def extract_jsonld(html_text):
    """Extract and parse JSON-LD from HTML"""
    html = etree.HTML(html_text)
    scripts = html.xpath('//script[@type="application/ld+json"]/text()')
    for script in scripts:
        try:
            data = json.loads(script)
            if isinstance(data, dict) and data.get("@type") == "Organization":
                return data
        except json.JSONDecodeError:
            continue
    return None

# Usage
resp = requests.get(detail_url, headers=HEADERS, timeout=30)
ld = extract_jsonld(resp.text)
if ld:
    name = ld.get("name", "")
    phone = ld.get("telephone", "")
    email = ld.get("email", "")
    website = ld.get("url", "")
    
    addr = ld.get("address", {})
    street = addr.get("streetAddress", "")
    city = addr.get("addressLocality", "")
    country = addr.get("addressCountry", "")
    postal = addr.get("postalCode", "")
    
    # 提取员工信息
    employees = ld.get("employee", [])
    contacts = "; ".join(
        f"{e.get('name')} ({e.get('jobTitle')})" 
        for e in (employees or [])
    )
```

### Step 3: 与 API 结合使用

JSON-LD 通常作为补充数据源，与 VIS API 配合：
- VIS API → 获取公司级别字段（name, email, phone, address, categories）
- JSON-LD → 获取 `employee[]` 详细信息（比 contacts API 更丰富）

### 关键坑

1. **JSON-LD 可能不完整**：部分字段缺失是常态，每个字段都要 `.get(key, "")`
2. **多 script 标签**：页面可能有多个 `ld+json`，只取 `@type=Organization` 的那个
3. **employee 格式差异**：不同展会的 employee 字段嵌套层级不同，需检查实际结构

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

Two options. Option A — `retrying` (更简洁，推荐):

```python
from retrying import retry

@retry(stop_max_attempt_number=5, wait_fixed=3000)  # 最多5次，间隔3秒
def fetch_page(url, headers):
    resp = requests.get(url, headers=headers, timeout=10)
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}")
    return resp
```

Option B — `tenacity` (更灵活):

```python
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type

@retry(stop=stop_after_attempt(3), wait=wait_fixed(10),
       retry=retry_if_exception_type((ConnectionError, Timeout)))
def robust_request(url, **kwargs):
    return requests.get(url, timeout=15, **kwargs)
```

### Multi-Threading Patterns

Three patterns for high-volume detail page scraping, ordered by complexity:

**Pattern A: ThreadPoolExecutor (推荐，最简洁)**

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

def fetch_detail(url):
    resp = requests.get(url, headers=HEADERS, timeout=30)
    return parse_detail(resp.text)

with ThreadPoolExecutor(max_workers=50) as executor:
    futures = {executor.submit(fetch_detail, url): url for url in url_list}
    for future in as_completed(futures):
        try:
            result = future.result()
            results.append(result)
        except Exception as e:
            logger.warning(f"Failed: {futures[future]}: {e}")
```

**Pattern B: threading.Thread + BoundedSemaphore (手动限流)**

```python
import threading

sem = threading.BoundedSemaphore(5)  # 最多5并发

def fetch_with_limit(url):
    sem.acquire()
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        return parse_detail(resp.text)
    finally:
        sem.release()

threads = []
for url in url_list:
    t = threading.Thread(target=fetch_with_limit, args=(url,))
    t.start()
    threads.append(t)
for t in threads:
    t.join()
```

**Pattern C: 数字ID遍历 + 多线程 (无序列表页时使用)**

```python
# 当网站按数字ID排列展商，可以直接遍历ID范围
# 如俄羅斯展會: stand_id 6034~150000
for stand_id in range(6034, 150001):
    url = f"https://catalog.expocentr.ru/stand/{stand_id}"
    executor.submit(fetch_detail, url)
```

### JSON-LD Quick Reference

Always configure dual logging (file + console) for long-running scrapes:

```python
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.FileHandler("scrape.log", encoding='utf-8'),
              logging.StreamHandler()]
)
```

### JSON-LD Quick Reference

When detail pages contain `<script type="application/ld+json">`, prefer JSON-LD over XPath. One-shot extraction of all structured fields:

```python
from lxml import etree
import json

def extract_jsonld(html_text):
    html = etree.HTML(html_text)
    for script in html.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            data = json.loads(script)
            if data.get("@type") == "Organization":
                return {
                    "name": data.get("name", ""),
                    "phone": data.get("telephone", ""),
                    "email": data.get("email", ""),
                    "website": data.get("url", ""),
                    "address": data.get("address", {}).get("streetAddress", ""),
                    "city": data.get("address", {}).get("addressLocality", ""),
                    "country": data.get("address", {}).get("addressCountry", ""),
                    "employees": [
                        {"name": e.get("name"), "title": e.get("jobTitle"),
                         "email": e.get("email"), "phone": e.get("telephone")}
                        for e in (data.get("employee") or [])
                    ]
                }
        except json.JSONDecodeError:
            continue
    return None
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
- `scripts/reference_konline.py` — K-Online VIS API approach (Messe Düsseldorf)

## Common Pitfalls

1. **C: drive full** — Set `PLAYWRIGHT_BROWSERS_PATH`, `TEMP`, `TMP` to D: drive
2. **Double-encoded JSON** — playwright-cli `--raw` output needs `json.loads(json.loads(data))`
3. **`<a>` tag extraction** — for nested divs, always extract from `<a>` tags, not `</div>` boundaries
4. **AJAX lazy loading** — must scroll to bottom to trigger all items
5. **Mixed locale countries** — country names can be in Japanese/Chinese/English; classification must search all text fields
6. **API key expiry** — use `allow_redirects=False` to detect 302 redirect (Messe Frankfurt sends you to login page when key expires)
7. **Rate limiting** — REST APIs often have anti-scraping thresholds; always add 1.5–3s random delay between pages
8. **VIS API requests 卡住？检查 header**：不是 `requests` 库本身的问题——关键是 `X-Vis-Domain` header（大写 X）+ `User-Agent`。缺失任一都会失败。

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

### FastenerExpo 2026 — Elementor 标题定位父容器提取法（新增 Elementor 静态 HTML 提取法）
- **适用**: 静态 HTML (Elementor/WordPress)，字段无 class/id，嵌套 `<div>` 无分隔标记
- **核心方案**: `extract_field(soup, heading_text)` — 找到标题元素 → 逐级上溯父容器 → 取第一个文本长度超过标题的容器 → 去掉标题得值
- **原因**: `find_next()` 遍历 DOM 会导致字段交叉污染（Booth 含 Country，Country 含 Type）；正则切分无分隔符不可靠。103/103 (100%) 成功

### INDEX26 2026 — Django REST API + Referer 认证绕过（新增 Django REST + Referer 绕过法）
- **架构**: Nuxt.js/Vue 前端 → `catalog-admin.palexpo.ch` Django REST API 后端
- **端点**: `GET /index/exhibitors_for_website/{event_id}` 获取展商；`GET /index/segments_categories_formatted_for_website/` 获取分类/国家映射
- **认证绕过**: 设 `Referer` 和 `Origin` 头为前端域名（如 `https://www.indexnonwovens.com/`）即可绕过 JWT 登录
- **关键坑**: Python httpx/requests 直接访问 `catalog-admin.palexpo.ch` 会卡住，需用 curl 或浏览器上下文 fetch

### K-Online K2025 — Messe Düsseldorf VIS API + Guest Ticket（已合并为正式 Workflow 5）

K-Online VIS API 内容已整合到上方的 **Workflow 5: VIS API (Messe Düsseldorf)** 完整工作流中，包含搜索 API、Profile API、Contacts API、Contact Detail API、断点续传等完整步骤。详细内容见上方正文。

## 经验更新 2026-06-09

### drupa 2024 — VIS API 实战参考

- **`requests` 库直接可用**：正确设置 `X-Vis-Domain`（大写 X）+ `User-Agent` 即可，无需 curl subprocess
- **drupa 2024 规模参考**：1630 家展商（含中国约 200+），单线程串行抓取约 1.5–2 小时完成
- **`retrying` 库替代 `tenacity`**：`retrying.retry(stop_max_attempt_number=N, wait_fixed=MS)` 更简洁
- **详细步骤见上方 Workflow 5**

### 用户爬虫文件夹学习总结

- **代码模板复用度高**：`infocomm.py/ISe.py/塑胶展.py` 共享同一 Selenium+Requests 模板；`光伏/智能欧洲/电力基础/电池展` 四文件几乎完全相同（同平台，仅域名不同）
- **广交会三层架构**：Selenium 登录型（广交会.py，含 Cookie 持久化 + 滑块验证）→ 纯 API 型（广交会2023.py/广交会re,py.py，两层 REST API）
- **JSON-LD 补充 VIS API**：K展.py（MEDICA）同时使用 VIS API 获取列表 + JSON-LD 获取详情（含 employee 数组）
- **多线程策略分化**：`ThreadPoolExecutor(50)` 用于数字ID遍历（俄羅斯展會），`BoundedSemaphore(5)` 用于可控并发（慕尼黑电子），`threading.Thread` 手动管理（EXCEL分类）
- **地区分类进化**：初代用 `+86` 判断中国 → 二代用区号 `755/20` 分深圳/广东 → 三代用城市名正则匹配（阿里测试.py 用 22 个广东城市英文+拼音）
- **Selenium 反检测积累**：`navigator.webdriver` 隐藏、`useAutomationExtension=False`、`Page.addScriptToEvaluateOnNewDocument` CDP 注入

## 经验更新 2026-06-10

### glasstec 2026 — VIS API 实战参考（883 家展商）

- **规模参考**：883 家展商（含 215 家中国展商），串行抓取约 25 分钟完成
- **搜索 API 参数不同**：glasstec 使用 `oid=18262` 作为事件 ID 参数（不同于 K展和 drupa 的纯 f_type=profile），URL: `vis-api/vis/v3/en/search?_rows=N&_start=0&f_type=profile&oid=18262&ticket=g_u_e_s_t`
- **Profile API 无 text/businessData 字段**：glasstec 的 Profile API（`vis-api/vis/v1/en/exhibitors/{exh_id}/slices/profile`）不返回公司描述（text）和业务数据（businessData），只有名称、地址、联系方式、分类和展位
- **联系人数据极少**：测试发现大多数展商没有联系人数据，少数有 1 个
- **分类层级完整**：categories 字段含 hierarchy 数组，可拼接完整分类路径（如 "Glass processing and finishing > Laser technology > Laser cutting technology"）

### 自动化断点续传脚本模板（适用于所有 VIS API 展会）

```python
# 核心模板 — 串行抓取 + retry + 断点续传
import requests, json, time, re, os, logging
from retrying import retry

DOMAIN = "www.glasstec-online.com"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ...",
    "X-Vis-Domain": DOMAIN,
}
PROGRESS_FILE = "exhibitors_progress.json"
RESULT_FILE = "exhibitors_all.json"

@retry(stop_max_attempt_number=3, wait_fixed=3000)
def fetch_profile(exh_id):
    url = f"https://{DOMAIN}/vis-api/vis/v1/en/exhibitors/{exh_id}/slices/profile?ticket=g_u_e_s_t"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}")
    return resp.json()

# 分页获取列表
BASE_URL = f"https://{DOMAIN}/vis-api/vis/v3/en/search"
total = requests.get(f"{BASE_URL}?_rows=1&_start=0&f_type=profile&oid=18262&ticket=g_u_e_s_t", headers=HEADERS).json()["meta"]["total"]
all_docs = []
for start in range(0, total, 100):
    url = f"{BASE_URL}?_rows=100&_start={start}&f_type=profile&oid=18262&ticket=g_u_e_s_t"
    resp = requests.get(url, headers=HEADERS)
    all_docs.extend(resp.json()["docs"])
    time.sleep(0.3)

# 串行抓取详情（每5个请求暂停0.5s，每10家保存进度）
results = json.load(open(PROGRESS_FILE)) if os.path.exists(PROGRESS_FILE) else {}
for idx, doc in enumerate(all_docs):
    exh_id = doc["exh"]
    if exh_id in results:
        continue
    results[exh_id] = fetch_profile(exh_id)  # 含parse/sanitize逻辑
    if (idx + 1) % 5 == 0:
        time.sleep(0.5)
    if (idx + 1) % 10 == 0:
        json.dump(results, open(PROGRESS_FILE, "w"), ensure_ascii=False)
```

### Excel 区域分类（保持原有逻辑不变）

**⚠️ 硬性规则：禁止随意变更分类逻辑！**
分类优先级顺序固定为：**Shenzhen → Xiamen → Guangdong → Fujian → China Other → Overseas**
- 未经用户明确指示，不得新增/删除/重排任何分类层级
- 不得引入省份级细分（如 Zhejiang、Jiangsu、Shandong 等）
- 如需调整（如新增城市到现有分类正则），必须先问用户确认
- Taiwan(China) 和 Hong Kong(China) 单独分类，独立于上述 China/Overseas 逻辑

广东城市正则包含（可扩展，但需先问用户）：
dongguan/huizhou/guangzhou/zhongshan/foshan/shunde/zhuhai/zhaoqing 等。
