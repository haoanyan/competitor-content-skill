"""
reportgen.py — HTML报告生成器

读取 analysis.json + raw_data.json，生成单一HTML报告。
游戏特有信息（产品分析、文案、insights、竞品描述）通过 --extra JSON 文件传入。

用法:
  python reportgen.py \
    --analysis output/xxx/analysis.json \
    --raw output/xxx/raw_data.json \
    --output output/xxx/report.html \
    --extra output/xxx/extra.json

extra.json 格式（可选，缺省时对应区块跳过）:
{
  "self_game_name": "幻想放置远征队",
  "game_descriptions": { "游戏名": "一句话描述" },
  "product_analysis": { "name": "...", "desc": "...", "features": [...], "tones": [...], "tags": [...] },
  "insights": ["规律1", "规律2", ...],
  "copies": [
    { "angle": "测评安利型", "source_platform": "B站", "title": "...", "body": "...", "tags": [...], "image_suggestion": "...", "reference": "..." },
    ...
  ],
  "competitor_note": "竞品选择依据说明"
}
"""
import argparse
import json
import os
import sys
import io
import html as html_module
from datetime import datetime

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

# ============================================================
# 常量
# ============================================================
GAME_PALETTE = ["#6c5ce7", "#00b894", "#e17055", "#0984e3", "#fdcb6e", "#e84393", "#00cec9", "#fab1a0"]
TYPE_COLORS = {
    "更新公告": "#3498db", "攻略教程": "#2ecc71", "实况录像": "#1abc9c",
    "测评推荐": "#e67e22", "速通挑战": "#e74c3c", "玩家整活": "#fd79a8",
    "爆料前瞻": "#9b59b6", "其他": "#95a5a6",
}
COPY_CARD_COLORS = [
    ("border-left-color: #ff6b6b;", "linear-gradient(135deg, #fff5f5, #fffafa)"),
    ("border-left-color: #51cf66;", "linear-gradient(135deg, #f0fff4, #f7fff9)"),
    ("border-left-color: #339af0;", "linear-gradient(135deg, #f0f7ff, #f5faff)"),
]
SOURCE_PLATFORM_COLORS = {
    "B站": ("#FB7299", "#ffeef3"),
    "小红书": ("#FF2442", "#fff0f2"),
    "跨平台": ("#6c5ce7", "#f0edff"),
}


def esc(s):
    if not s:
        return ""
    return html_module.escape(str(s))


def days_ago(pub_time, now=None):
    if not pub_time:
        return "?"
    if now is None:
        now = datetime.now()
    try:
        dt = datetime.strptime(pub_time, "%Y-%m-%d")
        d = (now - dt).days
        if d == 0:
            return "今天"
        elif d == 1:
            return "昨天"
        return f"{d}天前"
    except Exception:
        return "?"


def game_color_map(game_names):
    """游戏名 -> 颜色，自身用紫色，竞品按顺序分配"""
    colors = {}
    for i, name in enumerate(game_names):
        colors[name] = GAME_PALETTE[i % len(GAME_PALETTE)]
    return colors


