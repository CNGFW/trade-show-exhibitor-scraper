import re
import json
import time
import random
import logging
import requests
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type
import openpyxl
from openpyxl.utils import get_column_letter

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("exhibitor_crawler.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# === 精确配置（使用您提供的官方端点）===
CONFIG = {
    "API_ENDPOINT": "https://api.messefrankfurt.com/service/esb_api/exhibitor-service/api/2.1/public/exhibitor/search",
    "API_KEY": "LXnMWcYQhipLAS7rImEzmZ3CkrU033FMha9cwVSngG4vbufTsAOCQQ==",  # 从浏览器开发者工具获取
    "HEADERS": {
        "accept": "application/json",
        "accept-language": "en-GB,en;q=0.9",
        "apikey": "LXnMWcYQhipLAS7rImEzmZ3CkrU033FMha9cwVSngG4vbufTsAOCQQ==",
        "origin": "https://light-building.messefrankfurt.com",
        "referer": "https://light-building.messefrankfurt.com/",
        "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    },
    "PARAMS": {
        "language": "en-GB",
        "q": "",
        "orderBy": "name",
        "pageSize": 30,
        "orSearchFallback": "false",
        "showJumpLabels": "true",
        "findEventVariable": "LIGHTBUILDING"
    },
    "MAX_PAGES": 64,  # 根据实际页数调整
    "OUTPUT_DIR": "E:/OneDrive/企业号/展会数据/26年展会抓取/",
    "OUTPUT_FILE": "L+B_参展商数据.xlsx",
    "MAX_RETRIES": 3,
    "REQUEST_TIMEOUT": 15  # 秒
}

# === 地区分类正则（保持原逻辑）===
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

class Exhibitor:
    """结构化参展商数据"""
    def __init__(self, raw_data: Dict):
        exhibitor = raw_data.get("exhibitor", {})
        address = exhibitor.get("address", {})
        
        # 基础信息
        self.name = self._clean(exhibitor.get("name", ""))
        self.street = self._clean(address.get("street", ""))
        self.city = self._clean(address.get("city", ""))
        self.zipcode = self._clean(address.get("zip", ""))
        self.country = self._clean(address.get("country", {}).get("label", ""))
        
        # 联系方式
        self.tel = self._clean(address.get("tel", ""))
        self.fax = self._clean(address.get("fax", ""))
        self.email = self._clean(address.get("email", ""))
        self.homepage = self._clean(exhibitor.get("homepage", ""))
        
        # 其他信息
        self.keywords = self._clean(", ".join(exhibitor.get("keyWords", [])))
        
        # 详情页URL
        links = exhibitor.get("presentationLinks", [])
        self.url = ""
        if links and isinstance(links, list) and len(links) > 0:
            rewrite = links[0].get("exhibitorUrlRewrite", "")
            if rewrite:
                self.url = f"https://light-building.messefrankfurt.com/frankfurt/en/exhibitor-search.detail.html/{rewrite}.html"
        
        # 自动分类
        self.region = self._classify_region()
    
    def _clean(self, text: str | List) -> str:
        """清理文本，处理各种边缘情况"""
        if isinstance(text, list):
            text = ", ".join(str(t) for t in text if t)
        if not text:
            return ""
        
        # 多重清理
        text = str(text)
        text = re.sub(r'<[^>]+>', '', text)  # 移除HTML标签
        text = re.sub(r'&[a-z0-9]+;', '', text)  # 移除HTML实体
        text = re.sub(r'\s+', ' ', text).strip()  # 合并空格
        text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)  # 移除控制字符
        return text
    
    def _classify_region(self) -> str:
        """精准地区分类"""
        combined = f"{self.name} {self.street} {self.city} {self.zipcode} {self.country}{self.tel}{self.fax}{self.email}{self.homepage}{self.keywords}"
        
        # 优先级顺序：具体城市 > 省份 > 国家 > 其他
        if REGION_PATTERNS["shenzhen"].search(combined):
            return "shenzhen"
        if REGION_PATTERNS["xiamen"].search(combined):
            return "xiamen"
        if REGION_PATTERNS["guangdong"].search(combined):
            return "guangdong"
        if REGION_PATTERNS["fujian"].search(combined):
            return "fujian"
        if CHINA_PATTERN.search(combined):
            return "china"
        return "other"
    
    def to_tuple(self) -> Tuple:
        """转换为Excel可写入的元组"""
        return (
            self.name, self.street, self.city, self.zipcode, self.country,
            self.tel, self.fax, self.email, self.homepage, self.keywords, self.url, self.region
        )
    
    def __str__(self) -> str:
        return f"{self.name} ({self.city}, {self.country})"

@retry(
    stop=stop_after_attempt(CONFIG["MAX_RETRIES"]),
    wait=wait_fixed(10),
    retry=retry_if_exception_type((
        requests.exceptions.ConnectionError,
        requests.exceptions.Timeout,
        requests.exceptions.HTTPError
    )),
    reraise=True
)
def fetch_exhibitors_page(page_number: int) -> Optional[Dict]:
    """
    精准请求官方API端点，获取单页数据
    返回: API响应JSON，失败时返回None
    """
    params = CONFIG["PARAMS"].copy()
    params["pageNumber"] = page_number
    
    try:
        logger.info(f"▶ 请求第 {page_number} 页数据 (URL: {CONFIG['API_ENDPOINT']})")
        response = requests.get(
            CONFIG["API_ENDPOINT"],
            headers=CONFIG["HEADERS"],
            params=params,
            timeout=CONFIG["REQUEST_TIMEOUT"],
            allow_redirects=False  # 禁用重定向，直接处理
        )
        
        # 检查重定向
        if 300 <= response.status_code < 400:
            location = response.headers.get('Location', 'N/A')
            logger.error(f"🚫 检测到重定向! 状态码: {response.status_code}, Location: {location}")
            raise requests.exceptions.TooManyRedirects(
                f"API 返回重定向 (状态码 {response.status_code})，目标: {location}"
            )
        
        # 检查HTTP错误
        response.raise_for_status()
        
        # 验证JSON结构
        data = response.json()
        if not data.get("result") or not data["result"].get("hits"):
            logger.warning(f"⚠ 第 {page_number} 页返回空数据集 (状态码: {response.status_code})")
            return None
        
        logger.info(f"✓ 成功获取第 {page_number} 页，共 {len(data['result']['hits'])} 条记录")
        return data
    
    except requests.exceptions.TooManyRedirects as e:
        logger.critical(f"❌ 重定向错误: {str(e)}")
        raise  # 不重试重定向错误
    
    except requests.exceptions.RequestException as e:
        logger.error(f"✗ 第 {page_number} 页请求失败: {str(e)}")
        if hasattr(e, 'response') and e.response is not None:
            logger.debug(f"  响应内容: {e.response.text[:500]}")
        raise
    
    except ValueError as e:
        logger.error(f"✗ JSON解析失败 (第 {page_number} 页): {str(e)}")
        logger.debug(f"  响应内容: {response.text[:500]}")
        raise

def process_api_response(api_data: Dict) -> List[Exhibitor]:
    """处理API响应，转换为Exhibitor对象列表"""
    exhibitors = []
    hits = api_data.get("result", {}).get("hits", [])
    
    for item in hits:
        try:
            exhibitor = Exhibitor(item)
            exhibitors.append(exhibitor)
        except Exception as e:
            logger.warning(f"⚠ 跳过无效数据项: {str(e)}")
            continue
    
    return exhibitors

def save_to_excel(data_by_region: Dict[str, List[Exhibitor]], output_path: str):
    """将分类数据保存到Excel文件"""
    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # 移除默认工作表
    
    # 工作表配置
    sheet_config = [
        ("原始数据", "all_data"),
        ("中国", "china"),
        ("深圳", "shenzhen"),
        ("厦门", "xiamen"),
        ("广东", "guangdong"),
        ("福建", "fujian"),
        ("其他", "other")
    ]
    
    headers = ["公司名称", "街道", "城市", "邮编", "国家", "电话", "传真", 
               "邮箱", "主页", "关键词", "详情链接", "区域分类"]
    
    for sheet_name, region_key in sheet_config:
        if region_key == "all_data":
            data = [item for items in data_by_region.values() for item in items]
        else:
            data = data_by_region.get(region_key, [])
        
        if not data:
            continue
        
        ws = wb.create_sheet(title=sheet_name)
        ws.append(headers)
        
        for exhibitor in data:
            ws.append(exhibitor.to_tuple())
        
        # 自动调整列宽
        for col_idx in range(1, len(headers) + 1):
            column = get_column_letter(col_idx)
            max_length = 0
            for row in ws[column]:
                if row.value:
                    max_length = max(max_length, len(str(row.value)))
            adjusted_width = min(max(10, max_length + 2), 50)  # 限制最大宽度
            ws.column_dimensions[column].width = adjusted_width
    
    # 保存文件
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    logger.info(f"✓ Excel文件已保存: {output_path}")

def main():
    """主流程：采集 → 分类 → 保存"""
    logger.info("="*60)
    logger.info("🚀 Light+Building 2026 参展商数据采集启动")
    logger.info(f"🔗 API端点: {CONFIG['API_ENDPOINT']}")
    logger.info(f"📄 采集页数: 1-{CONFIG['MAX_PAGES']}")
    logger.info("="*60)
    
    # 初始化数据容器
    all_data = {
        "shenzhen": [], "xiamen": [], "guangdong": [], 
        "fujian": [], "china": [], "other": []
    }
    total_count = 0
    
    # 逐页采集
    for page in range(1, CONFIG["MAX_PAGES"] + 1):
        try:
            # 获取API数据
            api_data = fetch_exhibitors_page(page)
            if not api_data:
                logger.warning(f"⚠ 第 {page} 页无有效数据")
                continue
            
            # 处理数据
            exhibitors = process_api_response(api_data)
            logger.info(f"✅ 第 {page} 页成功处理 {len(exhibitors)} 家参展商")
            
            # 分类存储
            for exhibitor in exhibitors:
                all_data[exhibitor.region].append(exhibitor)
                total_count += 1
            
        except Exception as e:
            logger.error(f"✗ 第 {page} 页处理失败: {str(e)}")
            if "401" in str(e) or "Unauthorized" in str(e):
                logger.critical("🔑 API密钥失效！请更新CONFIG['API_KEY']")
                break
            # 非关键错误继续执行
        
        # 防风控延迟
        if page < CONFIG["MAX_PAGES"]:
            delay = 1.5 + random.uniform(0.5, 1.5)
            logger.info(f"⏳ 等待 {delay:.1f} 秒后请求下一页...")
            time.sleep(delay)
    
    # 生成报告
    if total_count == 0:
        logger.error("❌ 未采集到任何有效数据！请检查API密钥和网络连接")
        return
    
    # 保存Excel
    output_path = Path(CONFIG["OUTPUT_DIR"]) / CONFIG["OUTPUT_FILE"]
    save_to_excel(all_data, str(output_path))
    
    # 打印统计
    logger.info("\n" + "="*60)
    logger.info("📊 采集结果统计:")
    logger.info(f"   总计: {total_count} 家参展商")
    for region, items in all_data.items():
        if items:
            region_name = {
                "shenzhen": "深圳", "xiamen": "厦门", 
                "guangdong": "广东", "fujian": "福建",
                "china": "中国(其他)", "other": "海外"
            }.get(region, region)
            logger.info(f"   • {region_name:10s}: {len(items):4d} 家 ({len(items)/total_count:.1%})")
    logger.info("="*60)
    logger.info("🎉 采集任务圆满完成！")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("\n⚠ 用户中断执行")
    except Exception as e:
        logger.critical(f"❌ 程序异常终止: {str(e)}", exc_info=True)
    finally:
        logger.info("🔚 程序结束")