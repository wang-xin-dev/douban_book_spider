"""
爬虫核心模块 —— 豆瓣高分图书数据抓取
=========================================
负责发送 HTTP 请求、解析 HTML 页面、提取结构化字段数据。

核心技术栈：
    requests      - 发送网络请求，获取网页内容
    BeautifulSoup - 解析 HTML，像操作 DOM 树一样提取数据
    re            - 正则表达式，用于从文本中提取数字等信息

抓取流程（由 main.py 驱动）：
    1. 构建请求URL（含分页参数）
    2. 发送 GET 请求（带 User-Agent 伪装浏览器）
    3. 检查响应状态码 → 成功则解析 HTML
    4. 找到所有图书条目（class="doulist-item"）
    5. 逐个提取：书名、作者、出版社、出版日期、定价、评分、评价人数、简介
    6. 每页之间等待 1.5 秒（爬虫礼仪）

使用示例：
    >>> from spider import DoubanBookSpider
    >>> spider = DoubanBookSpider()
    >>> books = spider.crawl_all_pages()
    >>> print(f"共抓取 {len(books)} 本图书数据")

安全合规声明：
    - 只抓取网页公开可见数据
    - 不登录、不提交表单、不抓取需要权限的内容
    - 请求头不包含任何 Cookie / Token / 密钥
    - 每次请求间隔 1.5 秒，降低服务器压力
"""

# ---------- 标准库 ----------
import re                          # 正则表达式：从文本中提取数字、清洗字符串
import sys                         # 系统相关：处理输出编码问题
import time                        # 时间控制：实现请求间隔延时
from typing import Optional        # 类型注解：兼容 Python 3.9- 的 Optional[X] 写法

# ---------- 修复 Windows GBK 编码问题 ----------
# Windows 终端默认使用 GBK 编码，而豆瓣数据中包含 Unicode 特殊字符
# 将 stdout 替换为支持 replace 策略的包装器，避免 print 崩溃
# 只替换一次，避免多次替换导致 "I/O operation on closed file"
if sys.platform == "win32" and sys.stdout.encoding != "utf-8":
    import io
    try:
        sys.stdout = io.TextIOWrapper(
            sys.stdout.buffer,
            encoding="utf-8",
            errors="replace",
        )
    except (ValueError, AttributeError):
        pass  # 已经被替换过了

# ---------- 第三方库 ----------
import requests                    # HTTP 客户端：发送网络请求，获取网页内容
from bs4 import BeautifulSoup      # HTML 解析器：将网页源码转为可查询的 DOM 树

# ---------- 项目内部模块 ----------
import config                      # 统一配置文件：读取所有可调参数


