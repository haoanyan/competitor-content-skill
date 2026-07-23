# Competitor Content Skill

![version](https://img.shields.io/badge/version-1.0.0-blue)

Steam 独立游戏竞品社区内容分析与文案生成技能。输入一款游戏名 + 竞品列表，自动抓取 B站和小红书社区内容，分析竞品热点，模仿高互动帖子的写法生成 3 条社媒文案，产出一页 HTML 报告。

---

## Agent 自动安装指令

> 以下内容面向 opencode agent。如果你是 agent，用户给了你这个仓库链接并希望安装此 skill，请按以下步骤执行：

1. **克隆仓库**到 opencode skills 目录：
   - 全局安装：`git clone https://github.com/<your-username>/competitor-content-skill.git ~/.config/opencode/skills/competitor-content`
   - 项目级安装：`git clone https://github.com/<your-username>/competitor-content-skill.git .opencode/skills/competitor-content`
   - 若不确定 skills 目录，用 question 工具询问用户选择哪种方式。

2. **安装依赖**：在克隆后的目录中运行 `python crawler.py --check`，脚本会自动检测并安装 jieba、Playwright + Chromium。

3. **配置 Cookie**：
   - 复制 `.env.example` 为 `.env`（`cp .env.example .env`）。
   - 告诉用户：浏览器登录 `www.xiaohongshu.com` → F12 → Network → 复制任意请求的 Cookie 头 → 填入 `.env` 中的 `XHS_COOKIE=`。
   - Cookie 未配置时也可使用，但会跳过小红书仅抓 B站。

4. **安装完成**：告诉用户「skill 已安装，现在可以说：帮我分析"游戏名"这款游戏，竞品是XX、XX，即可触发。」

---

## 功能

- **双平台爬取**：B站（免签名 API）+ 小红书（Playwright + Cookie）
- **相关性过滤**：标题/标签命中游戏名才保留，排除词过滤歧义内容
- **内容分析**：互动评分、类型分类、词频分析（结构化标签优先 + jieba 补充）、Top10 排序
- **文案生成**：读取竞品高互动原文，归纳标题句式和正文结构，模仿产出自身游戏文案
- **HTML 报告**：单一文件，7 区块，内嵌 CSS，可直接打开

## 文件结构

```
Competitor-Skill/
├── SKILL.md          # 技能定义（opencode agent 读取）
├── crawler.py        # 双平台爬虫
├── analyzer.py       # 内容分析器
├── reportgen.py      # HTML 报告生成器
├── .env.example      # 环境变量模板
└── .env              # 你的实际配置（不入 Git）
```

## 安装

### 1. 安装 opencode

两种方式任选其一：

- **VS Code 插件**：在 VS Code 扩展市场搜索 "opencode" 安装插件，直接在编辑器内使用。
- **CLI 命令行**：参考 [opencode.ai](https://opencode.ai) 安装 opencode CLI。

### 2. 安装本 Skill

将本仓库克隆到 opencode 的 skills 目录：

```bash
# 方式一：克隆到全局 skills 目录
git clone https://github.com/<your-username>/competitor-content-skill.git ~/.config/opencode/skills/competitor-content

# 方式二：克隆到项目级 skills 目录
git clone https://github.com/<your-username>/competitor-content-skill.git .opencode/skills/competitor-content
```

### 3. 配置小红书 Cookie

```bash
# 复制模板
cp .env.example .env
```

编辑 `.env`，填入你的小红书 Cookie：

```
XHS_COOKIE=你的完整Cookie字符串
```

**获取方式**：浏览器登录 `www.xiaohongshu.com` → F12 → Network → 复制任意请求的 Cookie 头。有效期约 1-2 周。

> 未配置 Cookie 时自动跳过小红书，仅抓取 B站。

## 使用

在 opencode 中直接对话即可触发，例如：

```
帮我分析"Bits Bops"这款游戏，竞品是节奏天国、节奏医生、冰与火之舞
```

opencode agent 会自动执行 5 步流程：

| 步骤 | 动作 | 产出 |
|------|------|------|
| 1. 环境检查 | `python crawler.py --check` | 自动安装依赖 + 确认 Cookie |
| 2. 获取竞品 | 向用户确认竞品列表 | 游戏名 + 备用关键词 |
| 3. 抓取内容 | `python crawler.py --games ... --output ...` | `raw_data.json` |
| 4. 内容分析 | `python analyzer.py --input ... --output ...` | `analysis.json` |
| 5. 文案+报告 | agent 研读竞品原文 → 生成文案 → `python reportgen.py` | `extra.json` + `report.html` |

也可以手动运行各脚本，参数说明见 `SKILL.md`。

## 产出文件

每次运行后，`output/{游戏名}_{日期}/` 目录下最终保留 2 个文件：

| 文件 | 内容 |
|------|------|
| `raw_data.json` | 原始爬取数据：B站/小红书帖子原文（标题、正文、标签、互动数、链接），可复查/重新分析 |
| `report.html` | 最终 HTML 报告，浏览器直接打开，文案可直接复制 |

> 运行过程中临时生成 `analysis.json` 和 `extra.json`，报告生成后自动清理。

## 注意事项

- B站搜索按发布时间排序（`order=pubdate`），确保抓到近期内容。
- 小红书详情页抓取最多 15 条，每条间隔 2 秒，避免风控。
- 小红书 Cookie 有效期约 1-2 周，过期后需重新获取。
- 抓取的是公开搜索结果，用于运营参考。文案需人工审核后发布。
- 面向 Steam 独立游戏，不套用手游"卡池/福利/角色"框架。

## 依赖

- Python 3.8+
- [jieba](https://github.com/fxsjy/jieba) — 中文分词（首次运行自动安装）
- [Playwright](https://playwright.dev/) — 浏览器自动化（首次运行自动安装）

> 首次运行 `python crawler.py --check` 时会自动检测并安装缺失的 Python 依赖，无需手动操作。
