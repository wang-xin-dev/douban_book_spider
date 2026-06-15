"""
可视化模块 —— 豆瓣高分图书数据可视化
=========================================
使用 matplotlib 绘制专业的统计图表，用于项目展示和 README 配图。

生成图表：
    1. score_dist.png  - 评分分布柱状图（核心图表，适合README配图）
    2. top_books.png   - Top 10 高分图书横向排行图

技术要点：
    - matplotlib 是 Python 最主流的绑图库
    - 中文字体自适应（Windows/macOS/Linux）
    - 图表包含丰富的统计信息标注（均值线、统计框）
    - 高清输出（150 DPI），适合直接用于文档配图

使用示例：
    >>> from visualizer import ChartDrawer
    >>> drawer = ChartDrawer()
    >>> drawer.draw_score_distribution(df)   # 绘制评分分布图
"""

# ---------- 第三方库 ----------
import matplotlib.pyplot as plt    # 绘图核心库（pyplot 提供类似 MATLAB 的接口）
import matplotlib                  # matplotlib 本体（用于全局配置）
import numpy as np                 # 数值计算库（生成评分区间、统计数据）
import pandas as pd                # 数据处理库（接收 DataFrame 输入）

# ---------- 项目内部模块 ----------
import config                      # 统一配置文件：读取图表参数


# ================================================================
# 全局字体配置（解决中文显示问题）
# ================================================================

# matplotlib 默认不支持中文，需要手动指定中文字体
# 按优先级尝试：SimHei（Windows黑体）→ Microsoft YaHei → DejaVu Sans（兜底）
matplotlib.rcParams["font.sans-serif"] = [
    "SimHei",            # Windows 黑体（最常用）
    "Microsoft YaHei",   # Windows 微软雅黑
    "DejaVu Sans",       # Linux 兜底字体
]

# 解决负号显示问题
# 设置为 False 时，matplotlib 使用 ASCII 负号（-）替代 Unicode 负号（−）
# 可以避免某些中文字体下负号显示为方块的问题
matplotlib.rcParams["axes.unicode_minus"] = False

# 如果系统没有粗体字体，静默回退到常规字体（避免控制台刷屏 warning）
import logging
logging.getLogger("matplotlib.font_manager").setLevel(logging.ERROR)


