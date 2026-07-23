---
name: competitor-content
description: Steam独立游戏竞品社区内容分析与文案生成（B站+小红书双平台）。用户提供自身游戏名和竞品列表后，自动抓取双平台社区内容，分析竞品热点与内容类型分布，生成3条文案，产出单一HTML报告。Trigger: 竞品分析, 社区内容抓取, 文案生成, indie game competitor analysis.
---

# Steam独立游戏竞品社区内容分析与文案生成

输入一款Steam独立游戏名 + 用户指定的竞品列表 → B站和小红书双平台抓取社区内容 → 仅基于竞品数据分析热点与内容类型 → 结合自身产品特点生成3条文案 → 产出一份HTML报告。

## 文件结构

```
Competitor-Skill/
├── SKILL.md        # 本文件（技能定义）
├── crawler.py      # 第3步：双平台抓取（B站API + 小红书Playwright）
├── analyzer.py     # 第4步：内容分析（评分/分类/词频/Top排序）
├── reportgen.py    # 第5步：HTML报告生成
└── .env            # 小红书Cookie配置（XHS_COOKIE=...）
```

三个 `.py` 脚本为固化的通用工具，agent 直接调用即可，无需手写代码。游戏特有信息（产品分析、文案、insights）通过 `extra.json` 动态传入。

## 输入

1. **Steam独立游戏名**（必需）— 例如"吸血鬼幸存者"。未提供时用 question 工具询问。
2. **竞品列表**（必需）— 至少2款，由用户指定，不自动补充。见第2步。
3. **小红书Cookie**（首次使用）— 配置到 `.env`：`XHS_COOKIE=完整Cookie字符串`。获取方式：浏览器登录 `www.xiaohongshu.com` → F12 → Network → 复制任意请求的 Cookie 头。有效期约1-2周。未配置时自动跳过小红书，仅抓B站。

## 执行流程

---

### 第 1 步：环境检查与准备

1. **检查环境**：运行 `python crawler.py --check`，自动检测并安装缺失依赖（jieba、Playwright + Chromium），确认小红书 Cookie 状态。
   - jieba/Playwright 缺失：脚本自动 `pip install` 安装，无需用户手动操作。
   - Cookie 未配置：用 question 询问用户是配置还是跳过小红书。若配置，提示用户将 Cookie 写入 `.env`（`XHS_COOKIE=...`）后重新运行 `--check`。
2. 创建输出目录：`output/{游戏名}_{YYYYMMDD}/`

**output 目录最终包含 2 个文件**（中间文件已清理）：

| 文件 | 产出者 | 内容 |
|------|--------|------|
| `raw_data.json` | crawler.py | 原始爬取数据：每款游戏的 B站/小红书帖子原文（标题、正文、标签、互动数、链接），可复查/重新分析 |
| `report.html` | reportgen.py | 最终 HTML 报告：7 区块单文件，内嵌 CSS，浏览器直接打开 |

> 运行过程中会临时生成 `analysis.json`（分析结果）和 `extra.json`（游戏文案），报告生成后自动删除，内容已体现在 HTML 中。

---

### 第 2 步：获取竞品（用户必须提供）

**不自动搜索或补充竞品。**

1. 用 question 工具询问：「请提供竞品游戏名称（至少2款，建议3款），需与你的游戏同品类、体量相近的Steam独立游戏。」
2. 用户至少提供2款。若只给1款，追问是否补充。
3. 可选：用 webfetch 搜索 `{游戏名} similar games Steam` 获取候选参考，附在问题描述中，但**不自动选择**。
4. 记录备用搜索关键词（如竞品中文译名），供 crawler.py 使用。

---

### 第 3 步：抓取双平台社区内容

```bash
python crawler.py \
  --games "自身游戏名:self,竞品1:comp:备用词1,竞品2:comp,竞品3:comp:备用词3" \
  --output "output/{游戏名}_{日期}/raw_data.json" \
  --platform both --days 30 --max 30 \
  --exclude "Windows,Win11,卸载,Xbox"
```

