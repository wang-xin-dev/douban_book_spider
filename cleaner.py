"""
数据清洗模块 —— 豆瓣高分图书数据处理
=========================================
负责将爬虫吐出的「原始脏数据」清洗为「干净的结构化数据」。

为什么需要数据清洗？
    爬虫直接从 HTML 中提取的数据存在以下问题：
    1. 文本含有换行符、制表符、多余空格
    2. 评分和评价人数还是字符串，不是数值类型
    3. 某些字段可能为空（如某本书没有简介）
    4. 可能存在无效数据（如评分超出10分）

清洗流程（按顺序执行）：
    步骤1: 转为 pandas DataFrame
    步骤2: 文本字段去噪（清除换行/空格/制表符）
    步骤3: 定价字段清洗（去除货币符号）
    步骤4: 数值字段类型转换（评分→float，评价人数→int）
    步骤5: 空值统一填充（空文本→"无"，空数值→NaN）
    步骤6: 过滤脏数据（无效书名、无评分数据）
    步骤7: 按书名去重
    步骤8: 重置索引

使用示例：
    >>> from cleaner import DataCleaner
    >>> cleaner = DataCleaner()
    >>> df = cleaner.clean(raw_list)   # raw_list 是爬虫返回的 dict 列表
    >>> print(f"清洗后剩余 {len(df)} 条数据")
"""

# ---------- 标准库 ----------
import re                          # 正则表达式：从文本中提取/替换字符
from typing import Optional        # 类型注解：兼容 Python 3.9-

# ---------- 第三方库 ----------
import pandas as pd                # 数据处理王者库：DataFrame 是核心数据结构

# ---------- 项目内部模块 ----------
import config                      # 统一配置文件：读取清洗参数


