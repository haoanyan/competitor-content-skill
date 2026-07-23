"""
crawler.py — 双平台社区内容爬虫（B站 + 小红书）

用法:
  python crawler.py --games "幻想放置远征队:self,Task Bar Hero:comp,桌面副本物语:comp" --output "output/xxx/raw_data.json"
  python crawler.py --check          # 检查环境（Cookie/Playwright状态）

参数:
  --games   逗号分隔的游戏列表，格式: 游戏名:角色(self=自身, comp=竞品)
            可选附加备用关键词: 游戏名:角色:备用关键词
  --output  输出JSON路径
  --platform  bili | xhs | both (默认both)
  --days    时间过滤天数 (默认30)
  --max     每游戏每平台最大抓取条数 (默认30)
  --exclude 排除词，逗号分隔。标题/标签命中任一排除词的内容直接丢弃
            例: --exclude "Windows,Win11,卸载,Xbox"
  --check   仅检查环境配置，不抓取

环境变量:
  XHS_COOKIE  小红书登录Cookie，配置在 .env 文件中
  .env 查找顺序: 1) 脚本同目录(Competitor-Skill/.env) 2) 上级目录(.env)
  获取方式: 浏览器登录 www.xiaohongshu.com → F12开发者工具 → Network
            → 点任意请求 → 复制 Request Headers 中的 Cookie 值
  Cookie有效期约1-2周，过期后需重新获取。

输出:
  raw_data.json — 统一格式的双平台数据
"""
import argparse
import json
import os
import re
import sys
import io
import time
import urllib.request
import urllib.parse
from datetime import datetime, timedelta
from urllib.parse import quote

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')


# 加载 .env 文件（标准库实现，无需 python-dotenv）
def _load_env():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    for env_path in [os.path.join(script_dir, ".env"), os.path.join(script_dir, "..", ".env")]:
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        os.environ.setdefault(key.strip(), val.strip())

_load_env()


# ============================================================
# 工具函数
# ============================================================
def to_int(val):
    """'1.2万' -> 12000, '5' -> 5"""
    if isinstance(val, int):
        return val
    if not val:
        return 0
    val = str(val).strip()
    try:
        if "\u4e07" in val:
            return int(float(val.replace("\u4e07", "")) * 10000)
        if "\u5343" in val:
            return int(float(val.replace("\u5343", "")) * 1000)
        return int(val)
    except ValueError:
        return 0


def filter_official(posts, game_name):
    """
    过滤掉官方/自身社媒账号发布的内容。
    匹配规则：作者名包含游戏名、或作者名包含"官方""official""频道""工作室""studio"等关键词。
    返回 (filtered_posts, removed_count)。
    """
    official_keywords = ["官方", "official", "频道", "工作室", "studio", "publisher", "developer", "发行", "运营"]
    # 游戏名的常见变体
    name_variants = [game_name.lower()]
    if " " in game_name:
        name_variants.append(game_name.lower().replace(" ", ""))
    # 去掉中文名的前缀/后缀常见词
    for suffix in ["游戏", "手游", "ol", "online"]:
        if game_name.lower().endswith(suffix):
            name_variants.append(game_name[: -len(suffix)].lower())

    filtered = []
    removed = 0
    for p in posts:
        author = (p.get("author", "")).lower()
        is_official = False
        # 作者名匹配游戏名
        for nv in name_variants:
            if nv and len(nv) >= 3 and nv in author:
                is_official = True
                break
        # 作者名匹配官方关键词
        if not is_official:
            for kw in official_keywords:
                if kw in author:
                    is_official = True
                    break
        if is_official:
            removed += 1
        else:
            filtered.append(p)
    return filtered, removed


def filter_by_time(posts, days, has_time_key="publish_time"):
    """按时间过滤，若过滤后不足5条则返回全部"""
    threshold = datetime.now() - timedelta(days=days)
    recent = []
    for p in posts:
        pt = p.get(has_time_key, "")
        if not pt:
            continue
        try:
            dt = datetime.strptime(pt, "%Y-%m-%d")
            if dt >= threshold:
                recent.append(p)
        except Exception:
            continue
    return recent if len(recent) >= 5 else posts