# ============================================================
# HTML构建函数
# ============================================================
def build_css():
    return """<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Segoe UI', 'Microsoft YaHei', sans-serif; background: linear-gradient(135deg, #f0f4ff 0%, #fff5f7 100%); color: #2d3436; line-height: 1.6; }
.container { max-width: 1200px; margin: 0 auto; padding: 20px; }
.header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%); color: white; padding: 40px 30px; border-radius: 16px; margin-bottom: 24px; box-shadow: 0 8px 32px rgba(15,52,96,0.3); }
.header h1 { font-size: 28px; margin-bottom: 8px; }
.header .subtitle { font-size: 14px; opacity: 0.8; margin-bottom: 16px; }
.header .stats { display: flex; gap: 20px; flex-wrap: wrap; }
.header .stat-item { background: rgba(255,255,255,0.1); padding: 12px 20px; border-radius: 10px; border: 1px solid rgba(255,255,255,0.15); }
.header .stat-item .num { font-size: 24px; font-weight: bold; }
.header .stat-item .label { font-size: 12px; opacity: 0.7; }
.header .bili-badge { color: #FB7299; }
.header .xhs-badge { color: #FF2442; }
.section { background: white; border-radius: 14px; padding: 28px; margin-bottom: 20px; box-shadow: 0 4px 20px rgba(0,0,0,0.06); }
.section-title { font-size: 20px; font-weight: 700; margin-bottom: 20px; padding-bottom: 12px; border-bottom: 3px solid #6c5ce7; display: flex; align-items: center; gap: 8px; }
.section-title .icon { font-size: 24px; }
.comp-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(250px, 1fr)); gap: 16px; }
.comp-card { border-radius: 12px; padding: 20px; border-left: 5px solid; transition: transform 0.2s; box-shadow: 0 2px 12px rgba(0,0,0,0.05); }
.comp-card:hover { transform: translateY(-3px); box-shadow: 0 6px 20px rgba(0,0,0,0.1); }
.comp-card.self { background: linear-gradient(135deg, #f3f0ff, #faf7ff); }
.comp-card.comp { background: #f9f9f9; }
.comp-card h3 { font-size: 16px; margin-bottom: 8px; }
.comp-card .badge { display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 600; color: white; margin-bottom: 8px; }
.comp-card .data-row { font-size: 13px; color: #636e72; margin-top: 4px; }
.comp-card .data-row .platform-tag { font-weight: 600; }
.wordcloud { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; padding: 10px 0; }
.wordcloud .word { display: inline-block; padding: 4px 12px; border-radius: 20px; font-weight: 600; transition: transform 0.2s; cursor: default; }
.wordcloud .word:hover { transform: scale(1.15); }
.dual-chart { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
@media (max-width: 768px) { .dual-chart { grid-template-columns: 1fr; } }
.dual-chart-col h4 { font-size: 14px; margin-bottom: 12px; text-align: center; padding: 6px; border-radius: 8px; color: white; }
.dual-chart-col.bili h4 { background: #FB7299; }
.dual-chart-col.xhs h4 { background: #FF2442; }
.type-chart { margin: 16px 0; }
.type-bar-row { display: flex; align-items: center; gap: 12px; margin-bottom: 10px; }
.type-bar-label { width: 100px; font-size: 13px; font-weight: 600; text-align: right; }
.type-bar-container { flex: 1; height: 28px; background: #f0f0f0; border-radius: 14px; overflow: hidden; position: relative; }
.type-bar-fill { height: 100%; border-radius: 14px; display: flex; align-items: center; justify-content: flex-end; padding-right: 10px; color: white; font-size: 12px; font-weight: 600; transition: width 0.5s; }
.type-bar-pct { width: 50px; font-size: 12px; color: #636e72; }
.top-table { width: 100%; border-collapse: collapse; margin: 12px 0; font-size: 13px; table-layout: fixed; }
.top-table th { background: #f5f6fa; padding: 10px 8px; text-align: left; font-weight: 600; border-bottom: 2px solid #dfe6e9; white-space: nowrap; }
.top-table td { padding: 10px 8px; border-bottom: 1px solid #f0f0f0; vertical-align: top; word-wrap: break-word; }
.top-table tr:hover { background: #f8f9fa; }
.top-table .rank { font-weight: 700; text-align: center; width: 40px; }
.top-table .rank-1 { color: #ffd700; } .top-table .rank-2 { color: #c0c0c0; } .top-table .rank-3 { color: #cd7f32; }
.top-table th:nth-child(2), .top-table td:nth-child(2) { width: 25%; }
.top-table .game-tag { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; color: white; white-space: nowrap; max-width: 120px; overflow: hidden; text-overflow: ellipsis; vertical-align: middle; }
.top-table .type-tag { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 11px; font-weight: 600; color: white; white-space: nowrap; vertical-align: middle; }
.top-table .time-cell { font-size: 12px; color: #636e72; white-space: nowrap; }
.top-table .score { font-weight: 700; color: #e17055; }
.top-table .self-row { background: #f8f7ff; }
.table-header-row { display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }
.table-header-row h4 { font-size: 16px; }
.platform-icon { padding: 4px 12px; border-radius: 8px; color: white; font-size: 13px; font-weight: 600; }
.copy-card { border-radius: 14px; padding: 24px; margin-bottom: 16px; border-left: 6px solid; box-shadow: 0 4px 16px rgba(0,0,0,0.06); }
.copy-card h3 { font-size: 18px; margin-bottom: 12px; }
.copy-card .copy-title { font-size: 17px; font-weight: 700; margin-bottom: 10px; padding: 10px 14px; background: rgba(255,255,255,0.6); border-radius: 8px; }
.copy-card .copy-body { font-size: 14px; line-height: 1.8; margin-bottom: 12px; padding: 12px 14px; background: rgba(255,255,255,0.6); border-radius: 8px; }
.copy-card .copy-tags { margin-bottom: 10px; }
.copy-card .copy-tag { display: inline-block; padding: 3px 10px; background: #e3f2fd; color: #1976d2; border-radius: 20px; font-size: 12px; margin-right: 6px; margin-bottom: 4px; }
.copy-card .copy-image { font-size: 13px; color: #636e72; padding: 10px 14px; background: rgba(255,255,255,0.6); border-radius: 8px; margin-bottom: 10px; }
.copy-card .copy-source { font-size: 12px; color: #999; margin-bottom: 12px; }
.product-card { background: linear-gradient(135deg, #f3f0ff, #eef2ff); border-radius: 12px; padding: 20px; border-left: 5px solid #6c5ce7; }
.product-card h3 { font-size: 17px; margin-bottom: 12px; color: #6c5ce7; }
.product-card .feature { display: inline-block; padding: 4px 12px; background: white; border-radius: 20px; font-size: 13px; margin: 3px; border: 1px solid #ddd; }
.insight-card { background: #fff8e1; border-radius: 10px; padding: 16px; margin-bottom: 10px; border-left: 4px solid #ffc107; }
.insight-card .num { font-weight: 700; color: #f39c12; }
.footer { text-align: center; padding: 20px; color: #999; font-size: 12px; }
@media (max-width: 600px) { .header .stats { flex-direction: column; } .top-table { font-size: 11px; } .top-table th, .top-table td { padding: 6px 4px; } }
</style>"""