class DataCleaner:
    """
    数据清洗器

    设计思路：
        每个字段类型有独立的清洗方法（_clean_text / _clean_price / _clean_score 等），
        主方法 clean() 按固定顺序调用它们，形成清洗流水线。

    核心方法一览：
        _clean_text()        - 清洗文本字段（去换行、空格、制表符）
        _clean_price()       - 清洗定价字段（去货币符号）
        _clean_score()       - 清洗评分字段（字符串→float）
        _clean_rating_count()- 清洗评价人数字段（字符串→int）
        clean()              - 主清洗流水线（对外唯一入口）
    """

    def __init__(self):
        """
        初始化清洗器

        从 config.py 中读取所有清洗相关配置：
            - null_fill : 空值填充用的字符串（默认"无"）
            - score_min/max : 有效评分范围（过滤异常数据）
            - count_min/max : 有效评价人数范围（过滤异常数据）
        """
        self.null_fill   = config.NULL_FILL_VALUE     # 空值填充文本
        self.score_min   = config.SCORE_MIN           # 评分下限（0.0）
        self.score_max   = config.SCORE_MAX           # 评分上限（10.0）
        self.count_min   = config.RATING_COUNT_MIN    # 评价人数下限（0）
        self.count_max   = config.RATING_COUNT_MAX    # 评价人数上限（1000万）

    # ================================================================
    # 第一部分：单字段清洗方法
    # 每个方法负责一种数据类型的清洗转换
    # ================================================================

    def _clean_text(self, text: str) -> str:
        """
        清洗单个文本字段

        处理内容：
            1. 换行符 \n → 空格
            2. 回车符 \r → 空格
            3. 制表符 \t → 空格
            4. 多个连续空格 → 单个空格
            5. 去除首尾空白

        参数:
            text : 原始文本（可能含有各种格式字符）

        返回:
            清洗后的干净文本

        示例：
            "  百年孤独  \n  "  →  "百年孤独"
            "简介内容\r\n第二行"  →  "简介内容 第二行"
        """
        # ---- 防御性检查 ----
        # 如果不是字符串或为空，直接返回空字符串
        if not text or not isinstance(text, str):
            return ""

        # ---- 步骤1：替换特殊空白字符为普通空格 ----
        text = text.replace("\n", " ")   # 换行 → 空格
        text = text.replace("\r", " ")   # 回车 → 空格
        text = text.replace("\t", " ")   # 制表 → 空格

        # ---- 步骤2：合并连续空格 ----
        # r" {2,}" 匹配两个及以上的空格，替换为一个空格
        text = re.sub(r" {2,}", " ", text)

        # ---- 步骤3：去除首尾空白 ----
        text = text.strip()

        return text

    def _clean_publisher(self, text: str) -> str:
        """
        清洗出版社字段：多阶段净化处理

        【阶段1】剥离附带年份/日期信息
            "人民邮电出版社 2008-1-1"  → "人民邮电出版社"
            "中华书局出版年: 1959-9"   → "中华书局"

        【阶段2】剔除朝代标识 [宋] [汉] [明] [美] [英] 等
            问题场景：古籍/校注类书籍的校注人信息窜入出版社
            "[宋] 徐铉杨 校定"  → ""

        【阶段3】剔除校/注/编/译/著/撰等编纂角色关键词
            问题场景：作者行内片段被误归入出版社
            "徐铉杨 校定"  → ""

        【阶段4】非出版社内容兜底检测
            如果清洗后剩余文本不像出版社名（过短、纯标点等），置空
        """
        if not text or not isinstance(text, str):
            return ""

        # ---- 阶段1：移除「出版年/出版日期: ...」标签及内容 ----
        text = re.sub(
            r"[,，\s]*出版(年|日期|时间)[:：]\s*[\d\-/年月]+[^a-zA-Z\u4e00-\u9fff]*",
            "", text
        )

        # 阶段1b：移除尾部纯日期（如 " 2012-3"、" 2008-1-1"）
        text = re.sub(
            r"\s+\d{4}[-/年]\d{1,2}([-/月]\d{1,2}[日号]?)?$",
            "", text
        )

        # 阶段1c：移除尾部纯四位年份
        text = re.sub(
            r"[,，\s]+\d{4}\s*$",
            "", text
        )

        # ---- 阶段2：剔除朝代/国家标识 ----
        # 匹配模式：[汉] [宋] [明] [清] [美] [英] [法] [德] [日] 等
        # 这些标识是作者/校注人的前缀，不应出现在出版社中
        text = re.sub(
            r"[\[【][\u4e00-\u9fffA-Za-z]+[\]】]",
            "", text
        )

        # ---- 阶段3：剔除编纂角色关键词 ----
        # 如果文本中出现了校/注/编/译/著/撰等关键词，
        # 说明这是校注人信息窜入，不是出版社名
        # 匹配模式：关键词 + 可选内容
        editing_keywords = r"(校定|校注|校勘|校对|校点|校译|编注|编著|编译|注译|注疏|注釋|注释|译注|撰|著)"
        if re.search(editing_keywords, text):
            # 检测：如果整段文本主要是编纂角色信息，置空
            # 先尝试只删除编纂角色部分，保留可能夹杂的出版社名
            text_cleaned = re.sub(
                r"[,，/\s]*" + editing_keywords + r"[,，/\s]*",
                " ", text
            ).strip()
            # 如果清除后只剩空格或很短（<2个中文字符），说明整段都是编纂信息
            if len(re.sub(r"[^\u4e00-\u9fff]", "", text_cleaned)) < 2:
                return ""

        # ---- 阶段4：兜底检测 ----
        # 出版社名至少应包含中文且长度合理
        text = re.sub(r"[,，\s]+$", "", text).strip()
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        if len(chinese_chars) < 2 and len(text) > 0:
            # 中文太少，不像出版社名
            return ""

        return text

    def _clean_pub_date(self, text: str) -> str:
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

        规则：
            1. 提取年份（四位数字）
            2. 提取月份（1-2位数字）
            3. 格式化为 YYYY-MM 或 YYYY
            4. 丢弃日信息
        """
        if not text or not isinstance(text, str):
            return ""

        # 匹配 年-月 或 年-月-日 格式
        m = re.search(r"(\d{4})\s*[-/年.]\s*(\d{1,2})", text)
        if m:
            year = m.group(1)
            month = m.group(2).zfill(2)
            return f"{year}-{month}"

        # 只有四位年份
        m = re.search(r"(\d{4})", text)
        if m:
            return m.group(1)

        return text.strip()

    def _clean_price(self, price_str: str) -> str:
        """
        清洗定价字段

        豆瓣的价格格式五花八门，需要统一处理：
            "39.50元"   →  "39.50"
            "CNY 35.00" →  "35.00"
            "¥28.00"    →  "28.00"
            "$12.99"    →  "12.99"

        参数:
            price_str : 原始价格字符串

        返回:
            纯数字价格字符串（如 "39.50"）
        """
        # ---- 防御性检查 ----
        if not price_str or not isinstance(price_str, str):
            return ""

        # ---- 去除货币符号和单位 ----
        # 正则说明：
        #   [￥¥$€£CNY元]  匹配任意一个货币符号或"元"字
        #   flags=re.IGNORECASE 使匹配不区分大小写（如 CNY / cny 都能匹配）
        cleaned = re.sub(r"[￥¥$€£CNY元]", "", price_str, flags=re.IGNORECASE)
        cleaned = cleaned.strip()

        # ---- 提取数字部分 ----
        match = re.search(r"[\d.]+", cleaned)
        if match:
            return match.group()    # 返回纯数字（含小数点）

        return cleaned              # 兜底返回

    def _clean_score(self, score_str) -> Optional[float]:
        """
        清洗评分字段 → 转为浮点数

        豆瓣评分原始数据可能是：
            "9.2"   → 9.2   ✓ 正常
            "9.2分" → 9.2   ✓ 含文字，提取数字
            "abc"   → None  ✗ 无效，返回None
            11.0    → None  ✗ 超出范围，过滤

        参数:
            score_str : 原始评分（字符串或数字）

        返回:
            有效的浮点数评分，无效则返回 None
        """
        # ---- 空值检查 ----
        if score_str is None:
            return None

        # ---- 策略1：直接转换 ----
        try:
            score = float(score_str)
            # 验证是否在有效范围内（豆瓣评分0-10）
            if self.score_min <= score <= self.score_max:
                return round(score, 1)   # 保留1位小数
            else:
                return None              # 超出范围，标记为无效
        except (ValueError, TypeError):
            # 不是纯数字，进入策略2
            pass

        # ---- 策略2：从字符串中提取数字 ----
        if isinstance(score_str, str):
            # 用正则提取第一个数字（如 "评分9.2分" → "9.2"）
            match = re.search(r"[\d.]+", score_str)
            if match:
                try:
                    score = float(match.group())
                    if self.score_min <= score <= self.score_max:
                        return round(score, 1)
                except ValueError:
                    pass

        return None    # 所有策略都失败了

    def _clean_rating_count(self, count_str) -> Optional[int]:
        """
        清洗评价人数字段 → 转为整数

        豆瓣评价人数原始数据可能是：
            "125000"       → 125000  ✓ 正常
            "125,000"      → 125000  ✓ 含逗号分隔
            "(125000人评价)" → 125000 ✓ 含括号和文字
            ""             → None    ✗ 空值

        参数:
            count_str : 原始评价人数（字符串或数字）

        返回:
            有效的整数评价人数，无效则返回 None
        """
        # ---- 空值检查 ----
        if count_str is None:
            return None

        # ---- 策略1：直接转换 ----
        try:
            # int(float()) 可以处理 "125000" 和 125000.0
            count = int(float(count_str))
            if self.count_min <= count <= self.count_max:
                return count
        except (ValueError, TypeError):
            pass

        # ---- 策略2：从字符串中提取数字 ----
        if isinstance(count_str, str):
            # 先去除千分位逗号（如 "125,000" → "125000"）
            # 再用正则提取连续数字
            match = re.search(r"\d+", count_str.replace(",", ""))
            if match:
                try:
                    count = int(match.group())
                    if self.count_min <= count <= self.count_max:
                        return count
                except ValueError:
                    pass

        return None

    # ================================================================
    # 第二部分：主清洗流水线
    # 对外唯一入口，按固定顺序执行所有清洗步骤
    # ================================================================

    def clean(self, raw_data: list[dict]) -> pd.DataFrame:
        """
        对原始爬虫数据执行完整的清洗流水线 ★ 主入口方法 ★

        清洗步骤（按顺序）：
            ┌──────────────────────────────────────────┐
            │ 步骤1: dict列表 → pandas DataFrame      │
            │ 步骤2: 文本字段去噪（书名/作者/简介等）   │
            │ 步骤3: 定价字段清洗（去货币符号）         │
            │ 步骤4: 数值字段类型转换（评分→float等）   │
            │ 步骤5: 空值统一填充（空→"无"）           │
            │ 步骤6: 过滤脏数据（无效书名/无评分数据）  │
            │ 步骤7: 按书名去重                         │
            │ 步骤8: 重置索引                           │
            └──────────────────────────────────────────┘

        参数:
            raw_data : 爬虫返回的原始字典列表

        返回:
            清洗完成、可直接使用的 pandas DataFrame

        使用示例：
            cleaner = DataCleaner()
            df = cleaner.clean(raw_data_from_spider)
            df.to_excel("book_data.xlsx", index=False)  # 直接导出
        """
        # ---- 防御：空数据 ----
        if not raw_data:
            print("[警告] 输入数据为空，返回空DataFrame")
            return pd.DataFrame()

        # ---- 外层异常保护：防止整个清洗流程崩溃 ----
        try:
            return self._do_clean(raw_data)
        except Exception as e:
            print(f"[错误] 数据清洗过程中发生异常: {e}")
            import traceback
            traceback.print_exc()
            # 返回原始数据的 DataFrame 作为降级方案
            # 至少用户还能看到原始数据，不会完全丢失
            try:
                return pd.DataFrame(raw_data)
            except Exception:
                return pd.DataFrame()

    def _do_clean(self, raw_data: list) -> pd.DataFrame:
        """清洗流水线核心实现（内部方法）"""

        # ---- 打印清洗开始信息 ----
        print(f"\n{'='*50}")
        print(f"开始数据清洗...")
        print(f"原始数据量: {len(raw_data)} 条")

        # ============================================================
        # 步骤1：转为 DataFrame
        # ============================================================
        # pd.DataFrame() 将字典列表转为表格
        # 字典的 key 自动成为列名，value 成为单元格值
        df = pd.DataFrame(raw_data)
        print(f"DataFrame 创建完成，共 {len(df.columns)} 个字段")

        # ============================================================
        # 步骤2：文本字段去噪
        # ============================================================
        # apply() 方法会对整列每个元素依次调用 _clean_text 函数
        # 这是 pandas 的向量化操作，比 for 循环高效得多
        text_columns = ["书名", "作者译者", "出版社", "出版日期", "简介"]
        for col in text_columns:
            if col in df.columns:
                df[col] = df[col].apply(self._clean_text)

        # ============================================================
        # 步骤2.5：出版社 & 出版日期额外清洗（窜行修复的兜底）
        # ============================================================
        # 即使爬虫端已尽力拆分，仍可能在清洗阶段发现残留问题
        if "出版社" in df.columns:
            before = (df["出版社"] == "无").sum()
            df["出版社"] = df["出版社"].apply(self._clean_publisher)
            after = (df["出版社"] == "无").sum()
            if before != after:
                print(f"出版社清洗: 修复 {after - before} 条")

        if "出版日期" in df.columns:
            df["出版日期"] = df["出版日期"].apply(self._clean_pub_date)

        # ============================================================
        # 步骤3：定价清洗
        # ============================================================
        if "定价" in df.columns:
            df["定价"] = df["定价"].apply(self._clean_price)

        # ============================================================
        # 步骤4：数值字段类型转换
        # ============================================================
        # 评分：字符串 → float
        if "豆瓣评分" in df.columns:
            before = df["豆瓣评分"].notna().sum()    # 转换前有效条数
            df["豆瓣评分"] = df["豆瓣评分"].apply(self._clean_score)
            after = df["豆瓣评分"].notna().sum()     # 转换后有效条数
            print(f"评分转换: {before} -> {after} 条（丢失 {before - after} 条）")

        # 评价人数：字符串 → int
        if "评价人数" in df.columns:
            before = df["评价人数"].notna().sum()
            df["评价人数"] = df["评价人数"].apply(self._clean_rating_count)
            after = df["评价人数"].notna().sum()
            print(f"评价人数转换: {before} -> {after} 条（丢失 {before - after} 条）")

        # ============================================================
        # 步骤5：空值填充
        # ============================================================
        # 文本字段：空字符串 / None / NA → 统一填 "无"
        for col in text_columns:
            if col in df.columns:
                # replace 处理空字符串和 None
                df[col] = df[col].replace(["", None, pd.NA], self.null_fill)
                # fillna 处理 pandas 的 NaN
                df[col] = df[col].fillna(self.null_fill)

        # 数值字段（评分、评价人数）：保持 NaN 不做文本填充
        # 原因：NaN 在 pandas 中表示「缺失值」，后续计算会自动忽略
        #       如果用 "无" 填充，会影响统计计算

        # ============================================================
        # 步骤6：过滤脏数据
        # ============================================================
        initial_count = len(df)    # 记录过滤前数量

        # 过滤条件A：书名不能为空且不能是填充值"无"
        if "书名" in df.columns:
            df = df[df["书名"] != self.null_fill]          # 不是填充值
            df = df[df["书名"].notna()]                     # 不是 NaN
            df = df[df["书名"].str.strip() != ""]           # 不是空字符串

        # 过滤条件B：至少要有评分或评价人数之一
        # 两样都没有的条目没有分析价值，视为脏数据
        has_score = (
            df["豆瓣评分"].notna()
            if "豆瓣评分" in df.columns
            else pd.Series(False, index=df.index)
        )
        has_count = (
            df["评价人数"].notna()
            if "评价人数" in df.columns
            else pd.Series(False, index=df.index)
        )
        df = df[has_score | has_count]     # | 表示「或」

        filtered_count = initial_count - len(df)
        print(f"脏数据过滤: 去除 {filtered_count} 条")

        # ============================================================
        # 步骤7：按书名去重
        # ============================================================
        if "书名" in df.columns:
            before_dedup = len(df)
            # drop_duplicates 按指定列去重，keep="first" 保留第一次出现的
            df = df.drop_duplicates(subset=["书名"], keep="first")
            print(f"去重: {before_dedup} -> {len(df)} 条")

        # ============================================================
        # 步骤8：重置索引
        # ============================================================
        # 过滤和去重后，索引可能不连续（如 0,1,3,5,7）
        # reset_index(drop=True) 重新生成 0,1,2,3... 的连续索引
        df = df.reset_index(drop=True)

        # ---- 打印清洗完成信息 ----
        print(f"清洗完成！最终数据量: {len(df)} 条")
        print(f"{'='*50}")

        return df


# ================================================================
# 模块自测代码
# 用模拟数据验证清洗逻辑是否正常工作
# ================================================================
if __name__ == "__main__":
    # ---- 构造测试数据 ----
    # 包含一条「正常数据」和一条「脏数据」来验证清洗效果
    test_data = [
        {
            "书名":     "  百年孤独  \n",           # 含空格和换行 → 应被清洗
            "作者译者": "加西亚·马尔克斯",           # 正常数据
            "出版社":   "南海出版公司",              # 正常数据
            "出版日期": "2011-6",                    # 正常数据
            "定价":     "39.50元",                   # 含"元" → 应被去除
            "豆瓣评分": "9.2",                       # 字符串 → 应转为 float
            "评价人数": "125000",                    # 字符串 → 应转为 int
            "简介":     "一部魔幻现实主义巨著...\n", # 含换行 → 应被清洗
        },
        {
            "书名":     "无效书籍",                  # 正常书名
            "作者译者": "",                          # 空 → 应填"无"
            "出版社":   "",                          # 空 → 应填"无"
            "出版日期": "",                          # 空 → 应填"无"
            "定价":     "",                          # 空 → 应填"无"
            "豆瓣评分": "abc",                       # 无效评分 → 应为 NaN
            "评价人数": "",                          # 空 → 应为 NaN
            "简介":     "",                          # 空 → 应填"无"
        },
    ]

    # ---- 执行清洗 ----
    cleaner = DataCleaner()
    df = cleaner.clean(test_data)

    # ---- 查看结果 ----
    print("\n清洗结果:")
    print(df.to_string())
