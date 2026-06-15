"""
主程序入口 —— 豆瓣高分图书爬虫 & 数据分析系统
=================================================
一键运行整个数据处理流水线，串联四大模块。

运行方式：
    python main.py

工作流程（四大步骤）：
    第一步 [爬虫抓取]  spider.py     →  批量抓取豆瓣高分图书榜单数据
    第二步 [数据清洗]  cleaner.py    →  去噪、格式化、类型转换、过滤脏数据
    第三步 [导出Excel]  pandas       →  生成 book_data.xlsx 表格文件
    第四步 [可视化]    visualizer.py →  生成 score_dist.png 评分分布图

项目文件结构：
    main.py          - 本文件，主程序入口（流程调度中心）
    config.py        - 统一配置文件（所有参数集中管理，修改即可全局生效）
    spider.py        - 爬虫模块（请求 + 解析 + 提取）
    cleaner.py       - 数据清洗模块（去噪 + 格式化 + 过滤）
    visualizer.py    - 可视化模块（绑图 + 统计标注）
    requirements.txt - 依赖清单（pip install -r requirements.txt）

输出产物：
    book_data.xlsx   - 清洗后的完整图书数据表
    score_dist.png   - 评分分布柱状图（适合 README 配图）
    top_books.png    - Top 10 高分图书排行图

作者：GitHub 作品集展示项目
许可：MIT License（完全开源，可用于个人/商业用途）
"""

# ---------- 标准库 ----------
import sys                          # 系统相关：程序退出码控制
import os                           # 文件系统：获取文件大小等

# ---------- 修复 Windows GBK 编码问题 ----------
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
import pandas as pd                 # 数据处理库（Excel 导出核心）

# ---------- 项目模块 ----------
from spider import DoubanBookSpider    # 爬虫模块
from cleaner import DataCleaner        # 数据清洗模块
from visualizer import ChartDrawer     # 可视化模块
import config                          # 统一配置文件