def build_wordcloud(keywords, max_freq, common_kw_set):
    if not keywords:
        return "<p style='color:#999;'>无数据</p>"
    html = '<div class="wordcloud">'
    for word, freq in keywords[:20]:
        ratio = freq / max_freq if max_freq > 0 else 0.3
        size = int(14 + ratio * 18)
        if ratio > 0.7:
            color, bg = "#e74c3c", "#fadbd8"
        elif ratio > 0.4:
            color, bg = "#e67e22", "#fdebd0"
        elif ratio > 0.2:
            color, bg = "#27ae60", "#d5f5e3"
        else:
            color, bg = "#3498db", "#d6eaf8"
        is_common = word in common_kw_set
        border = "border: 2px solid #6c5ce7;" if is_common else ""
        title = f"频次:{freq}" + (" (跨平台热词)" if is_common else "")
        html += f'<span class="word" style="font-size:{size}px; color:{color}; background:{bg}; {border}" title="{title}">{esc(word)}</span>'
    html += '</div>'
    return html


def build_type_chart(type_counts, total):
    if not type_counts:
        return "<p style='color:#999;'>无数据</p>"
    html = '<div class="type-chart">'
    for ctype, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
        pct = (count / total * 100) if total > 0 else 0
        color = TYPE_COLORS.get(ctype, "#95a5a6")
        html += f'<div class="type-bar-row"><div class="type-bar-label">{esc(ctype)}</div><div class="type-bar-container"><div class="type-bar-fill" style="width:{pct}%; background:{color};">{count}</div></div><div class="type-bar-pct">{pct:.0f}%</div></div>'
    html += '</div>'
    return html


