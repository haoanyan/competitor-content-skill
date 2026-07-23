"""
analyzer.py — 竞品社区内容分析器

读取 crawler.py 产出的 raw_data.json，执行：
  1. 互动综合评分（B站/小红书分平台公式）
  2. 内容类型分类（关键词匹配）
  3. 词频分析（竞品数据，分平台）
  4. 高互动Top排序（竞品Top10 + 自身Top5参照）
  5. 竞品/自身数据分离

输出 analysis.json，供 reportgen.py 使用。

用法:
  python analyzer.py --input output/xxx/raw_data.json --output output/xxx/analysis.json
"""
import argparse
import json
import os
import re
import sys
import io
from datetime import datetime, timedelta
from collections import Counter, defaultdict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


# ============================================================
# 互动综合分公式（分平台）
# ============================================================
def bili_score(p):
    return p.get("play", 0) + p.get("like", 0) * 5 + p.get("danmaku", 0) * 3 + p.get("favorites", 0) * 2

def xhs_score(p):
    return p.get("likes", 0) * 5 + p.get("comments", 0) * 3 + p.get("collected", 0) * 2 + p.get("shares", 0) * 2


# ============================================================
# 内容类型分类（关键词匹配）
# ============================================================
CONTENT_TYPES = {
    "更新公告": ["更新", "补丁", "patch", "版本", "新内容", "DLC", "联动", "新增"],
    "攻略教程": ["攻略", "教程", "保姆级", "通关", "build", "配装", "技巧", "全收集", "指南", "玩法", "新手"],
    "实况录像": ["实况", "录播", "直播", "playthrough", "游玩", "通关流程", "流程"],
    "测评推荐": ["测评", "评测", "推荐", "安利", "值不值得买", "Steam评价", "种草", "试玩"],
    "速通挑战": ["速通", "speedrun", "无伤", "挑战", "极限", "世界纪录"],
    "玩家整活": ["整活", "搞笑", "沙雕", "meme", "二创", "鬼畜", "离谱", "抽象"],
    "爆料前瞻": ["爆料", "泄露", "datamine", "前瞻", "预告", "teaser", "即将"],
}

def classify_content(title, desc=""):
    text = (title + " " + desc).lower()
    for ctype, keywords in CONTENT_TYPES.items():
        for kw in keywords:
            if kw.lower() in text:
                return ctype
    return "其他"


# ============================================================
# 词频分析
# ============================================================
STOPWORDS = set(
    "的 了 是 在 我 也 都 就 还 和 与 及 给 让 被 把 向 从 到 对 为 以 于 等 之 其 此 这 那 "
    "一个 种 些 所 又 不 没 有 会 能 可以 要 想 说 做 看 听 玩 游戏 视频 笔记 分享 "
    "这个 那个 什么 怎么 为什么 多少 "
    "话题 口令 关注 转发 收藏 点赞 评论 喜欢 觉得 但是 不过 其实 然后 还是 已经 "
    "一下 也是 就是 这样 那样 怎么样 还是的话 因为 所以 而且 或者 如果".split()
)

def extract_keywords(posts, platform, game_names_to_exclude=None):
    """
    提取高频词Top20，排除游戏名本身。
    优先提取结构化标签（B站tag逗号拆分 / 小红书#hashtag），再用jieba对标题补充分词。
    """
    if game_names_to_exclude is None:
        game_names_to_exclude = []

    # 把游戏名加入jieba自定义词典，避免被拆分
    try:
        import jieba
        for gn in game_names_to_exclude:
            gname = gn.strip()
            if gname and len(gname) >= 2:
                jieba.add_word(gname)
    except ImportError:
        pass

    structured_words = []  # 结构化标签（高权重）
    jieba_words = []       # jieba分词（补充）

    for p in posts:
        title = p.get("title", "")
        tag_str = p.get("tag", "")

        # 1. 结构化标签提取（双平台统一：逗号分隔的tag字段）
        has_structured_tag = False
        for tag in tag_str.split(","):
            tag = tag.strip()
            if tag and len(tag) >= 2 and tag not in STOPWORDS:
                structured_words.append(tag)
                has_structured_tag = True

        # 2. jieba对标题分词
        # 无结构化tag时（如小红书），标题是唯一来源，权重加倍
        jieba_weight = 1 if has_structured_tag else 2
        desc = p.get("description", "")
        # 标题+正文合并分词，标题权重更高
        combined_text = title + " " + desc
        try:
            import jieba
            for w in jieba.cut(combined_text):
                w = w.strip()
                if (len(w) >= 2
                    and w not in STOPWORDS
                    and (not w.isascii() or len(w) >= 3)):
                    jieba_words.append((w, jieba_weight))
        except ImportError:
            for m in re.finditer(r'[\u4e00-\u9fff]{2,8}', combined_text):
                w = m.group()
                if w not in STOPWORDS:
                    jieba_words.append((w, jieba_weight))
            for m in re.finditer(r'[a-zA-Z]{3,}', combined_text):
                jieba_words.append((m.group().lower(), jieba_weight))

    # 合并：结构化标签计双倍权重，jieba按各自权重
    counter = Counter()
    for w in structured_words:
        counter[w] += 2
    for w, wt in jieba_words:
        counter[w] += wt

    # 排除游戏名
    for gn in game_names_to_exclude:
        for variant in [gn, gn.lower(), gn.replace(" ", ""), gn.replace(" ", "").lower()]:
            if variant in counter:
                del counter[variant]

    return counter.most_common(20)