def get_name_variants(game_name, alt_keyword=""):
    """
    生成游戏名的匹配变体。
    返回 (phrase_variants, word_variants):
      - phrase_variants: 完整短语（如 "pixel chess", "像素棋"），命中即相关
      - word_variants: 单词集合（如 {"pixel","chess"}），全部命中才相关
    """
    phrase_variants = set()
    word_groups = []  # 每组是一个名字的所有单词，需全部命中

    def add_name(n):
        n = n.strip().lower()
        if not n or len(n) < 2:
            return
        phrase_variants.add(n)
        phrase_variants.add(n.replace(" ", ""))
        words = [w for w in n.split() if len(w) >= 2]
        if len(words) > 1:
            word_groups.append(set(words))

    add_name(game_name)
    if alt_keyword:
        for part in alt_keyword.split(","):
            part = part.strip()
            if part:
                add_name(part)

    return phrase_variants, word_groups


def _is_relevant(text, phrase_variants, word_groups):
    """判断文本是否与游戏相关：短语命中 → 相关；任一单词组全命中 → 相关"""
    for pv in phrase_variants:
        if pv in text:
            return True
    for wg in word_groups:
        if all(w in text for w in wg):
            return True
    return False


def filter_by_relevance(posts, game_name, alt_keyword="", exclude_words=None):
    """
    标题相关性过滤：检查 title + tag 中是否命中游戏名。
    - 短语命中（如 "pixel chess" 出现）→ 相关
    - 多词名所有单词均出现 → 相关
    - 单词名出现 → 相关
    排除词命中的直接丢弃。
    返回 (filtered_posts, removed_count)。
    """
    phrase_variants, word_groups = get_name_variants(game_name, alt_keyword)
    exclude_words = [w.lower().strip() for w in (exclude_words or []) if w.strip()]

    filtered = []
    removed = 0
    for p in posts:
        title = (p.get("title", "")).lower()
        tag = (p.get("tag", "")).lower()
        text = title + " " + tag

        # 排除词检查：命中任一就丢弃
        if any(ew in text for ew in exclude_words):
            removed += 1
            continue

        # 相关性检查
        if _is_relevant(text, phrase_variants, word_groups):
            filtered.append(p)
        else:
            removed += 1

    # 若严格过滤后不足5条，降级：短语命中即可（不要求全词）
    if len(filtered) < 5 and word_groups:
        relaxed = []
        for p in posts:
            text = (p.get("title", "") + " " + p.get("tag", "")).lower()
            if any(ew in text for ew in exclude_words):
                continue
            if any(pv in text for pv in phrase_variants):
                relaxed.append(p)
        if len(relaxed) > len(filtered):
            filtered = relaxed
            removed = len(posts) - len(filtered)

    return filtered, removed