def build_top_table(posts, platform, is_self, game_colors, raw_data, now):
    if not posts:
        return "<p style='color:#999;'>无数据</p>"

    # Build post->game map from raw_data
    post_game_map = {}
    for gn, gd in raw_data.items():
        posts_list = gd.get("bilibili", []) if platform == "bili" else gd.get("xiaohongshu", [])
        for p in posts_list:
            key = p.get("bvid", "") if platform == "bili" else p.get("link", "")
            post_game_map[key] = gn

    html = '<table class="top-table">'
    html += '<tr><th class="rank">#</th><th>标题</th><th>游戏</th><th>类型</th><th>发布时间</th><th>距今</th>'
    if platform == "bili":
        html += '<th>播放</th><th>点赞</th>'
    else:
        html += '<th>点赞</th><th>评论</th>'
    html += '<th>综合分</th><th>链接</th></tr>'

    for i, p in enumerate(posts):
        rank_class = f"rank-{i+1}" if i < 3 else ""
        row_class = "self-row" if is_self else ""
        if platform == "bili":
            key = p.get("bvid", "")
            game_name = post_game_map.get(key, "")
            link = p.get("link", "")
            play = p.get("play", 0)
            like = p.get("like", 0)
            metric1 = f"{play:,}" if play >= 10000 else str(play)
            metric2 = f"{like:,}"
            link_text = "BV" + p.get("bvid", "")[-8:]
        else:
            key = p.get("link", "")
            game_name = post_game_map.get(key, "")
            link = p.get("link", "")
            metric1 = str(p.get("likes", 0))
            metric2 = str(p.get("comments", 0))
            link_text = "笔记"

        color = game_colors.get(game_name, "#636e72")
        ctype = p.get("_content_type", "其他")
        type_color = TYPE_COLORS.get(ctype, "#95a5a6")
        pub_time = p.get("publish_time", "未知")
        da = days_ago(pub_time, now)
        score = p.get("_score", 0)
        title = p.get("title", "")[:45]

        html += f'<tr class="{row_class}"><td class="rank {rank_class}">{i+1}</td><td>{esc(title)}</td><td><span class="game-tag" style="background:{color};">{esc(game_name)}</span></td><td><span class="type-tag" style="background:{type_color};">{esc(ctype)}</span></td><td class="time-cell">{esc(pub_time)}</td><td class="time-cell">{da}</td><td>{metric1}</td><td>{metric2}</td><td class="score">{score:,}</td><td><a href="{esc(link)}" target="_blank" style="font-size:12px;color:#3498db;">{link_text}</a></td></tr>'

    html += '</table>'
    return html


def build_copy_card(copy, index):
    border, bg = COPY_CARD_COLORS[index % len(COPY_CARD_COLORS)]
    src_platform = copy.get("source_platform", "")
    sp_color, sp_bg = SOURCE_PLATFORM_COLORS.get(src_platform, ("#6c5ce7", "#f0edff"))

    tags_html = "".join(f'<span class="copy-tag">#{esc(t)}</span>' for t in copy.get("tags", []))

    return f"""<div class="copy-card" style="{border} background: {bg};">
  <h3>文案{['一','二','三'][index]}：{esc(copy.get('angle',''))} <span style="font-size:12px; font-weight:400; color:{sp_color}; background:{sp_bg}; padding:2px 8px; border-radius:10px;">灵感来源：{esc(src_platform)}</span></h3>
  <div class="copy-title">{esc(copy.get('title',''))}</div>
  <div class="copy-body">{esc(copy.get('body',''))}</div>
  <div class="copy-tags">{tags_html}</div>
  <div class="copy-image"><strong>配图建议：</strong>{esc(copy.get('image_suggestion',''))}</div>
  <div class="copy-source"><strong>参考来源：</strong>{esc(copy.get('reference',''))}</div>
  {f'<div class="copy-source"><strong>竞品原文：</strong>{esc(copy.get("reference_snippet"))}</div>' if copy.get('reference_snippet') else ''}
</div>"""


