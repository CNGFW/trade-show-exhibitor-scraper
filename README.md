# trade-show-exhibitor-scraper

展会参展商数据抓取工具 — 支持 NEPCON Japan、electronica、Light+Building、EUROGUSS 等展会。

## 支持的数据源架构

1. **GraphQL API**（Reed Expo / NEPCON 系）— 异步 httpx + Cookie 认证
2. **Algolia Search API**（NuernbergMesse Next.js 系，如 EUROGUSS）— 直接调用 Algolia REST API
3. **REST API + API Key**（Messe Frankfurt 系，如 Light+Building）— 同步分页请求
4. **CMS/AJAX**（electronica 系）— Playwright 列表页 + httpx 异步详情页

## 输出

按区域分类的 Excel 工作表（含 Summary 汇总页）+ JSON 备份。