# ============================================================
# B站爬虫
# ============================================================
def crawl_bilibili(keyword, max_posts=30):
    url = f"https://api.bilibili.com/x/web-interface/search/all/v2?keyword={quote(keyword)}&page=1&order=pubdate"
    req = urllib.request.Request(url, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36',
        'Referer': 'https://www.bilibili.com',
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        data = json.loads(resp.read().decode('utf-8'))
    except Exception as e:
        print(f"  [B站] 请求失败 ({keyword}): {e}")
        return []

    results = []
    for result_type in data.get('data', {}).get('result', []):
        if result_type.get('result_type') != 'video':
            continue
        for item in result_type.get('data', []):
            title = re.sub(r'<[^>]+>', '', item.get('title', ''))
            pubdate = item.get('pubdate', 0)
            results.append({
                'platform': 'bilibili',
                'title': title,
                'description': item.get('description', ''),
                'tag': item.get('tag', ''),
                'author': item.get('author', ''),
                'pubdate': pubdate,
                'publish_time': datetime.fromtimestamp(pubdate).strftime('%Y-%m-%d') if pubdate else '',
                'play': int(item.get('play') or 0),
                'danmaku': int(item.get('video_review') or 0),
                'favorites': int(item.get('favorites') or 0),
                'like': int(item.get('like') or 0),
                'pic': 'https:' + item.get('pic', '') if item.get('pic') else '',
                'bvid': item.get('bvid', ''),
                'link': f"https://www.bilibili.com/video/{item.get('bvid', '')}",
            })
            if len(results) >= max_posts:
                break
    return results


# ============================================================
# 小红书爬虫 (Playwright)
# ============================================================
def crawl_xiaohongshu(keyword, max_posts=30):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"  [小红书] Playwright未安装，跳过。安装: pip install playwright && python -m playwright install chromium")
        return []

    cookie_str = os.environ.get("XHS_COOKIE", "")
    if not cookie_str:
        print(f"  [小红书] 未配置XHS_COOKIE，跳过。请在 .env 中配置（获取方式见文件头注释）")
        return []

    cookies = []
    for pair in cookie_str.split("; "):
        if "=" in pair:
            k, v = pair.split("=", 1)
            cookies.append({"name": k, "value": v, "domain": ".xiaohongshu.com", "path": "/"})

    # ===== 阶段1: 搜索获取笔记列表 =====
    api_responses = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        context.add_cookies(cookies)

        def handle_response(response):
            if "search" in response.url and "notes" in response.url and response.status == 200:
                try:
                    api_responses.append(response.json())
                except Exception:
                    pass

        page = context.new_page()
        page.on("response", handle_response)
        search_url = f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&source=web_explore_feed"
        try:
            page.goto(search_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(5000)
        except Exception:
            pass
        scroll_times = max(1, max_posts // 20)
        for _ in range(scroll_times):
            page.evaluate("window.scrollBy(0, 1000)")
            page.wait_for_timeout(2000)
        browser.close()

    if not api_responses:
        print(f"  [小红书] 未拦截到API响应 ({keyword})，Cookie可能已过期")
        return []

    # 去重合并
    all_items = []
    seen_ids = set()
    for resp in api_responses:
        for item in resp.get("data", {}).get("items", []):
            item_id = item.get("id", "")
            if item_id and item_id not in seen_ids:
                all_items.append(item)
                seen_ids.add(item_id)

    # ===== 阶段2: 逐条请求详情页获取正文和标签 =====
    # 控制详情页请求数量，避免风控（最多15条）
    detail_limit = min(max_posts, 15)
    items_for_detail = all_items[:detail_limit]
    print(f"  [小红书] 搜索到{len(all_items)}条，抓取前{len(items_for_detail)}条详情页")

    detail_map = {}  # id -> {desc, tags}
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1920, "height": 1080},
        )
        context.add_cookies(cookies)

        for item in items_for_detail:
            note_id = item.get("id", "")
            xsec_token = item.get("xsec_token", "")
            if not note_id:
                continue

            detail_data = {}
            page = context.new_page()

            def handle_detail(response, did=note_id):
                if "feed" in response.url and response.status == 200:
                    try:
                        data = response.json()
                        items = data.get("data", {}).get("items", [])
                        if items and not detail_data:
                            nc = items[0].get("note_card", {})
                            detail_data["desc"] = nc.get("desc", "")
                            tag_list = nc.get("tag_list", [])
                            detail_data["tags"] = [t.get("name", "") for t in tag_list if t.get("name")]
                    except Exception:
                        pass

            page.on("response", handle_detail)
            detail_url = f"https://www.xiaohongshu.com/explore/{note_id}?xsec_token={xsec_token}&xsec_source=pc_search"
            try:
                page.goto(detail_url, wait_until="domcontentloaded", timeout=15000)
                page.wait_for_timeout(3000)
            except Exception:
                pass
            page.close()

            if detail_data:
                detail_map[note_id] = detail_data
            time.sleep(2)  # 请求间隔，避免风控

        browser.close()

    print(f"  [小红书] 详情页抓取完成: {len(detail_map)}/{len(items_for_detail)} 条成功")

    # ===== 阶段3: 组装结果 =====
    current_year = datetime.now().year
    results = []

    for item in all_items[:max_posts]:
        try:
            note = item.get("note_card", item)
            post_id = item.get("id", note.get("note_id", ""))
            user = note.get("user", {})
            interact = note.get("interact_info", {})

            # 时间解析: corner_tag_info -> "MM-DD"
            pub_time = None
            for tag_info in note.get("corner_tag_info", []):
                if tag_info.get("type") == "publish_time":
                    time_text = tag_info.get("text", "")
                    if time_text:
                        try:
                            month, day = time_text.split("-")
                            pub_date = datetime(current_year, int(month), int(day))
                            if pub_date > datetime.now():
                                pub_date = datetime(current_year - 1, int(month), int(day))
                            pub_time = pub_date.strftime('%Y-%m-%d')
                        except Exception:
                            pass
                    break

            # 图片
            images = []
            for img in note.get("image_list", note.get("imageList", [])):
                for info in img.get("info_list", []):
                    if info.get("image_scene") == "WB_DFT" and info.get("url"):
                        images.append(info["url"])
                        break

            title_str = note.get("display_title", note.get("title", ""))
            # 从详情页获取正文和标签
            detail = detail_map.get(post_id, {})
            desc_str = detail.get("desc", "")
            tag_str = ",".join(detail.get("tags", []))

            results.append({
                'platform': 'xiaohongshu',
                'title': title_str,
                'description': desc_str,
                'author': user.get("nickname", user.get("nick_name", "")),
                'publish_time': pub_time,
                'tag': tag_str,
                'likes': to_int(interact.get("liked_count", "0")),
                'comments': to_int(interact.get("comment_count", "0")),
                'collected': to_int(interact.get("collected_count", "0")),
                'shares': to_int(interact.get("shared_count", "0")),
                'images': images,
                'note_type': note.get("type", ""),
                'link': f"https://www.xiaohongshu.com/explore/{post_id}",
            })
        except Exception:
            continue

    return results