class DoubanBookSpider:
    """
    豆瓣高分图书爬虫

    设计思路：
        将爬虫封装为一个类，所有功能内聚在一起。
        外部只需创建实例 → 调用 crawl_all_pages() → 拿到数据列表。
        每个私有方法（以 _ 开头）负责一个独立的小任务，便于维护和测试。

    核心方法一览：
        _fetch_page()         - 发送 HTTP 请求，获取页面 HTML 源码
        _parse_book_items()   - 从 HTML 中找出所有图书条目
        _parse_single_book()  - 从单个条目中提取 8 个字段
        _parse_info_line()    - 解析「作者/出版社/日期/定价」这一行
        _extract_rating()     - 专门提取评分
        _extract_rating_count() - 专门提取评价人数
        _extract_abstract()   - 专门提取简介
        crawl_page()          - 爬取单页数据
        crawl_all_pages()     - 爬取所有页（主入口）
    """

    def __init__(self):
        """
        初始化爬虫实例

        从 config.py 中读取所有配置参数并保存到实例属性中。
        这样做的好处：
            1. 修改配置只需改 config.py，不用动爬虫代码
            2. 每个实例可以有不同的配置（虽然通常用默认值就够了）
            3. 代码中不会出现硬编码的魔法数字
        """
        self.base_url    = config.BASE_URL          # 目标榜单 URL
        self.headers     = config.HEADERS           # 请求头（模拟浏览器）
        self.timeout     = config.REQUEST_TIMEOUT   # 请求超时上限（秒）
        self.delay       = config.REQUEST_DELAY     # 请求间隔（秒）
        self.max_retries = config.MAX_RETRIES       # 失败重试次数

    # ================================================================
    # 第一部分：网络请求层
    # 负责与豆瓣服务器通信，获取原始 HTML 页面
    # ================================================================

    def _fetch_page(self, url: str, start: int = 0) -> Optional[str]:
        """
        发送 GET 请求，获取指定页面的 HTML 源码

        参数:
            url   : 目标页面 URL（如豆瓣豆列地址）
            start : 分页偏移量（豆瓣用这个参数翻页，0=第1页, 25=第2页, 50=第3页）

        返回:
            成功 → 网页 HTML 文本（字符串）
            失败 → None（网络超时、被封、解析失败等）

        容错机制：
            1. 支持自动重试（最多 max_retries 次）
            2. 每次重试等待递增时间（避免连续撞击服务器）
            3. 区分不同异常类型给出明确提示
            4. 特殊处理 418 状态码（豆瓣的反爬标志）
        """
        # ---- 构建查询参数 ----
        # 第1页不需要传参数（start=0 时豆瓣默认返回第一页）
        # 从第2页开始需要传 start 和 sort 参数
        if start > 0:
            params = {
                "start":    start,   # 偏移量：0/25/50/75...
                "sort":     "seq",   # 排序方式：seq=按添加顺序
                "sub_type": "",      # 子类型：空=全部
            }
        else:
            params = {}              # 第1页用空参数即可

        # ---- 重试循环 ----
        # 如果第1次请求失败，会自动重试最多 max_retries 次
        for attempt in range(1, self.max_retries + 1):

            try:
                # ① 发送 GET 请求
                #    headers 参数让我们伪装成浏览器
                #    timeout 参数防止请求永远挂起
                resp = requests.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=self.timeout,
                )

                # ② 检查 HTTP 状态码
                #    200 = 成功，直接返回 HTML 内容
                #    418 = 豆瓣的「I'm a teapot」反爬虫响应
                #    其他 = 未知错误
                if resp.status_code == 200:
                    # 请求成功！返回 HTML 文本内容
                    return resp.text

                elif resp.status_code == 418:
                    # 豆瓣用 418 表示检测到爬虫行为
                    # 等更长时间再试（正常延时的2倍）
                    print(
                        f"[警告] 第{attempt}次请求被反爬拦截（状态码418），"
                        f"等待 {self.delay * 2} 秒后重试..."
                    )
                    time.sleep(self.delay * 2)

                else:
                    # 其他异常状态码（如 403 禁止访问、500 服务器错误等）
                    print(f"[警告] 第{attempt}次请求返回状态码: {resp.status_code}")

            # ③ 捕获各种网络异常
            except requests.exceptions.Timeout:
                # 连接/读取超时：服务器响应太慢或网络不好
                print(f"[错误] 第{attempt}次请求超时（{self.timeout}秒）")

            except requests.exceptions.ConnectionError:
                # DNS 解析失败、网络断开、代理问题等
                print(f"[错误] 第{attempt}次请求连接失败，请检查网络")

            except requests.exceptions.RequestException as e:
                # 其他所有 requests 库可能抛出的异常
                print(f"[错误] 第{attempt}次请求异常: {e}")

            # ④ 如果不是最后一次尝试，等待后重试
            #    等待时间逐次递增：第1次等1.5秒，第2次等3秒
            if attempt < self.max_retries:
                time.sleep(self.delay * attempt)

        # ⑤ 所有重试都失败了
        print(f"[失败] 请求最终失败，URL: {url}")
        return None

    # ================================================================
    # 第二部分：HTML 解析层
    # 负责将 HTML 源码拆解为结构化的图书数据
    # ================================================================

    def _parse_book_items(self, html: str) -> list:
        """
        从 HTML 源码中找出所有图书条目

        豆瓣豆列的 HTML 结构：
            <div class="doulist-item">    ← 每个图书条目
                <div class="title">...</div>     ← 书名
                <div class="abstract">...</div>  ← 作者/出版社/简介
                <div class="rating">...</div>    ← 评分区域
            </div>

        参数:
            html : 完整的页面 HTML 源码

        返回:
            BeautifulSoup Tag 对象列表，每个 Tag 代表一本图书的条目
        """
        # 创建 BeautifulSoup 解析对象
        # 使用 lxml 作为底层解析器（比 Python 内置的 html.parser 更快更稳定）
        soup = BeautifulSoup(html, "lxml")

        # 找到所有 class="doulist-item" 的 div 元素
        # 每个这样的 div 就是一本书的完整信息块
        items = soup.find_all("div", class_="doulist-item")

        return items

    def _extract_text(self, element, selector: str, default: str = "") -> str:
        """
        通用方法：安全地从元素中提取文本

        这是一个工具函数，被其他提取方法调用。
        它的作用是：无论提取成功还是失败，都不会抛出异常。

        参数:
            element  : BeautifulSoup 元素（父节点）
            selector : CSS 选择器（如 ".title a"）或标签名（如 "span"）
            default  : 提取失败时返回的默认值

        返回:
            提取到的文本（已自动去除首尾空白），失败则返回 default

        智能判断：
            如果 selector 包含 . 或 # → 当作 CSS 选择器处理
            否则 → 当作标签名处理（兼容老式写法）
        """
        try:
            # 判断是 CSS 选择器还是简单标签名
            is_css = any(char in selector for char in (" ", ".", "#"))

            if is_css:
                # CSS 选择器模式：如 ".title a" 表示 class="title" 下的 <a> 标签
                found = element.select_one(selector)
            else:
                # 标签名模式：如 "span" 表示找到第一个 <span> 标签
                found = element.find(selector)

            if found:
                # get_text(strip=True) 会提取纯文本并自动去除首尾空白
                return found.get_text(strip=True)

        except Exception:
            # 任何异常都吞掉，返回默认值
            # 这样不会因为一个字段解析失败而影响整本书的数据
            pass

        return default

    def _extract_rating(self, element) -> str:
        """
        提取豆瓣评分

        豆瓣豆列页面中，评分通常存储在：
            <span class="rating_nums">9.2</span>

        参数:
            element : 单个图书条目的 BeautifulSoup 元素

        返回:
            评分字符串（如 "9.2"），找不到则返回空字符串 ""

        策略：
            1. 先精确匹配 class="rating_nums"
            2. 如果找不到，模糊匹配包含 "rating" 的 class 名
            3. 从匹配到的文本中用正则提取数字
        """
        # ---- 策略1：精确匹配 class="rating_nums" ----
        rating_el = element.select_one(".rating_nums")
        if rating_el:
            # 直接获取文本内容（豆瓣的评分格式就是纯数字如 "9.2"）
            return rating_el.get_text(strip=True)

        # ---- 策略2：模糊匹配包含 "rating" 关键词的元素 ----
        # 某些豆列模板可能使用不同的 class 名，如 "rating-score"
        rating_el = element.find("span", class_=re.compile(r"rating"))
        if rating_el:
            text = rating_el.get_text(strip=True)
            # 用正则提取数字部分（如 "评分9.2" → "9.2"）
            match = re.search(r"[\d.]+", text)
            if match:
                return match.group()

        # 所有策略都失败了
        return ""

    def _extract_rating_count(self, element) -> str:
        """
        提取评价人数

        豆瓣豆列页面中，评价人数通常存储在：
            <span class="rating_people">
                <span>(125000人评价)</span>
            </span>

        参数:
            element : 单个图书条目的 BeautifulSoup 元素

        返回:
            纯数字字符串（如 "125000"），找不到则返回 ""

        策略：
            1. 先精确匹配 class="rating_people"
            2. 如果找不到，搜索包含「人评价」文本的 span
            3. 用正则提取纯数字
        """
        # ---- 策略1：精确匹配 ----
        count_el = element.select_one(".rating_people")
        if count_el:
            text = count_el.get_text(strip=True)
            # 文本可能是 "(125000人评价)"，用正则只取数字
            match = re.search(r"\d+", text)
            if match:
                return match.group()

        # ---- 策略2：搜索「人评价」关键词 ----
        count_el = element.find("span", string=re.compile(r"\d+人评价"))
        if count_el:
            match = re.search(r"\d+", count_el.get_text())
            if match:
                return match.group()

        return ""

    def _extract_abstract(self, element, preserve_newlines: bool = False) -> str:
        """
        提取图书简介/摘要

        豆瓣豆列的简介可能出现在不同位置：
            <div class="abstract">...</div>
            <div class="comment">...</div>
            <div class="intro">...</div>

        参数:
            element           : 单个图书条目的 BeautifulSoup 元素
            preserve_newlines : 是否保留换行符（用于字段拆分场景）

        返回:
            简介文本，找不到则返回 ""

        注意：
            preserve_newlines=True 时，get_text 使用 "\n" 作为子元素分隔符，
            这样可以保留「作者/出版社/出版年」的换行结构，供 _parse_info_line 使用。
            这是解决古籍/校注类书籍字段窜行的关键——如果 strip=True 把所有行合并，
            多作者的「/」会被误当作字段分隔符。
        """
        # ---- 策略1：class="abstract"（最常见） ----
        abstract_el = element.select_one(".abstract")
        if abstract_el:
            if preserve_newlines:
                return abstract_el.get_text("\n", strip=True)
            return abstract_el.get_text(strip=True)

        # ---- 策略2：其他可能的 class 名 ----
        for cls in [".comment", ".intro", ".article-desc-bd"]:
            found = element.select_one(cls)
            if found:
                if preserve_newlines:
                    return found.get_text("\n", strip=True)
                return found.get_text(strip=True)

        return ""

    def _parse_info_line(self, text: str) -> dict:
        """
        解析图书详细信息行（★★★ 核心拆分逻辑 ★★★）

        豆瓣豆列的 abstract 区域内，各信息字段以换行符分隔，每行带明确标签前缀：
            "作者: [英] 吉米·哈利"
            "出版社: 中国城市出版社"
            "出版年: 2012-3"
            "定价: 35.00元"

        某些豆列模板用「 / 」分隔（紧凑格式）：
            "作者: 加西亚·马尔克斯 / 译者: 范晔 / 出版社: 南海出版公司 / 出版年: 2011-6"

        分层解析规则（★★ 核心设计 ★★）：
            【层级1】按换行拆分 → 逐行标签匹配（优先，覆盖 95% 豆列）
            【层级2】按关键词正则分层：
                      第一段（作者块）= 从开头到第一个「出版社/出版年」标签之前
                      第二段（出版块）= 后半段文本，再从中拆分「出版社」+「出版日期」
            【层级3】窜行检测与修复 → 字段交叉污染回退重解析

        设计理念：
            古籍/校注类书籍的作者行内常有「/」连接多位贡献者
            （如 "作者: [汉] 许慎 撰 / [宋] 徐铉杨 校定"），
            这些「/」是作者行内分隔符，不是字段分隔符。
            通过保留换行 + 正则分层，确保作者行始终完整归入作者字段。

        参数:
            text : 原始信息文本（保留换行符的 abstract 文本）

        返回:
            {
                "author":    "作者译者",
                "publisher": "出版社",
                "pub_date":  "出版日期",
                "price":     "定价"
            }
        """
        # ---- 初始化结果字典 ----
        result = {
            "author":    "",
            "publisher": "",
            "pub_date":  "",
            "price":     "",
        }

        # ---- 空文本直接返回 ----
        if not text:
            return result

        text = text.strip()

        # ---- 层级1：按换行拆分 → 逐行标签匹配 ----.
        # 由于 _parse_single_book 中 abstract 已保留换行，
        # 这是最优先、最准确的解析路径
        lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
        if len(lines) > 1:
            # 多行文本：逐行标签匹配（作者行内 / 不会被当作分隔符）
            result = self._parse_labeled_lines(lines, result)
        else:
            # 单行文本：进入层级2
            result = self._parse_single_line_hierarchical(text)

        # ---- 后处理 ----
        # 清理作者字段中可能的重复前缀残留
        if result["author"]:
            result["author"] = re.sub(
                r"^(作者|译者)[:：]\s*", "", result["author"]
            )

        # 窜行检测与修复
        result = self._fix_field_crossover(result, text)

        # 出版社剥离年份信息
        if result["publisher"]:
            result["publisher"] = self._strip_year_from_publisher(
                result["publisher"]
            )

        # 出版日期只保留年月
        if result["pub_date"]:
            result["pub_date"] = self._normalize_pub_date(
                result["pub_date"]
            )

        # 最终兜底：空值填充
        for key in ["author", "publisher", "pub_date", "price"]:
            if not result[key]:
                result[key] = ""

        return result

    def _parse_single_line_hierarchical(self, text: str) -> dict:
        """
        【层级2】单行文本的正则分层解析

        适用于换行拆分失败的情况（紧凑格式豆列模板）：
            "作者: xxx / 译者: yyy / 出版社: zzz / 出版年: 2020-1 / 定价: 39.00"

        分层规则：
            ① 第一段（作者块）= 从文本开头到第一个「出版信息标签」之前的所有内容
            ② 第二段（出版块）= 剩余文本，再从中拆分「出版社」+「出版日期」

        关键正则：
            r"(出版社|出版年|出版日期|出版时间|定价|价格)"
            → 找到第一个出版信息标签的位置，之前全部归作者，之后拆分出版信息
        """
        result = {"author": "", "publisher": "", "pub_date": "", "price": ""}

        # ---- 步骤1：定位「作者块」和「出版块」的分界点 ----
        # 搜索第一个出版相关标签关键词
        pub_label_pattern = r"(出版社|出版年|出版日期|出版时间|定价|价格)"
        boundary_match = re.search(pub_label_pattern, text)

        if not boundary_match:
            # 整个文本都不含出版标签 → 全部归为作者
            result["author"] = text
            return result

        # ---- 步骤2：切分作者块和出版块 ----
        split_pos = boundary_match.start()
        author_block = text[:split_pos].strip()      # 作者块（标签之前）
        pub_block = text[split_pos:].strip()          # 出版块（标签及之后）

        # ---- 步骤3：处理作者块 ----
        # 作者块可能含「 / 」连接多位作者/译者
        # 清洗步骤：
        #   a) 去掉「作者:」「译者:」标签前缀
        #   b) 去掉尾部残留的「 / 」「/ 」等分隔符
        #   c) 多位作者/译者之间用「 / 」连接
        author_clean = re.sub(r"^(作者|译者)[:：]?\s*", "", author_block)
        # 移除作者块内所有「译者:」标签（紧凑格式下可能残留）
        author_clean = re.sub(r"译者[:：]?\s*", "", author_clean)
        # 清理首尾的 / 和空白
        author_clean = re.sub(r"^[/\s]+|[/\s]+$", "", author_clean)
        # 规范内部 / 分隔符（多个 / 合并为单个，两侧加空格）
        author_clean = re.sub(r"\s*/\s*", " / ", author_clean)
        result["author"] = author_clean.strip()

        # ---- 步骤4：处理出版块 → 拆分为出版社 + 出版日期 ----
        # 出版块格式如："出版社: 中华书局 / 出版年: 1963-12 / 定价: 39.00"
        # 也可能不含 /： "出版社: 中华书局出版年: 1963-12定价: 39.00"
        self._parse_pub_block(pub_block, result)

        return result

    @staticmethod
    def _parse_pub_block(pub_text: str, result: dict) -> None:
        """
        从出版块文本中提取「出版社」「出版日期」「定价」

        输入示例：
            "出版社: 中华书局 / 出版年: 1963-12 / 定价: 39.00"
            "出版社: 中华书局出版年: 1963-12定价: 39.00元"

        策略：
            按关键标签用正则切分，逐个匹配到对应字段。
            标签顺序有讲究：「出版年」必须在「出版社」前面，
            否则「出版社」会先匹配到「出版年」中的「出版」二字。
        """
        # 按标签切分出版块
        pattern = r"(?=出版社|出版年|出版日期|出版时间|定价|价格)"
        parts = re.split(pattern, pub_text)
        parts = [p.strip() for p in parts if p.strip()]

        LABEL_MAP = [
            ("出版年",    "pub_date"),
            ("出版日期",  "pub_date"),
            ("出版时间",  "pub_date"),
            ("出版社",    "publisher"),
            ("定价",      "price"),
            ("价格",      "price"),
        ]

        for part in parts:
            for keyword, field_key in LABEL_MAP:
                if keyword in part:
                    content = re.sub(
                        rf"^{keyword}[:：]?\s*", "", part
                    ).strip()
                    # 清理尾随的 / 分隔符和空白
                    content = re.sub(r"\s*/\s*$", "", content).strip()
                    if not content:
                        break
                    if field_key in ("publisher", "pub_date", "price"):
                        if not result[field_key]:
                            result[field_key] = content
                    break

    # ================================================================
    # 解析策略子方法
    # ================================================================

    @staticmethod
    def _parse_labeled_lines(lines: list, result: dict) -> dict:
        """
        对已拆分的行列表，逐行按标签关键词归类到对应字段

        标签映射表顺序有讲究：
            "出版年" 必须排在 "出版社" 前面，
            否则 "出版社" 会先匹配 "出版年" 中的 "出版"
        """
        LABEL_MAP = [
            ("出版年",    "pub_date"),
            ("出版日期",  "pub_date"),
            ("出版时间",  "pub_date"),
            ("出版社",    "publisher"),
            ("作者",      "author"),
            ("译者",      "author"),
            ("定价",      "price"),
            ("价格",      "price"),
            ("装帧",      "binding"),
            ("页数",      "pages"),
            ("ISBN",      "isbn"),
            ("丛书",      "series"),
            ("原作名",    "orig_title"),
        ]

        for line in lines:
            matched = False
            for keyword, field_key, *_ in LABEL_MAP:
                if keyword in line:
                    content = re.sub(
                        rf"^{keyword}[:：]?\s*", "", line
                    ).strip()

                    if not content:
                        matched = True
                        break

                    if field_key == "author":
                        if not result["author"]:
                            result["author"] = content
                        else:
                            result["author"] += " / " + content
                    elif field_key in ("publisher", "pub_date", "price"):
                        result[field_key] = content

                    matched = True
                    break

            # 无标签行：智能推断
            if not matched and line.strip():
                DoubanBookSpider._parse_unlabeled_line(line, result)

        return result

    @staticmethod
    def _fix_field_crossover(result: dict, original_text: str) -> dict:
        """
        ★ 窜行检测与修复 ★

        问题场景：当原始文本被错误解析后，出版日期字段可能混入
        出版社信息（如 "出版社: 人民邮电出版社出版年: 2008-1-1"）。

        检测规则：
            - pub_date 含 "出版社" 关键词 → 窜行
            - publisher 含 "出版年" / "出版日期" → 窜行

        修复策略：对窜行字段重新用正则提取纯净内容
        """
        # ---- 检测1：出版日期字段含出版社信息 ----
        if result["pub_date"] and ("出版社" in result["pub_date"] or
                                     "出版年" in result["pub_date"]):
            # 尝试从窜行文本中提取各字段
            fixed = DoubanBookSpider._force_extract_from_mixed(
                result["pub_date"]
            )
            if fixed["pub_date"]:
                result["pub_date"] = fixed["pub_date"]
            if fixed["publisher"] and not result["publisher"]:
                result["publisher"] = fixed["publisher"]
            if fixed["author"] and not result["author"]:
                result["author"] = fixed["author"]

        # ---- 检测2：出版社字段含出版年信息 ----
        if result["publisher"] and "出版年" in result["publisher"]:
            fixed = DoubanBookSpider._force_extract_from_mixed(
                result["publisher"]
            )
            if fixed["publisher"]:
                result["publisher"] = fixed["publisher"]
            if fixed["pub_date"] and not result["pub_date"]:
                result["pub_date"] = fixed["pub_date"]

        # ---- 检测3：作者字段含出版社/出版年 ----
        if result["author"] and ("出版社" in result["author"] or
                                   "出版年" in result["author"]):
            fixed = DoubanBookSpider._force_extract_from_mixed(
                result["author"]
            )
            if fixed["author"]:
                result["author"] = fixed["author"]
            if fixed["publisher"] and not result["publisher"]:
                result["publisher"] = fixed["publisher"]
            if fixed["pub_date"] and not result["pub_date"]:
                result["pub_date"] = fixed["pub_date"]

        return result

    @staticmethod
    def _force_extract_from_mixed(text: str) -> dict:
        """
        从窜行的混合文本中强制提取各字段

        用正则按关键词切分，然后逐个字段提取。
        例如："[美] 威廉·诺德豪斯出版社: 人民邮电出版社出版年: 2008-1-1"
        → author="[美] 威廉·诺德豪斯", publisher="人民邮电出版社", pub_date="2008-1-1"
        """
        result = {"author": "", "publisher": "", "pub_date": "", "price": ""}

        # 按关键标签切分
        pattern = r"(?=作者|译者|出版年|出版日期|出版时间|出版社|定价|价格)"
        parts = re.split(pattern, text)
        parts = [p.strip() for p in parts if p.strip()]

        LABEL_MAP = [
            ("出版年",    "pub_date"),
            ("出版日期",  "pub_date"),
            ("出版时间",  "pub_date"),
            ("出版社",    "publisher"),
            ("作者",      "author"),
            ("译者",      "author"),
            ("定价",      "price"),
            ("价格",      "price"),
        ]

        for part in parts:
            for keyword, field_key in LABEL_MAP:
                if keyword in part:
                    content = re.sub(
                        rf"^{keyword}[:：]?\s*", "", part
                    ).strip()
                    if not content:
                        break
                    if field_key == "author":
                        if not result["author"]:
                            result["author"] = content
                        else:
                            result["author"] += " / " + content
                    elif field_key in ("publisher", "pub_date", "price"):
                        if not result[field_key]:
                            result[field_key] = content
                    break

        # 兜底：如果切分后没有匹配到标签，尝试按位置推断
        if not result["author"] and not result["publisher"] and not result["pub_date"]:
            # 可能是不含标签的纯文本，全部归为作者
            if text.strip():
                result["author"] = text.strip()

        return result

    @staticmethod
    def _strip_year_from_publisher(text: str) -> str:
        """
        从出版社字段中剥离附带年份/朝代/编纂信息

        多阶段净化：
            【阶段1】移除「出版年/出版日期: ...」标签及内容
            【阶段2】剔除朝代/国家标识（[宋] [汉] [美] [英] 等）
            【阶段3】剔除校/注/编/译/著/撰等编纂角色关键词
            【阶段4】兜底检测：清洗后不像出版社名则置空

        返回：
            纯净的出版社名称
        """
        if not text:
            return text

        # ---- 阶段1：移除「出版年/出版日期: ...」标签及内容 ----
        text = re.sub(
            r"[,，\s]*出版(年|日期|时间)[:：]\s*[\d\-/年月]+[^a-zA-Z\u4e00-\u9fff]*",
            "", text
        )

        # 移除尾部纯日期/年份
        text = re.sub(
            r"\s+\d{4}[-/年]\d{1,2}([-/月]\d{1,2}[日号]?)?$",
            "", text
        )
        text = re.sub(
            r"[,，\s]+\d{4}\s*$",
            "", text
        )

        # ---- 阶段2：剔除朝代/国家标识 ----
        # 如 "[宋]" "[汉]" "[美]" "[英]" 等
        text = re.sub(
            r"[\[【][\u4e00-\u9fffA-Za-z]+[\]】]",
            "", text
        )

        # ---- 阶段3：剔除编纂角色关键词 ----
        editing_keywords = r"(校定|校注|校勘|校对|校点|校译|编注|编著|编译|注译|注疏|注釋|注释|译注|撰|著)"
        if re.search(editing_keywords, text):
            text_cleaned = re.sub(
                r"[,，/\s]*" + editing_keywords + r"[,，/\s]*",
                " ", text
            ).strip()
            if len(re.sub(r"[^\u4e00-\u9fff]", "", text_cleaned)) < 2:
                return ""

        # ---- 阶段4：兜底检测 ----
        text = re.sub(r"[,，\s]+$", "", text).strip()
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        if len(chinese_chars) < 2 and len(text) > 0:
            return ""

        return text.strip()

    @staticmethod
    def _normalize_pub_date(text: str) -> str:
        """
        标准化出版日期：只保留年月信息

        输入示例：
            "2012-3"        → "2012-03"
            "2012-3-1"      → "2012-03"
            "2012年3月"     → "2012-03"
            "1998-10-1"     → "1998-10"
            "2003-01-01"    → "2003-01"
            "2003年"        → "2003"
            "2012"          → "2012"

        处理规则：
            1. 提取年份（四位数字）
            2. 提取月份（1-2位数字）
            3. 格式化为 YYYY-MM 或 YYYY
            4. 丢弃日信息
        """
        if not text:
            return text

        # 提取年份和月份
        # 匹配模式：2012-3, 2012-3-1, 2012年3月, 2012年3月1日
        m = re.search(r"(\d{4})\s*[-/年.]\s*(\d{1,2})", text)
        if m:
            year = m.group(1)
            month = m.group(2).zfill(2)  # 补齐两位（如 "3" → "03"）
            return f"{year}-{month}"

        # 只有年份
        m = re.search(r"(\d{4})", text)
        if m:
            return m.group(1)

        # 无法提取日期，返回原文
        return text.strip()

    @staticmethod
    def _split_info_by_keywords(text: str) -> list:
        """
        兜底策略：当文本既没有换行也没有「/」分隔时，
        用正则按关键词标签切分。

        例如："作者: xxx 出版社: yyy 出版年: 2020-1 定价: 39.00"
        → ["作者: xxx", "出版社: yyy", "出版年: 2020-1", "定价: 39.00"]
        """
        # 按关键标签切分（出版年必须在出版社前面匹配）
        pattern = r"(?=作者|译者|出版年|出版日期|出版时间|出版社|定价|价格|装帧|页数|ISBN|丛书|原作名)"
        parts = re.split(pattern, text)
        return [p.strip() for p in parts if p.strip()]

    @staticmethod
    def _parse_unlabeled_line(line: str, result: dict) -> None:
        """
        处理无标签行：尝试推断其属于哪个字段

        推断规则（按优先级）：
            1. 包含 "元" / "￥" / "$" / "CNY" → 定价
            2. 包含 "出版" / 匹配日期格式 → 出版日期
            3. 其余 → 作者（兜底）
        """
        line = line.strip()
        if not line:
            return

        # 规则1：价格特征
        if re.search(r"[￥¥$€£]|元|CNY", line, re.IGNORECASE):
            cleaned = re.sub(r"[￥¥$€£CNY元]", "", line, flags=re.IGNORECASE).strip()
            if cleaned:
                result["price"] = cleaned
            return

        # 规则2：日期特征（如 "2012-3"、"2012年"）
        if re.search(r"\d{4}[-/年.]\d{1,2}", line):
            result["pub_date"] = line
            return

        # 规则3：纯数字可能是出版年份
        if re.match(r"^\d{4}$", line.strip()):
            result["pub_date"] = line
            return

        # 规则4：兜底 → 追加到作者
        if result["author"]:
            result["author"] += " / " + line
        else:
            result["author"] = line

    def _parse_single_book(self, item) -> Optional[dict]:
        """
        解析单个图书条目，提取全部 8 个目标字段

        这是爬虫最核心的方法，它调用上面所有辅助提取方法，
        把一个 HTML 条目转换为一个完整的字典。

        参数:
            item : BeautifulSoup 解析后的单个图书条目 Tag 对象

        返回:
            成功 → {"书名":..., "作者译者":..., ..., "简介":...}
            失败 → None（书名解析不到或发生异常）

        提取的 8 个字段：
            1. 书名      - 从 .title a 中提取
            2. 作者译者  - 从信息行中拆分
            3. 出版社    - 从信息行中拆分
            4. 出版日期  - 从信息行中拆分
            5. 定价      - 从信息行中拆分
            6. 豆瓣评分  - 从 .rating_nums 中提取
            7. 评价人数  - 从 .rating_people 中提取
            8. 简介      - 从 .abstract 或 .comment 中提取
        """
        try:
            # ========================================================
            # 字段1：书名
            # ========================================================
            # 书名在 <div class="title"><a href="...">书名</a></div> 中
            title_el = (
                item.select_one(".title a")       # 优先：class="title" 下的 <a>
                or item.select_one("div.title a")  # 备选：<div class="title"> 下的 <a>
            )
            title = title_el.get_text(strip=True) if title_el else ""

            # 书名是必填字段，如果连书名都提取不到，整条数据就没有意义
            if not title:
                return None

            # ========================================================
            # 字段2-5：作者译者、出版社、出版日期、定价
            # ========================================================
            # 这四个字段从 abstract / pub / info 区域中拆分

            # ★ 关键修改：abstract 获取时保留换行（preserve_newlines=True）
            #   这是解决古籍/校注类书籍字段窜行的根本修复——
            #   豆瓣 abstract 区域内部按换行分行，每行一个字段标签。
            #   如果 strip=True 合并所有行，多作者中间的「/」会被
            #   误当作字段分隔符，导致校注人窜入出版社。
            abstract_text = self._extract_abstract(item, preserve_newlines=True)

            # 备选：从 .pub 或 .info 区域提取（保留换行）
            info_text = ""
            info_el = item.select_one(".pub") or item.select_one(".info")
            if info_el:
                info_text = info_el.get_text("\n", strip=True)

            # 合并策略：
            #   - 如果 .pub/.info 有内容，优先使用（更结构化）
            #   - 否则使用 .abstract（主要数据来源）
            if info_text:
                full_info = info_text
            elif abstract_text:
                full_info = abstract_text
            else:
                full_info = ""

            # 调用 _parse_info_line 拆分为四个独立字段
            info_dict = self._parse_info_line(full_info)

            # ========================================================
            # 字段6：豆瓣评分
            # ========================================================
            score = self._extract_rating(item)

            # ========================================================
            # 字段7：评价人数
            # ========================================================
            rating_count = self._extract_rating_count(item)

            # ========================================================
            # 字段8：简介
            # ========================================================
            # 简介用 strip=True 获取（干净的单行文本）
            intro = self._extract_abstract(item, preserve_newlines=False)

            # 如果 .abstract 的内容已经被用作信息行解析了
            # 再尝试从 .comment 中获取（有些豆列把简介放在这里）
            comment_el = item.select_one(".comment")
            if comment_el:
                intro = comment_el.get_text(strip=True)

            # ========================================================
            # 组装返回
            # ========================================================
            return {
                "书名":     title,                   # 字段1
                "作者译者": info_dict["author"],     # 字段2
                "出版社":   info_dict["publisher"],  # 字段3
                "出版日期": info_dict["pub_date"],   # 字段4
                "定价":     info_dict["price"],      # 字段5
                "豆瓣评分": score,                   # 字段6
                "评价人数": rating_count,            # 字段7
                "简介":     intro,                   # 字段8
            }

        except Exception as e:
            # 解析过程中出现任何意外错误
            # 打印错误信息（便于调试），跳过这条数据
            print(f"[解析错误] 解析单条图书数据时出错: {e}")
            return None

    # ================================================================
    # 第三部分：业务流程层
    # 负责组织爬取流程：翻页、延时、汇总
    # ================================================================

    def crawl_page(self, page_num: int) -> list[dict]:
        """
        爬取指定页码的数据

        参数:
            page_num : 页码（从 1 开始计数）

        返回:
            该页所有图书数据的列表，每本书是一个 dict

        处理流程：
            1. 计算分页偏移量（第1页=0，第2页=25，第3页=50...）
            2. 请求页面 HTML
            3. 解析所有图书条目
            4. 逐个提取结构化数据
            5. 打印进度日志
        """
        # ---- 打印分页分隔线 ----
        print(f"\n{'='*50}")
        print(f"正在爬取第 {page_num} 页...")

        # ---- 计算分页偏移量 ----
        # 豆瓣豆列每页 25 条，用 start 参数控制
        # 第1页: start=0, 第2页: start=25, 第3页: start=50
        start = (page_num - 1) * 25

        # ---- 获取页面 HTML ----
        html = self._fetch_page(self.base_url, start=start)
        if not html:
            # 请求失败，跳过本页（不中断整个流程）
            print(f"[跳过] 第 {page_num} 页获取失败，跳过该页")
            return []

        # ---- 解析所有图书条目 ----
        try:
            items = self._parse_book_items(html)
        except Exception as e:
            print(f"[错误] 解析第 {page_num} 页HTML失败: {e}")
            return []

        print(f"  发现 {len(items)} 个条目，开始提取数据...")

        # ---- 逐条提取数据 ----
        page_data = []
        for i, item in enumerate(items, 1):   # enumerate 从 1 开始编号
            book = self._parse_single_book(item)
            if book:
                page_data.append(book)
                # 打印每条数据的摘要信息（书名截断到30字符，右对齐）
                print(
                    f"  [{i:2d}] "                          # 序号（2位右对齐）
                    f"{book['书名'][:30]:30s} | "           # 书名（30字符宽）
                    f"评分: {book['豆瓣评分']}"             # 评分
                )

        print(f"  第 {page_num} 页成功提取 {len(page_data)} 条数据")
        return page_data

    def crawl_all_pages(self, pages: int = None) -> list[dict]:
        """
        爬取所有目标页面的数据 ★ 主入口方法 ★

        这是外部调用的唯一入口，main.py 中就是调用这个方法。
        它会自动完成所有翻页、延时、汇总工作。

        参数:
            pages : 要爬取的总页数（不传则使用 config.CRAWL_PAGES）

        返回:
            所有图书数据的列表，每个元素是一个包含 8 个字段的 dict

        使用示例：
            spider = DoubanBookSpider()
            data = spider.crawl_all_pages()          # 使用默认页数
            data = spider.crawl_all_pages(pages=5)   # 指定爬5页
        """
        # ---- 确定爬取页数 ----
        if pages is None:
            pages = config.CRAWL_PAGES     # 使用配置文件中的默认值

        # ---- 打印启动信息 ----
        print(f"\n{'#'*50}")
        print(f"# 豆瓣高分图书爬虫启动")
        print(f"# 目标页数: {pages} 页（约 {pages * 25} 本书）")
        print(f"# 请求间隔: {self.delay} 秒/次")
        print(f"{'#'*50}")

        # ---- 逐页爬取 ----
        all_data = []

        for page in range(1, pages + 1):
            # ① 爬取当前页
            page_data = self.crawl_page(page)

            # ② 合并到总数据中
            all_data.extend(page_data)

            # ③ 页面间延时（爬虫礼仪核心）
            #    最后一页不需要等待（后面没有请求了）
            if page < pages:
                print(f"\n  [等待] {self.delay} 秒后继续...（遵守爬虫礼仪）")
                time.sleep(self.delay)

        # ---- 打印完成信息 ----
        print(f"\n{'='*50}")
        print(f"爬取完成！共获取 {len(all_data)} 条图书数据")
        print(f"{'='*50}")

        return all_data


# ================================================================
# 模块自测代码
# 当直接运行 python spider.py 时执行，用于独立测试爬虫模块
# ================================================================
if __name__ == "__main__":
    # 创建爬虫实例
    spider = DoubanBookSpider()

    # 执行完整爬取流程
    data = spider.crawl_all_pages()

    # 打印前5条数据用于验证
    for i, book in enumerate(data[:5], 1):
        print(f"\n--- 第{i}本书 ---")
        for key, value in book.items():
            print(f"  {key}: {value}")