| 参数 | 说明 |
|------|------|
| `--games` | 逗号分隔，格式 `游戏名:角色[:备用关键词]`。`self`=自身，`comp`=竞品 |
| `--output` | 输出 `raw_data.json` |
| `--platform` | `both`(默认) / `bili` / `xhs` |
| `--days` | 时间过滤天数（默认30） |
| `--max` | 每游戏每平台最大条数（默认30） |
| `--exclude` | 排除词，逗号分隔。标题/标签命中任一排除词的内容直接丢弃。用于过滤歧义词（如搜"Task Bar Hero"时排除"Windows"） |

crawler.py 内置过滤链（按顺序执行）：
1. **相关性过滤**：检查 title+tag 是否命中游戏名变体（短语命中 / 多词名全词命中），不相关的丢弃。过滤后不足5条时逐级降级（短语命中→保留全部）。`raw_data.json` 中每款游戏含 `alt_keyword` 字段，供 analyzer.py 加入 jieba 词典避免游戏名被拆分。
2. **官方账号过滤**：排除作者名匹配游戏名或含"官方/official/频道/工作室/studio"等关键词的发文。
3. **备用关键词补搜**：结果不足5条时用 `alt_keyword` 补搜。
4. **时间过滤**：按 `--days` 过滤，不足5条保留全部。

---

### 第 4 步：内容分析

```bash
python analyzer.py --input "output/{游戏名}_{日期}/raw_data.json" --output "output/{游戏名}_{日期}/analysis.json"
```

analyzer.py 内置（全部自动，无需手动干预）：
- **竞品/自身分离**：仅竞品数据用于词云/类型分布/Top10，自身仅Top5参照。
- **互动评分**：B站 `play+like*5+danmaku*3+favorites*2`；小红书 `likes*5+comments*3+collected*2+shared*2`。
- **类型分类**：7类关键词匹配（更新公告/攻略教程/实况录像/测评推荐/速通挑战/玩家整活/爆料前瞻）+ 其他。
- **词频分析**：优先提取结构化标签（B站tag逗号拆分 / 小红书 `#hashtag`，双倍权重），jieba 仅对标题补充分词（游戏名已加入自定义词典避免被拆分）。分平台Top20高频词，排除游戏名及其备用关键词，标注跨平台共同热词。
- **Top排序**：竞品Top10（B站+小红书各一张）+ 自身Top5参照。

#### 4.1 产品特点分析（agent 手动）

agent 基于 webfetch 搜索 Steam 商店页，即时总结：游戏类型、核心卖点、文案调性、Steam标签。写入 `extra.json` 的 `product_analysis` 字段。

---

### 第 5 步：生成文案并产出HTML报告

#### 5.1 研读竞品原文（agent 必做）

生成文案前，agent **必须先读取 `raw_data.json`**，研读竞品高互动内容的实际文案写法：

1. 读取 `raw_data.json`，遍历每款竞品的 `bilibili` 和 `xiaohongshu` 帖子。
2. 按互动评分排序（B站：`play+like*5`；小红书：`likes*5+comments*3`），取每平台 Top5。
3. 逐条研读高互动帖子的：
   - **标题**：分析标题句式套路（如"【UP主名】+情绪词+游戏名+描述"、"疑问句/感叹句"、"数字+挑战型"）
   - **正文/简介**：分析开头 hook（如何吸引注意力）、中间内容结构、结尾互动引导（如"求关注""你觉得呢"）
   - **标签**：分析标签组合规律（如"游戏名+平台+玩法类型+情绪词"）
4. 归纳出 3 种高互动文案模板，作为自身游戏文案的创作骨架。

#### 5.2 生成 extra.json

agent 基于竞品文案模板 + 产品特点 + 分析结果，生成3条不同角度文案，连同产品分析、insights、竞品描述写入 `extra.json`：