# ============================================================
# 主流程
# ============================================================
def parse_games(games_str):
    """解析 --games 参数: '游戏A:self,游戏B:comp:备用词'"""
    games = []
    for entry in games_str.split(","):
        parts = entry.strip().split(":")
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        role = parts[1].strip()
        alt_kw = parts[2].strip() if len(parts) > 2 else ""
        games.append({"name": name, "is_self": role == "self", "alt_keyword": alt_kw})
    return games


def auto_install(package, extra_cmd=None):
    """自动安装 Python 包"""
    import subprocess
    print(f"  [自动安装] pip install {package} ...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", package],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"  [自动安装] {package} 安装成功")
        if extra_cmd:
            print(f"  [自动安装] {extra_cmd} ...")
            subprocess.check_call(extra_cmd.split(),
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            print(f"  [自动安装] {extra_cmd} 完成")
        return True
    except Exception as e:
        print(f"  [自动安装] {package} 安装失败: {e}")
        return False


def check_env():
    """检查环境配置，缺失依赖自动安装，输出状态报告"""
    print("=" * 50)
    print("环境检查")
    print("=" * 50)

    all_ok = True

    # B站（无需特殊配置）
    print(f"  [B站]      可用（免签名API，无需配置）")

    # jieba
    try:
        import jieba
        print(f"  [jieba]    已安装（{jieba.__version__}）")
    except ImportError:
        print(f"  [jieba]    未安装，正在自动安装...")
        if auto_install("jieba"):
            print(f"  [jieba]    安装成功")
        else:
            print(f"  [jieba]    安装失败，将降级为正则分词")
            all_ok = False

    # 小红书Cookie
    cookie = os.environ.get("XHS_COOKIE", "")
    if cookie:
        print(f"  [小红书]    Cookie已配置（{len(cookie)}字符）")
    else:
        print(f"  [小红书]    Cookie未配置")
        print(f"             获取方式: 浏览器登录 www.xiaohongshu.com")
        print(f"             → F12 → Network → 复制Cookie头")
        print(f"             → 写入 .env: XHS_COOKIE=你的Cookie")

    # Playwright
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        print(f"  [Playwright] 已安装，Chromium可用")
    except ImportError:
        print(f"  [Playwright] 未安装，正在自动安装...")
        if auto_install("playwright", "python -m playwright install chromium"):
            print(f"  [Playwright] 安装成功，Chromium已就绪")
        else:
            print(f"  [Playwright] 安装失败，小红书爬取将不可用")
            all_ok = False
    except Exception as e:
        print(f"  [Playwright] 已安装但Chromium缺失，正在安装...")
        if auto_install("playwright", "python -m playwright install chromium"):
            print(f"  [Playwright] Chromium安装成功")
        else:
            print(f"  [Playwright] Chromium安装失败: {e}")
            all_ok = False

    # .env 路径
    script_dir = os.path.dirname(os.path.abspath(__file__))
    env_local = os.path.join(script_dir, ".env")
    env_parent = os.path.join(script_dir, "..", ".env")
    print(f"\n  .env 查找路径:")
    print(f"    1) {env_local} {'(存在)' if os.path.exists(env_local) else '(不存在)'}")
    print(f"    2) {env_parent} {'(存在)' if os.path.exists(env_parent) else '(不存在)'}")

    print("\n" + "=" * 50)


def main():
    parser = argparse.ArgumentParser(description="双平台社区内容爬虫")
    parser.add_argument("--games", help="游戏列表，格式: 游戏名:角色[:备用关键词], 逗号分隔")
    parser.add_argument("--output", help="输出JSON路径")
    parser.add_argument("--platform", default="both", choices=["bili", "xhs", "both"])
    parser.add_argument("--days", type=int, default=30, help="时间过滤天数")
    parser.add_argument("--max", type=int, default=30, help="每游戏每平台最大条数")
    parser.add_argument("--exclude", default="", help="排除词，逗号分隔。标题/标签命中任一排除词的内容直接丢弃")
    parser.add_argument("--check", action="store_true", help="仅检查环境配置，不抓取")
    args = parser.parse_args()

    if args.check:
        check_env()
        return

    if not args.games or not args.output:
        parser.error("--games 和 --output 是必需的（或使用 --check 仅检查环境）")

    games = parse_games(args.games)
    exclude_words = [w.strip() for w in args.exclude.split(",") if w.strip()] if args.exclude else []
    if exclude_words:
        print(f"排除词: {exclude_words}")
    output_dir = os.path.dirname(args.output)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    all_data = {}

    for game in games:
        name = game["name"]
        is_self = game["is_self"]
        alt_kw = game.get("alt_keyword", "")
        label = "自身" if is_self else "竞品"
        print(f"\n>>> {name} ({label})")

        bili_posts = []
        xhs_posts = []

        # B站
        if args.platform in ("bili", "both"):
            print(f"  [B站] 搜索: {name}")
            bili_posts = crawl_bilibili(name, args.max)
            if len(bili_posts) < 5 and alt_kw:
                print(f"  [B站] 结果不足({len(bili_posts)}条)，备用关键词: {alt_kw}")
                bili_posts.extend(crawl_bilibili(alt_kw, args.max))
            # 相关性过滤（标题/标签必须命中游戏名变体，排除词命中则丢弃）
            bili_posts, removed = filter_by_relevance(bili_posts, name, alt_kw, exclude_words)
            if removed:
                print(f"  [B站] 过滤不相关内容 {removed} 条")
            # 时间过滤
            bili_posts = filter_by_time(bili_posts, args.days)
            # 官方账号过滤
            bili_posts, removed = filter_official(bili_posts, name)
            if removed:
                print(f"  [B站] 过滤官方账号发文 {removed} 条")
            print(f"  [B站] 最终 {len(bili_posts)} 条")

        # 小红书
        if args.platform in ("xhs", "both"):
            print(f"  [小红书] 搜索: {name}")
            xhs_posts = crawl_xiaohongshu(name, args.max)
            if len(xhs_posts) < 5 and alt_kw:
                print(f"  [小红书] 结果不足({len(xhs_posts)}条)，备用关键词: {alt_kw}")
                xhs_posts.extend(crawl_xiaohongshu(alt_kw, args.max))
            # 相关性过滤
            xhs_posts, removed = filter_by_relevance(xhs_posts, name, alt_kw, exclude_words)
            if removed:
                print(f"  [小红书] 过滤不相关内容 {removed} 条")
            # 时间过滤
            xhs_posts = filter_by_time(xhs_posts, args.days)
            # 官方账号过滤
            xhs_posts, removed = filter_official(xhs_posts, name)
            if removed:
                print(f"  [小红书] 过滤官方账号发文 {removed} 条")
            print(f"  [小红书] 最终 {len(xhs_posts)} 条")

        all_data[name] = {
            "is_self": is_self,
            "alt_keyword": alt_kw,
            "bilibili": bili_posts,
            "xiaohongshu": xhs_posts,
        }
        time.sleep(2)

    # 保存
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(all_data, f, ensure_ascii=False, indent=2)

    # 汇总
    print("\n" + "=" * 60)
    print("抓取完成汇总:")
    total_b = sum(len(d["bilibili"]) for d in all_data.values())
    total_x = sum(len(d["xiaohongshu"]) for d in all_data.values())
    for gn, gd in all_data.items():
        lb = "自身" if gd["is_self"] else "竞品"
        print(f"  {gn} ({lb}): B站 {len(gd['bilibili'])} + 小红书 {len(gd['xiaohongshu'])}")
    print(f"\n  总计: B站 {total_b}条 + 小红书 {total_x}条")
    print(f"  数据已保存: {args.output}")


if __name__ == "__main__":
    main()