class ChartDrawer:
    """
    图表绘制器

    设计思路：
        将图表绘制封装为独立类，每个图表类型对应一个方法。
        从 config.py 读取所有样式参数，修改配置即可全局生效。
        方法之间互相独立，可以单独调用也可以组合使用。

    核心方法：
        draw_score_distribution() - 绘制评分分布柱状图
        draw_top_books_bar()      - 绘制 Top N 图书排行图
    """

    def __init__(self):
        """
        初始化绘图器

        从 config.py 中读取所有图表样式参数：
            - figsize    : 图表尺寸（宽, 高），单位英寸
            - dpi        : 图片清晰度（每英寸像素数）
            - color      : 柱状图颜色（Material Design 绿色）
            - title      : 图表主标题
            - output_path: 输出文件路径
        """
        self.figsize     = config.CHART_FIGSIZE     # 图表尺寸
        self.dpi         = config.CHART_DPI         # 输出清晰度
        self.color       = config.CHART_COLOR       # 柱状图颜色
        self.title       = config.CHART_TITLE       # 图表标题
        self.output_path = config.OUTPUT_CHART      # 输出路径

    def draw_score_distribution(self, df: pd.DataFrame) -> str:
        """
        绘制图书评分分布柱状图 ★ 核心图表 ★

        图表内容：
            - 横轴：评分区间（如 8.0-8.5、8.5-9.0...）
            - 纵轴：该区间内的图书数量
            - 红色虚线：平均评分位置
            - 右上角文本框：最高分/最低分/中位数/标准差
            - 每个柱子上方：该区间的具体数量

        参数:
            df : 清洗后的 DataFrame（必须包含"豆瓣评分"列）

        返回:
            生成的图片文件路径，失败返回空字符串

        使用示例：
            drawer = ChartDrawer()
            path = drawer.draw_score_distribution(df)
            # path = "score_dist.png"
        """
        # ---- 防御性检查 ----
        if df is None or df.empty:
            print("[警告] 数据为空，无法绘制图表")
            return ""

        if "豆瓣评分" not in df.columns:
            print("[警告] 数据中缺少'豆瓣评分'列，无法绘制")
            return ""

        # ---- 提取有效评分数据 ----
        # dropna() 会丢弃所有 NaN 值（即清洗阶段标记为无效的评分）
        scores = df["豆瓣评分"].dropna()

        if len(scores) == 0:
            print("[警告] 没有有效的评分数据")
            return ""

        print(f"\n绘制评分分布图（有效评分数据: {len(scores)} 条）...")

        # ============================================================
        # 步骤1：创建画布
        # ============================================================
        # plt.subplots() 同时返回 Figure（画布）和 Axes（坐标系）
        # figsize 参数控制图片尺寸
        fig, ax = plt.subplots(figsize=self.figsize)

        # ============================================================
        # 步骤2：定义评分区间（bins）
        # ============================================================
        # 高分图书榜的评分通常在 6.0 ~ 10.0 之间
        # 以 0.5 分为步长划分区间，如 6.0-6.5, 6.5-7.0...
        bins = np.arange(6.0, 10.1, 0.5)

        # 如果数据中存在低于 6.0 的评分，自动扩展区间范围
        # 这样图表更贴合实际数据分布
        if scores.min() < 6.0:
            bins = np.arange(
                max(0, int(scores.min()) - 1),           # 从最低分减1开始
                min(10, int(scores.max()) + 1.5),        # 到最高分加1.5结束
                0.5                                       # 步长0.5
            )

        # ============================================================
        # 步骤3：统计各区间频数
        # ============================================================
        # np.histogram 返回两个数组：
        #   counts: 每个区间的数据条数
        #   edges:  区间的边界值
        counts, edges = np.histogram(scores, bins=bins)

        # 生成区间标签，如 "8.0-8.5"、"8.5-9.0"
        bin_labels = [
            f"{edges[i]:.1f}-{edges[i+1]:.1f}"
            for i in range(len(edges) - 1)
        ]

        # ============================================================
        # 步骤4：绘制柱状图
        # ============================================================
        # 柱子的 x 坐标（0, 1, 2, 3...）
        x_pos = np.arange(len(bin_labels))

        # ax.bar() 绘制垂直柱状图
        bars = ax.bar(
            x_pos,                        # x 坐标
            counts,                       # 柱子的高度（数量）
            width=0.7,                    # 柱子宽度（0.7 表示留 30% 空隙）
            color=self.color,             # 柱子颜色
            edgecolor="white",            # 柱子边框颜色
            linewidth=0.5,                # 边框线宽度
            alpha=0.85,                   # 透明度（0.85 略透，有质感）
        )

        # ============================================================
        # 步骤5：在柱子上方添加数据标签
        # ============================================================
        # 每个柱子顶部显示该区间的图书数量
        for bar, count in zip(bars, counts):
            if count > 0:    # 数量为 0 的区间不显示标签
                ax.text(
                    bar.get_x() + bar.get_width() / 2,   # x: 柱子中心
                    bar.get_height() + 0.3,               # y: 柱子顶部稍上方
                    str(count),                            # 文本: 数量
                    ha="center",                           # 水平居中
                    va="bottom",                           # 垂直底部对齐
                    fontsize=9,                            # 字体大小
                    fontweight="bold",                     # 加粗
                )

        # ============================================================
        # 步骤6：绘制平均分参考线
        # ============================================================
        mean_score = scores.mean()

        # axhline 绘制水平线
        ax.axhline(
            y=counts.max() * 0.85,         # y 坐标：最高柱子 85% 的位置
            color="#E53935",                # 红色（Material Design Red 600）
            linestyle="--",                 # 虚线样式
            linewidth=1.5,                  # 线宽
            alpha=0.7,                      # 透明度
            label=f"平均评分: {mean_score:.2f}",   # 图例文本
        )

        # ============================================================
        # 步骤7：设置坐标轴
        # ============================================================
        # x 轴标签
        ax.set_xlabel("评分区间", fontsize=12, labelpad=10)
        # y 轴标签
        ax.set_ylabel("图书数量（本）", fontsize=12, labelpad=10)
        # x 轴刻度位置
        ax.set_xticks(x_pos)
        # x 轴刻度标签（旋转45度避免重叠）
        ax.set_xticklabels(bin_labels, rotation=45, ha="right", fontsize=9)

        # ============================================================
        # 步骤8：设置标题
        # ============================================================
        ax.set_title(
            f"{self.title}\n（共 {len(scores)} 本书，平均分 {mean_score:.2f}）",
            fontsize=14,         # 标题字号
            fontweight="bold",   # 标题加粗
            pad=15,              # 标题与图表的间距
        )

        # ============================================================
        # 步骤9：添加图例
        # ============================================================
        # 图例显示在右上角，半透明背景
        ax.legend(loc="upper right", fontsize=10, framealpha=0.9)

        # ============================================================
        # 步骤10：添加网格线
        # ============================================================
        # 只在 y 轴方向显示网格线（帮助读取数量值）
        ax.yaxis.grid(True, linestyle="--", alpha=0.3)
        # 将网格线置于柱子后面（避免遮挡）
        ax.set_axisbelow(True)

        # ============================================================
        # 步骤11：设置 y 轴范围
        # ============================================================
        # y 轴从 0 开始（柱状图规范），上限为最大值的 120%
        ax.set_ylim(0, counts.max() * 1.2)

        # ============================================================
        # 步骤12：添加统计信息文本框
        # ============================================================
        # 在图表右上角显示关键统计指标
        stats_text = (
            f"最高分: {scores.max():.1f}\n"
            f"最低分: {scores.min():.1f}\n"
            f"中位数: {scores.median():.1f}\n"
            f"标准差: {scores.std():.2f}"
        )
        ax.text(
            0.98,                # x: 相对位置 98%（右侧）
            0.95,                # y: 相对位置 95%（顶部）
            stats_text,          # 文本内容
            transform=ax.transAxes,    # 使用相对坐标（0-1）
            fontsize=9,                 # 字号
            verticalalignment="top",    # 垂直顶部对齐
            horizontalalignment="right",# 水平右对齐
            bbox=dict(                  # 文本框样式
                boxstyle="round,pad=0.5",  # 圆角，内边距0.5
                facecolor="#F5F5F5",       # 浅灰背景
                alpha=0.8,                 # 80% 不透明度
            ),
        )

        # ============================================================
        # 步骤13：调整布局 & 保存
        # ============================================================
        # tight_layout 自动优化子图间距，防止文字被截断
        plt.tight_layout()

        # 保存为 PNG 图片
        # bbox_inches="tight" 裁掉多余空白
        # facecolor="white"   白色背景
        fig.savefig(
            self.output_path,
            dpi=self.dpi,
            bbox_inches="tight",
            facecolor="white",
        )

        # 关闭 Figure，释放内存
        plt.close(fig)

        print(f"图表已保存: {self.output_path}")
        return self.output_path

    def draw_top_books_bar(self, df: pd.DataFrame, top_n: int = 10) -> str:
        """
        绘制 Top N 高分图书横向排行图（额外可视化）

        这是一个横向柱状图，按评分从高到低排列，直观展示哪些书评分最高。

        参数:
            df    : 清洗后的 DataFrame
            top_n : 显示前 N 本书（默认10本）

        返回:
            生成的图片文件路径
        """
        # ---- 防御性检查 ----
        if df is None or df.empty:
            print("[警告] 数据为空，无法绘制")
            return ""

        # ---- 按评分降序，取前 N 本 ----
        top_df = df.sort_values("豆瓣评分", ascending=False).head(top_n)

        if len(top_df) == 0:
            return ""

        # ---- 处理书名（过长则截断） ----
        # lambda 函数：书名超过15个字符就截断并加 "..."
        names = top_df["书名"].apply(
            lambda x: x[:15] + "..." if len(str(x)) > 15 else str(x)
        )

        # ---- 创建画布 ----
        fig, ax = plt.subplots(figsize=(10, 6))

        # ---- 生成渐变色 ----
        # viridis 是 matplotlib 内置的色带（从紫到黄）
        # np.linspace(0.2, 0.9, N) 在色带上均匀取 N 个点
        colors = plt.cm.viridis(np.linspace(0.2, 0.9, len(top_df)))

        # ---- 绘制横向柱状图 ----
        bars = ax.barh(
            range(len(top_df)),               # y 坐标（0,1,2...）
            top_df["豆瓣评分"].values,         # 柱子宽度 = 评分
            color=colors,                      # 渐变色
        )

        # ---- 添加数据标签 ----
        for bar, score in zip(bars, top_df["豆瓣评分"].values):
            ax.text(
                bar.get_width() + 0.05,                  # 柱子右侧稍远处
                bar.get_y() + bar.get_height() / 2,       # 柱子中心高度
                f"{score:.1f}",                            # 评分（1位小数）
                va="center",                               # 垂直居中
                fontsize=10,
                fontweight="bold",
            )

        # ---- 设置坐标轴 ----
        ax.set_yticks(range(len(top_df)))                # y 轴刻度位置
        ax.set_yticklabels(names.values, fontsize=9)     # y 轴标签（书名）
        ax.invert_yaxis()                                 # 反转 y 轴（最高分在上面）
        ax.set_xlabel("豆瓣评分", fontsize=12)            # x 轴标签
        ax.set_title(                                     # 标题
            f"豆瓣高分图书 Top {top_n}",
            fontsize=14,
            fontweight="bold",
        )

        # ---- 设置 x 轴范围（留白让标签不溢出） ----
        ax.set_xlim(
            top_df["豆瓣评分"].min() - 0.5,
            top_df["豆瓣评分"].max() + 0.3,
        )

        # ---- 添加网格线 ----
        ax.xaxis.grid(True, linestyle="--", alpha=0.3)

        # ---- 调整布局 & 保存 ----
        plt.tight_layout()

        output_path = "top_books.png"
        fig.savefig(output_path, dpi=self.dpi, bbox_inches="tight", facecolor="white")
        plt.close(fig)

        print(f"Top{top_n}图表已保存: {output_path}")
        return output_path


# ================================================================
# 模块自测代码
# 生成随机模拟数据来验证图表绘制是否正常
# ================================================================
if __name__ == "__main__":
    # ---- 构造模拟数据 ----
    # np.random.uniform(7.0, 9.5, 20) 生成20个 7.0~9.5 之间的随机浮点数
    # .round(1) 保留1位小数，模拟真实的豆瓣评分分布
    test_df = pd.DataFrame({
        "书名": [f"测试书籍{i}" for i in range(20)],
        "豆瓣评分": np.random.uniform(7.0, 9.5, 20).round(1),
    })

    # ---- 创建绘图器并执行 ----
    drawer = ChartDrawer()

    # 测试评分分布图
    drawer.draw_score_distribution(test_df)

    # 测试 Top 10 排行图
    drawer.draw_top_books_bar(test_df, top_n=10)

    print("可视化模块测试完成！")