# ============================================================
# 主生成流程
# ============================================================
def generate_report(analysis, raw_data, extra=None):
    now = datetime.now()
    report_date = analysis.get("report_date", now.strftime("%Y-%m-%d"))
    extra = extra or {}
    self_game_name = extra.get("self_game_name", "")
    game_descs = extra.get("game_descriptions", {})
    game_names = list(analysis.get("games", {}).keys())
    game_colors = game_color_map(game_names)

    total_bili = sum(g["bili_count"] for g in analysis["games"].values())
    total_xhs = sum(g["xhs_count"] for g in analysis["games"].values())
    num_comps = sum(1 for g in analysis["games"].values() if not g["is_self"])

    bili_types = analysis.get("bili_content_types", {})
    xhs_types = analysis.get("xhs_content_types", {})
    bili_type_total = sum(bili_types.values()) or 1
    xhs_type_total = sum(xhs_types.values()) or 1
    bili_kw = analysis.get("bili_keywords", [])
    xhs_kw = analysis.get("xhs_keywords", [])
    bili_kw_max = bili_kw[0][1] if bili_kw else 1
    xhs_kw_max = xhs_kw[0][1] if xhs_kw else 1
    common_kw_set = set(analysis.get("common_keywords", []))

    parts = []

    # HTML head + CSS
    parts.append(f'<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>竞品社区内容分析报告 - {esc(self_game_name)}</title>{build_css()}</head><body><div class="container">')

    # Header
    parts.append(f'<div class="header"><h1>竞品社区内容分析报告</h1><div class="subtitle">{esc(self_game_name)} | 报告日期: {report_date} | B站 + 小红书双平台</div><div class="stats"><div class="stat-item"><div class="num">{len(game_names)}</div><div class="label">游戏数（1自身 + {num_comps}竞品）</div></div><div class="stat-item"><div class="num bili-badge">{total_bili}</div><div class="label">B站内容（视频）</div></div><div class="stat-item"><div class="num xhs-badge">{total_xhs}</div><div class="label">小红书内容（笔记）</div></div><div class="stat-item"><div class="num">{total_bili + total_xhs}</div><div class="label">总内容量</div></div></div></div>')

    # Section 1: 竞品识别
    parts.append('<div class="section"><div class="section-title"><span class="icon">1</span> 竞品识别</div><div class="comp-grid">')
    for gn, gi in analysis["games"].items():
        is_self = gi["is_self"]
        color = game_colors.get(gn, "#636e72")
        card_class = "comp-card self" if is_self else "comp-card comp"
        badge_text = "自身产品" if is_self else "竞品"
        desc = game_descs.get(gn, "")
        parts.append(f'<div class="{card_class}" style="border-left-color:{color};"><span class="badge" style="background:{color};">{badge_text}</span><h3>{esc(gn)}</h3><div style="font-size:13px;color:#636e72;margin-bottom:8px;">{esc(desc)}</div><div class="data-row"><span class="platform-tag" style="color:#FB7299;">B站</span> {gi["bili_count"]} 条视频</div><div class="data-row"><span class="platform-tag" style="color:#FF2442;">小红书</span> {gi["xhs_count"]} 条笔记</div></div>')
    parts.append('</div>')
    if extra.get("competitor_note"):
        parts.append(f'<div style="margin-top:16px;padding:14px;background:#f8f9fa;border-radius:8px;font-size:13px;color:#636e72;"><strong>竞品选择依据：</strong>{esc(extra["competitor_note"])}</div>')
    parts.append('</div>')

    # Section 2: 词云
    parts.append('<div class="section"><div class="section-title"><span class="icon">2</span> 高频话题词云（双平台，仅竞品）</div><div style="font-size:13px;color:#636e72;margin-bottom:16px;">紫色边框 = 跨平台共同热词 | 字号 = 词频 | 颜色：红/橙=高频，绿/蓝=低频</div><div class="dual-chart"><div class="dual-chart-col bili"><h4>B站热词 Top20</h4>')
    parts.append(build_wordcloud(bili_kw, bili_kw_max, common_kw_set))
    parts.append('</div><div class="dual-chart-col xhs"><h4>小红书热词 Top20</h4>')
    parts.append(build_wordcloud(xhs_kw, xhs_kw_max, common_kw_set))
    parts.append('</div></div>')
    if common_kw_set:
        parts.append('<div style="margin-top:16px;padding:14px;background:linear-gradient(135deg,#f3f0ff,#eeeaff);border-radius:10px;border-left:4px solid #6c5ce7;"><strong style="color:#6c5ce7;">跨平台共同热词：</strong>')
        for kw in common_kw_set:
            parts.append(f'<span style="display:inline-block;padding:3px 10px;background:#6c5ce7;color:white;border-radius:20px;font-size:12px;margin:3px;">{esc(kw)}</span>')
        parts.append('<div style="font-size:12px;color:#636e72;margin-top:8px;">这些话题在B站和小红书均高频出现，是跨平台行业热点。</div></div>')
    parts.append('</div>')

    # Section 3: 内容类型分布
    parts.append('<div class="section"><div class="section-title"><span class="icon">3</span> 内容类型分布（双平台对比，仅竞品）</div><div class="dual-chart"><div class="dual-chart-col bili"><h4>B站内容类型</h4>')
    parts.append(build_type_chart(bili_types, bili_type_total))
    parts.append('</div><div class="dual-chart-col xhs"><h4>小红书内容类型</h4>')
    parts.append(build_type_chart(xhs_types, xhs_type_total))
    parts.append('</div></div></div>')

    # Section 4: Top10
    parts.append('<div class="section"><div class="section-title"><span class="icon">4</span> 竞品高互动内容 Top10</div><div class="table-header-row"><span class="platform-icon" style="background:#FB7299;">B站</span><h4>竞品 B站 高互动 Top10</h4></div>')
    parts.append(build_top_table(analysis.get("bili_competitor_top10", []), "bili", False, game_colors, raw_data, now))
    parts.append('<div style="margin-top:24px;" class="table-header-row"><span class="platform-icon" style="background:#FF2442;">小红书</span><h4>竞品 小红书 高互动 Top10</h4></div>')
    parts.append(build_top_table(analysis.get("xhs_competitor_top10", []), "xhs", False, game_colors, raw_data, now))
    # Self top5
    self_bili = analysis.get("bili_self_top5", [])
    self_xhs = analysis.get("xhs_self_top5", [])
    if self_bili or self_xhs:
        parts.append(f'<div style="margin-top:24px;" class="table-header-row"><span class="platform-icon" style="background:#6c5ce7;">自身参照</span><h4>{esc(self_game_name)} 自身高互动 Top5（参照）</h4></div><div style="font-size:13px;color:#636e72;margin-bottom:8px;">以下为自身游戏数据，仅作参照对比，非分析重点。</div>')
        if self_bili:
            parts.append('<div style="font-size:13px;font-weight:600;color:#FB7299;margin:10px 0 5px;">B站 Top5</div>')
            parts.append(build_top_table(self_bili, "bili", True, game_colors, raw_data, now))
        if self_xhs:
            parts.append('<div style="font-size:13px;font-weight:600;color:#FF2442;margin:12px 0 5px;">小红书 Top5</div>')
            parts.append(build_top_table(self_xhs, "xhs", True, game_colors, raw_data, now))
    parts.append('</div>')

    # Section 5: Insights（可选）
    insights = extra.get("insights", [])
    if insights:
        parts.append('<div class="section"><div class="section-title"><span class="icon">5</span> 竞品高互动特征规律</div>')
        for i, insight in enumerate(insights):
            parts.append(f'<div class="insight-card"><span class="num">{i+1}.</span> {esc(insight)}</div>')
        parts.append('</div>')

    # Section 6: 产品特点分析（可选）
    pa = extra.get("product_analysis")
    if pa:
        parts.append('<div class="section"><div class="section-title"><span class="icon">6</span> 产品特点分析</div><div class="product-card">')
        parts.append(f'<h3>{esc(pa.get("name",""))}</h3><p style="font-size:14px;margin-bottom:12px;">{esc(pa.get("desc",""))}</p>')
        for label, key in [("核心卖点", "features"), ("适合文案调性", "tones"), ("Steam标签", "tags")]:
            items = pa.get(key, [])
            if items:
                parts.append(f'<div style="margin-bottom:10px;"><strong style="font-size:13px;">{label}：</strong>')
                parts.append(''.join(f'<span class="feature">{esc(f)}</span>' for f in items))
                parts.append('</div>')
        parts.append('</div></div>')

    # Section 7: 文案审核稿（可选）
    copies = extra.get("copies", [])
    if copies:
        parts.append('<div class="section"><div class="section-title"><span class="icon">7</span> 发布文案审核稿（3条）</div><div style="font-size:13px;color:#636e72;margin-bottom:16px;">以下文案基于竞品高互动内容规律 + 产品特点生成，需人工审核后发布。每条标注灵感来源平台。</div>')
        for i, copy in enumerate(copies):
            parts.append(build_copy_card(copy, i))
        parts.append('</div>')

    # Footer
    parts.append(f'<div class="footer"><p>竞品社区内容分析报告 | {esc(self_game_name)} | 生成日期: {report_date}</p><p>B站（视频平台）+ 小红书（图文平台）双平台分析 | 数据用于运营参考，文案需人工审核后发布</p><p>Powered by competitor-content skill</p></div>')

    parts.append('</div></body></html>')
    return "\n".join(parts)


# ============================================================
# CLI
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="HTML报告生成器")
    parser.add_argument("--analysis", required=True, help="analysis.json 路径")
    parser.add_argument("--raw", required=True, help="raw_data.json 路径")
    parser.add_argument("--output", required=True, help="report.html 输出路径")
    parser.add_argument("--extra", help="extra.json 路径（游戏特有信息，可选）")
    args = parser.parse_args()

    with open(args.analysis, "r", encoding="utf-8") as f:
        analysis = json.load(f)
    with open(args.raw, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    extra = {}
    if args.extra and os.path.exists(args.extra):
        with open(args.extra, "r", encoding="utf-8") as f:
            extra = json.load(f)

    html_content = generate_report(analysis, raw_data, extra)

    with open(args.output, "w", encoding="utf-8") as f:
        f.write(html_content)

    print(f"HTML报告已生成: {args.output}")
    print(f"文件大小: {len(html_content) / 1024:.1f} KB")


if __name__ == "__main__":
    main()