def main():
    """
    主流程调度函数 ★ 程序唯一入口 ★

    执行顺序（四步流水线）：
        爬虫抓取 → 数据清洗 → 导出Excel → 可视化制图

    每步之间通过 Python 对象传递数据：
        spider.crawl_all_pages()  →  list[dict]  原始数据
        cleaner.clean(raw_data)   →  DataFrame    清洗后数据
        df.to_excel(...)          →  .xlsx 文件   表格输出
        drawer.draw_...(df)       →  .png 文件    图表输出
    """
    # ---- 打印启动横幅 ----
    print(r"""
    ╔══════════════════════════════════════════╗
    ║     豆瓣高分图书爬虫 & 数据分析系统      ║
    ║     Douban Top Books Crawler & EDA       ║
    ╚══════════════════════════════════════════╝
    """)

    # ================================================================
    # 第一步：爬虫抓取
    # ================================================================
    # 调用 spider.py 中的 DoubanBookSpider 类
    # crawl_all_pages() 会自动处理翻页、延时、重试
    # 返回原始数据列表，每个元素是包含8个字段的 dict

    print("\n" + "=" * 50)
    print(">>> 第一步：启动爬虫，抓取豆瓣高分图书数据")
    print("=" * 50)

    # 创建爬虫实例（自动加载 config.py 中的配置）
    spider = DoubanBookSpider()

    # 开始抓取（默认爬 config.CRAWL_PAGES 页）
    raw_data = spider.crawl_all_pages()

    # ---- 检查是否获取到数据 ----
    if not raw_data:
        # 如果完全没数据，可能是网络问题或页面结构变化
        # 给出明确的排查建议，帮助用户定位问题
        print("\n[错误] 未获取到任何数据，程序终止。")
        print("可能原因：")
        print("  1. 网络连接异常，请检查网络")
        print("  2. 豆瓣页面结构变化，需要更新解析逻辑")
        print("  3. IP被暂时限制，请稍后重试")
        sys.exit(1)    # 非零退出码表示异常终止

    print(f"\n[OK] 爬虫阶段完成，共获取 {len(raw_data)} 条原始数据")

    # ================================================================
    # 第二步：数据清洗
    # ================================================================
    # 将爬虫吐出的原始数据交给 DataCleaner 处理
    # clean() 方法执行8步清洗流水线，返回干净的 DataFrame

    print("\n" + "=" * 50)
    print(">>> 第二步：数据清洗与格式化")
    print("=" * 50)

    # 创建清洗器实例
    cleaner = DataCleaner()

    # 执行完整清洗流水线
    df = cleaner.clean(raw_data)

    # ---- 检查清洗后是否有有效数据 ----
    if df.empty:
        print("\n[错误] 清洗后无有效数据，程序终止。")
        sys.exit(1)

    print(f"\n[OK] 清洗阶段完成，有效数据 {len(df)} 条")

    # ---- 打印数据概览（快速了解数据质量） ----
    print(f"\n{'─' * 50}")
    print("数据概览：")
    print(f"  字段列表: {list(df.columns)}")

    # 如果评分列有效，显示评分统计
    if "豆瓣评分" in df.columns and df["豆瓣评分"].notna().any():
        print(f"  评分范围: {df['豆瓣评分'].min():.1f} ~ {df['豆瓣评分'].max():.1f}")
        print(f"  平均评分: {df['豆瓣评分'].mean():.2f}")

    # 如果评价人数列有效，显示人数范围
    if "评价人数" in df.columns and df["评价人数"].notna().any():
        print(f"  评价人数范围: {int(df['评价人数'].min())} ~ {int(df['评价人数'].max())}")

    print(f"{'─' * 50}")

    # ================================================================
    # 第三步：导出 Excel
    # ================================================================
    # 使用 pandas 的 ExcelWriter 将 DataFrame 导出为 .xlsx 文件
    # 同时对表格做格式优化：自动列宽、冻结表头

    print("\n" + "=" * 50)
    print(">>> 第三步：导出数据到 Excel")
    print("=" * 50)

    output_excel = config.OUTPUT_EXCEL    # 从配置文件读取输出文件名

    try:
        # pd.ExcelWriter 提供比 df.to_excel() 更精细的控制
        # engine="openpyxl" 使用 openpyxl 作为底层引擎（支持 .xlsx）
        with pd.ExcelWriter(output_excel, engine="openpyxl") as writer:
            # ---- 写入数据 ----
            df.to_excel(
                writer,
                sheet_name="豆瓣高分图书",   # 工作表名称
                index=False,                 # 不导出 DataFrame 的行号索引
                na_rep="",                   # NaN 值显示为空白单元格
            )

            # ---- 格式优化 ----
            # 获取刚才写入的工作表对象
            worksheet = writer.sheets["豆瓣高分图书"]

            # 自动调整列宽：遍历每一列，根据内容长度设置合适的宽度
            for col_idx, col_name in enumerate(df.columns, 1):   # 从1开始（Excel列号从1开始）
                # 计算本列最大字符宽度
                # 取「列名长度」和「数据最大长度」中的较大值
                max_len = max(
                    len(str(col_name)),                              # 列名长度
                    df[col_name].astype(str).str.len().max()         # 数据最大长度
                    if not df[col_name].empty else 0,
                )

                # 设置列宽（中文字符显示宽度约为英文的2倍，所以乘以1.2）
                # 限制最大宽度为40，防止某一列过宽
                adjusted_width = min(max_len * 1.2 + 2, 40)

                # 将列索引转换为 Excel 列字母（1→A, 2→B, 3→C...）
                # chr(65) = 'A', chr(66) = 'B', ...
                col_letter = chr(64 + col_idx) if col_idx <= 26 else ""
                if col_letter:
                    worksheet.column_dimensions[col_letter].width = adjusted_width

            # 冻结首行（表头行固定不动，滚动时始终可见）
            # "A2" 表示冻结 A1 以上的行（即第1行）
            worksheet.freeze_panes = "A2"

        # ---- 输出文件信息 ----
        file_size = os.path.getsize(output_excel)    # 获取文件大小（字节）
        print(f"[OK] Excel文件已导出: {output_excel}")
        print(f"  文件大小: {file_size / 1024:.1f} KB")
        print(f"  数据行数: {len(df)} 行")
        print(f"  数据列数: {len(df.columns)} 列")

    except Exception as e:
        # Excel 导出失败通常是因为文件被占用或磁盘空间不足
        print(f"[错误] Excel导出失败: {e}")
        sys.exit(1)

    # ================================================================
    # 第四步：数据可视化
    # ================================================================
    # 调用 visualizer.py 中的 ChartDrawer 类
    # 绘制评分分布图（核心）和 Top 10 排行图（额外）

    print("\n" + "=" * 50)
    print(">>> 第四步：数据可视化（评分分布图）")
    print("=" * 50)

    try:
        # 创建图表绘制器实例
        drawer = ChartDrawer()

        # 绘制核心图表：评分分布柱状图
        chart_path = drawer.draw_score_distribution(df)

        if chart_path:
            print(f"[OK] 评分分布图已生成: {chart_path}")
            print(f"  可将此图片用于 README.md 配图")

            # 额外绘制：Top 10 高分图书排行图
            # 至少要有5本书才绘制（书太少没有排行意义）
            if len(df) >= 5:
                drawer.draw_top_books_bar(df, top_n=10)

    except Exception as e:
        # 可视化失败不影响数据导出（数据已经保存了）
        print(f"[警告] 可视化生成失败（不影响数据导出）: {e}")

    # ================================================================
    # 完成！输出最终报告
    # ================================================================

    print("\n" + "=" * 50)
    print(">>> 全流程执行完成！")
    print("=" * 50)

    # 打印生成的文件清单和统计信息
    print(f"""
    生成文件清单：
      |-- {output_excel}        <- 清洗后的图书数据（Excel）
      |-- score_dist.png      <- 评分分布柱状图（README配图）
      |-- top_books.png        <- Top10图书排行图（额外）

    数据统计：
      |-- 原始抓取: {len(raw_data)} 条
      |-- 清洗后:   {len(df)} 条

    项目可直接上传GitHub作为作品集展示 [OK]
    """)


# ================================================================
# 程序入口
# ================================================================
if __name__ == "__main__":
    # 启动主程序
    main()