# ============================================================
# 主分析流程
# ============================================================
def analyze(raw_data):
    """
    输入: raw_data.json 的字典
    输出: analysis 字典（可序列化为 analysis.json）
    """
    now = datetime.now()
    all_game_names = list(raw_data.keys())
    # 收集所有alt_keyword，加入分词词典和排除列表
    all_alt_keywords = []
    for gn, gd in raw_data.items():
        ak = gd.get("alt_keyword", "")
        if ak:
            all_alt_keywords.extend([k.strip() for k in ak.split(",") if k.strip()])
    all_names_for_jieba = all_game_names + all_alt_keywords

    # 竞品/自身分离
    competitor_bili, competitor_xhs = [], []
    self_bili, self_xhs = [], []
    games_summary = {}

    for game_name, game_data in raw_data.items():
        is_self = game_data["is_self"]
        bili = game_data.get("bilibili", [])
        xhs = game_data.get("xiaohongshu", [])

        # 评分 + 分类
        for p in bili:
            p["_score"] = bili_score(p)
            p["_content_type"] = classify_content(p.get("title", ""), p.get("description", ""))
        for p in xhs:
            p["_score"] = xhs_score(p)
            p["_content_type"] = classify_content(p.get("title", ""), p.get("description", ""))

        bili_sorted = sorted(bili, key=lambda x: x["_score"], reverse=True)
        xhs_sorted = sorted(xhs, key=lambda x: x["_score"], reverse=True)

        games_summary[game_name] = {
            "is_self": is_self,
            "bili_count": len(bili),
            "xhs_count": len(xhs),
            "bili_types": dict(Counter(p["_content_type"] for p in bili)),
            "xhs_types": dict(Counter(p["_content_type"] for p in xhs)),
        }

        if is_self:
            self_bili.extend(bili_sorted[:5])
            self_xhs.extend(xhs_sorted[:5])
        else:
            competitor_bili.extend(bili_sorted)
            competitor_xhs.extend(xhs_sorted)

    # 全局Top排序
    comp_bili_top10 = sorted(competitor_bili, key=lambda x: x["_score"], reverse=True)[:10]
    comp_xhs_top10 = sorted(competitor_xhs, key=lambda x: x["_score"], reverse=True)[:10]
    self_bili_top5 = sorted(self_bili, key=lambda x: x["_score"], reverse=True)[:5]
    self_xhs_top5 = sorted(self_xhs, key=lambda x: x["_score"], reverse=True)[:5]

    # 内容类型分布（仅竞品）
    bili_comp_types = Counter(p["_content_type"] for p in competitor_bili)
    xhs_comp_types = Counter(p["_content_type"] for p in competitor_xhs)

    # 词频（仅竞品）
    comp_bili_posts = [p for p in competitor_bili]
    comp_xhs_posts = [p for p in competitor_xhs]
    bili_kw = extract_keywords(comp_bili_posts, "bilibili", all_names_for_jieba)
    xhs_kw = extract_keywords(comp_xhs_posts, "xiaohongshu", all_names_for_jieba)

    # 跨平台共同热词
    bili_kw_set = set(k for k, _ in bili_kw)
    xhs_kw_set = set(k for k, _ in xhs_kw)
    common_kw = list(bili_kw_set & xhs_kw_set)

    return {
        "report_date": now.strftime("%Y-%m-%d"),
        "games": games_summary,
        "bili_competitor_top10": comp_bili_top10,
        "xhs_competitor_top10": comp_xhs_top10,
        "bili_self_top5": self_bili_top5,
        "xhs_self_top5": self_xhs_top5,
        "bili_content_types": dict(bili_comp_types),
        "xhs_content_types": dict(xhs_comp_types),
        "bili_keywords": bili_kw,
        "xhs_keywords": xhs_kw,
        "common_keywords": common_kw,
    }


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="竞品社区内容分析器")
    parser.add_argument("--input", required=True, help="raw_data.json 路径")
    parser.add_argument("--output", required=True, help="analysis.json 输出路径")
    args = parser.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    result = analyze(raw_data)

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # 控制台摘要
    print("=== 分析完成 ===")
    print(f"竞品B站Top10:")
    for i, p in enumerate(result["bili_competitor_top10"][:5]):
        print(f"  {i+1}. [{p.get('publish_time','')}] score={p['_score']} type={p['_content_type']} | {p.get('title','')[:40]}")
    print(f"\n竞品小红书Top10:")
    for i, p in enumerate(result["xhs_competitor_top10"][:5]):
        print(f"  {i+1}. [{p.get('publish_time','')}] score={p['_score']} type={p['_content_type']} | {p.get('title','')[:40]}")
    print(f"\nB站内容类型: {result['bili_content_types']}")
    print(f"小红书内容类型: {result['xhs_content_types']}")
    print(f"B站Top关键词: {[k for k,_ in result['bili_keywords'][:10]]}")
    print(f"小红书Top关键词: {[k for k,_ in result['xhs_keywords'][:10]]}")
    print(f"跨平台共同热词: {result['common_keywords']}")
    print(f"\n分析数据已保存: {args.output}")


if __name__ == "__main__":
    main()