```json
{
  "self_game_name": "游戏名",
  "game_descriptions": { "游戏名": "一句话描述" },
  "product_analysis": { "name": "...", "desc": "...", "features": [...], "tones": [...], "tags": [...] },
  "insights": ["竞品高互动规律1", "规律2"],
  "copies": [
    {
      "angle": "测评安利型",
      "source_platform": "B站",
      "title": "...",
      "body": "...",
      "tags": [...],
      "image_suggestion": "...",
      "reference": "模仿来源：UP主xxx的《xxx》标题句式 + 正文结构（评分xxx）",
      "reference_snippet": "竞品原文标题/正文片段，供对比参考"
    }
  ],
  "competitor_note": "竞品选择依据"
}
```

文案要求：
- **模仿竞品高互动内容的标题句式和正文结构**，替换为自身游戏内容，不是凭空创作。
- 每条文案的 `reference` 字段注明模仿的竞品帖子来源及互动评分。
- `reference_snippet` 字段附上竞品原文片段（标题或正文前50字），供对比。
- 文案角度参考：更新驱动型 / 攻略Build型 / 测评安利型 / 速通挑战型 / 情感互动型 / 玩家整活型。
- 每条含：标题(20字内)、正文(150字内)、话题标签(3-5个)、配图建议。

#### 5.2 生成HTML报告

```bash
python reportgen.py \
  --analysis "output/{游戏名}_{日期}/analysis.json" \
  --raw "output/{游戏名}_{日期}/raw_data.json" \
  --output "output/{游戏名}_{日期}/report.html" \
  --extra "output/{游戏名}_{日期}/extra.json" \
  --days 30
```

`--days` 为可选参数，默认 30 天，与 `crawler.py` 的时间窗口保持一致。

reportgen.py：内嵌CSS单一HTML文件，7区块（报告头→竞品识别→词云→类型分布→Top10→insights→产品分析→文案），丰富配色，tag自适应不截断。`extra.json` 缺省时对应区块自动跳过。若某平台 Top10/Top5 表格中包含 `--days` 天外的历史内容（ crawler.py 时间过滤触发降级保留全部数据），表格上方会自动显示橙色数据提示。

#### 5.3 清理中间文件

HTML 报告生成后，删除 `analysis.json` 和 `extra.json`（内容已体现在报告中，从 HTML 复制更方便），仅保留 `raw_data.json`（原始数据，可复查/重新分析）和 `report.html`（最终交付物）。

```bash
rm "output/{游戏名}_{日期}/analysis.json" "output/{游戏名}_{日期}/extra.json"
```

最终 output 目录仅含：
- `raw_data.json` — 原始爬取数据
- `report.html` — 最终 HTML 报告

#### 5.4 交付摘要

向用户输出：抓取游戏数/双平台内容数、Top3热点话题、3条文案标题，提示查看 `report.html`。

---

## 降级与异常处理

- **B站API失败**：crawler.py 自动重试备用关键词，仍失败则跳过并记录。
- **小红书Cookie过期/未配置**：跳过小红书，仅用B站数据，报告中说明。
- **Playwright未安装**：跳过小红书，提示安装命令。
- **数据不足**：相关性过滤后不足5条时逐级降级；时间过滤后不足5条保留全部。
- **jieba不可用**：降级为正则提取，不阻塞流程。

## 注意事项

- 抓取公开搜索结果，用于运营参考。文案需人工审核后发布。
- 面向Steam独立游戏，不套用手游"卡池/福利/角色"框架。
- 小红书Cookie有效期约1-2周，需定期更新。
- 小红书搜索仅返回标题（无正文/标签），发布时间为月-日格式。
- 竞品由用户提供，不自动补充。名称有歧义时建议提供备用关键词。
- 英文名歧义较大时（如"Pixel Chess"易匹配 Google Pixel 手机），优先使用中文译名作为备用关键词，并通过 `--exclude` 排除明显不相关词。
