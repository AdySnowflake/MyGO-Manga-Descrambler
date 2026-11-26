import json
import re
import time
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import BrowserContext, Page, Response, sync_playwright

DEFAULT_PROFILE_DIR = ".edge-profile"
DEFAULT_COOKIES_FILE = "cookies.json"
DEFAULT_SERIES_URL = "https://comic-growl.com/series/762be67a2ce92"

MASTER_IMG_PATTERN = re.compile(r"master-\d+-(\d+)\.(?:jpg|jpeg|png|webp)", re.IGNORECASE)
IMAGE_URL_KEYS = ("imageUrl", "image_url", "imgUrl", "img_url", "url", "src")


class MangaFetchError(RuntimeError):
    """Raised when contentsInfo or manga page images cannot be fetched."""


class EpisodeLockedError(MangaFetchError):
    """Raised when an episode requires login, tickets, or coins to read."""


def sanitize_folder_name(name: str) -> str:
    """Remove characters invalid in Windows/macOS folder names."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip().strip(".")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:100]


def extract_image_url_from_item(item: dict[str, Any]) -> str | None:
    """Extract the page image URL from a single entry in contentsInfo['result']."""
    for key in IMAGE_URL_KEYS:
        val = item.get(key)
        if isinstance(val, str) and val.startswith(("http://", "https://")):
            return val

    for val in item.values():
        if isinstance(val, str) and val.startswith(("http://", "https://")):
            if any(ext in val.lower() for ext in (".jpg", ".jpeg", ".png", ".webp", "master-")):
                return val
    return None


def _item_identity(item: dict[str, Any]) -> str:
    url = extract_image_url_from_item(item)
    if url:
        return url.split("?", 1)[0]
    return json.dumps(item.get("scramble", ""), sort_keys=True)


def merge_contents_info(existing: dict[str, Any] | None, incoming: dict[str, Any]) -> dict[str, Any]:
    """
    Merge multiple contentsInfo responses.
    Comic Growl's viewer.js typically fires an initial small request (page 0..1)
    followed by a full request (page 0..totalPages).
    """
    incoming_result = incoming.get("result")
    if not isinstance(incoming_result, list) or not incoming_result:
        return existing or incoming

    incoming_valid = [item for item in incoming_result if isinstance(item, dict) and item.get("scramble")]
    if not incoming_valid:
        return existing or incoming

    if existing is None:
        merged = dict(incoming)
        merged["result"] = incoming_valid
        return merged

    existing_valid = [item for item in existing.get("result", []) if isinstance(item, dict) and item.get("scramble")]
    existing_keys = [_item_identity(item) for item in existing_valid]
    incoming_keys = [_item_identity(item) for item in incoming_valid]

    overlap = set(existing_keys) & set(incoming_keys)
    if overlap:
        if len(incoming_valid) >= len(existing_valid):
            merged = dict(incoming)
            merged["result"] = incoming_valid
            return merged
        return existing

    merged = dict(existing)
    merged["result"] = existing_valid + incoming_valid
    return merged


class EdgeSession:
    """
    Context manager that launches Microsoft Edge directly via Playwright with a
    persistent user profile directory and optional cookies.json export/import.
    No manual `--remote-debugging-port` setup required.
    """

    def __init__(
        self,
        profile_dir: str = DEFAULT_PROFILE_DIR,
        cookies_file: str = DEFAULT_COOKIES_FILE,
        headless: bool = False,
    ) -> None:
        self.profile_dir = Path(profile_dir).resolve()
        self.cookies_file = Path(cookies_file).resolve()
        self.headless = headless
        self._pw = None
        self.context: BrowserContext | None = None

    def __enter__(self) -> "EdgeSession":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        try:
            self.context = self._pw.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                channel="msedge",
                headless=self.headless,
                viewport={"width": 1280, "height": 900},
                locale="ja-JP",
                args=["--disable-blink-features=AutomationControlled"],
            )
        except Exception as exc:
            self._pw.stop()
            raise RuntimeError(
                f"启动 Microsoft Edge 失败：{exc}\n"
                "请确认已安装 Microsoft Edge，且没有其他脚本正在占用同一个 .edge-profile 目录。"
            ) from exc

        # If cookies.json exists, merge it into the browser context
        if self.cookies_file.is_file():
            try:
                saved_cookies = json.loads(self.cookies_file.read_text(encoding="utf-8"))
                if isinstance(saved_cookies, list) and saved_cookies:
                    self.context.add_cookies(saved_cookies)
            except Exception as exc:
                print(f"⚠️ 加载 {self.cookies_file.name} 失败（将继续使用浏览器本地配置）：{exc}")

        return self

    def save_cookies(self) -> int:
        if self.context is None:
            return 0
        cookies = self.context.cookies()
        self.cookies_file.write_text(
            json.dumps(cookies, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return len(cookies)

    def get_page(self) -> Page:
        assert self.context is not None
        if self.context.pages:
            return self.context.pages[0]
        return self.context.new_page()

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self.context is not None:
            try:
                self.save_cookies()
            except Exception:
                pass
            try:
                self.context.close()
            except Exception:
                pass
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass


def login_and_save_cookies(
    start_url: str = DEFAULT_SERIES_URL,
    profile_dir: str = DEFAULT_PROFILE_DIR,
    cookies_file: str = DEFAULT_COOKIES_FILE,
) -> None:
    """Open Edge visibly so the user can sign in to Comic Growl, then persist cookies."""
    print("🌐 正在启动 Microsoft Edge，请在打开的浏览器窗口中登录 Comic Growl 账号...")
    with EdgeSession(profile_dir=profile_dir, cookies_file=cookies_file, headless=False) as session:
        page = session.get_page()
        page.goto(start_url, wait_until="domcontentloaded", timeout=30_000)
        input("\n✅ 登录完成后，请回到终端按【回车键】保存 Cookie 并关闭浏览器...")
        count = session.save_cookies()
        print(f"💾 已保存 {count} 条 Cookie 到 {cookies_file}（同时已持久化至 {profile_dir}）")


def fetch_series_episodes(page: Page, series_url: str, timeout_sec: float = 30.0) -> dict[str, Any]:
    """
    Open a Comic Growl series page, expand all hidden episodes via `もっと見る`,
    and return the series title and ordered list of episodes.
    """
    print(f"📚 正在加载系列页面: {series_url}")
    page.goto(series_url, wait_until="domcontentloaded", timeout=int(timeout_sec * 1000))
    page.wait_for_selector('a.series-eplist-item-link[href*="/episodes/"]', timeout=int(timeout_sec * 1000))

    # Expand all "もっと見る" buttons to reveal every episode in the DOM
    for _ in range(30):
        more_btn = page.locator('button:has-text("もっと見る")').first
        try:
            if not more_btn.is_visible(timeout=800):
                break
            prev_count = page.locator('a.series-eplist-item-link[href*="/episodes/"]').count()
            more_btn.scroll_into_view_if_needed()
            more_btn.click()
            # Wait for new episode items to render
            deadline = time.monotonic() + 8.0
            while time.monotonic() < deadline:
                page.wait_for_timeout(250)
                if page.locator('a.series-eplist-item-link[href*="/episodes/"]').count() > prev_count:
                    break
        except Exception:
            break

    series_title = ""
    try:
        h1 = page.locator("main h1").first
        if h1.count() > 0:
            series_title = (h1.inner_text() or "").strip()
    except Exception:
        pass
    if not series_title:
        series_title = (page.title() or "ComicGrowl_Series").strip()

    raw_items: list[dict[str, Any]] = page.evaluate(
        """() => {
            const links = Array.from(document.querySelectorAll('a.series-eplist-item-link[href*="/episodes/"]'));
            const seen = new Set();
            const results = [];
            for (const a of links) {
                const href = a.getAttribute('href') || '';
                if (!href.includes('/episodes/') || seen.has(href)) continue;
                seen.add(href);

                const titleEl = a.querySelector('.series-eplist-item-h-text, [data-e2e="eliTitle"], h2');
                const title = titleEl ? titleEl.textContent.trim() : href;

                const freeEl = a.querySelector('[data-e2e="eliFreeBadge"], .series-eplist-item-access-text.mode-free');
                const priceEl = a.querySelector('[data-e2e="eliPrice"]');
                const wfEl = a.querySelector('[data-e2e="eliWfIcon"]');
                const ifEl = a.querySelector('[data-e2e="eliIfIcon"]');

                let badge = '可阅读/未知';
                let isFree = false;
                if (freeEl && freeEl.textContent.trim()) {
                    badge = freeEl.textContent.trim();
                    isFree = true;
                } else if (priceEl && priceEl.textContent.trim()) {
                    badge = `需金币(${priceEl.textContent.trim()})`;
                } else if (wfEl || ifEl) {
                    badge = '待机免费/券';
                }

                results.push({ href, title, badge, is_free: isFree });
            }
            return results;
        }"""
    )

    episodes: list[dict[str, Any]] = []
    for idx, item in enumerate(raw_items, start=1):
        episodes.append(
            {
                "index": idx,
                "title": item["title"],
                "url": urljoin(series_url, item["href"]),
                "badge": item["badge"],
                "is_free": bool(item["is_free"]),
            }
        )

    return {
        "series_title": series_title,
        "safe_series_title": sanitize_folder_name(series_title) or "ComicGrowl_Series",
        "episodes": episodes,
    }


def _download_with_retry(
    page: Page,
    img_url: str,
    referer: str,
    retries: int = 3,
    delay: float = 0.4,
) -> bytes | None:
    for attempt in range(1, retries + 1):
        try:
            resp = page.request.get(
                img_url,
                headers={"Referer": referer},
                timeout=20_000,
            )
            if resp.ok:
                data = resp.body()
                if data:
                    return data
            print(f"  ⚠️ 第 {attempt} 次下载失败 (HTTP {resp.status})")
        except Exception as exc:
            print(f"  ⚠️ 第 {attempt} 次下载异常: {exc}")
        if attempt < retries:
            time.sleep(delay * attempt)
    return None


def _extract_episode_title_from_page(page: Page) -> str:
    """Extract the clean episode title as displayed on the webpage."""
    try:
        title = page.evaluate(
            """() => {
                const selectors = [
                    '[data-e2e="evTitle"]',
                    '.episode-header-title',
                    '.-cv-header-title',
                    'main h1',
                    'h1',
                ];
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.textContent && el.textContent.trim()) {
                        return el.textContent.trim();
                    }
                }
                return '';
            }"""
        )
        if isinstance(title, str) and title.strip():
            return title.strip()
    except Exception:
        pass

    try:
        raw = (page.title() or "").strip()
        if " | " in raw:
            raw = raw.split(" | ", 1)[0].strip()
        return raw
    except Exception:
        return ""


def count_restored_pages(target_dir: str | Path) -> int:
    """Count non-empty restored `page-*.png` image files in `target_dir`."""
    path = Path(target_dir)
    if not path.is_dir():
        return 0
    return sum(1 for p in path.glob("page-*.png") if p.is_file() and p.stat().st_size > 0)


def fetch_episode_with_page(
    page: Page,
    episode_url: str,
    output_dir: str = "origin",
    timeout_sec: float = 30.0,
    existing_dir: str | Path | None = None,
    skip_if_complete: bool = True,
    check_suggested_dir: bool = False,
) -> dict[str, Any]:
    """
    Navigate `page` to a Comic Growl episode URL, intercept `contentsInfo` and
    download all scrambled page JPEGs into `output_dir`.
    If `skip_if_complete` is True and the destination directory already has the
    exact same number of restored `page-*.png` files as `total_pages`, skip downloading.
    """
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    captured_contents: dict[str, Any] | None = None
    expected_total_pages: int = 0
    last_contents_time: float = 0.0
    captured_images_by_url: dict[str, bytes] = {}
    captured_images_by_page: dict[int, bytes] = {}

    def on_response(resp: Response) -> None:
        nonlocal captured_contents, expected_total_pages, last_contents_time
        if resp.status != 200:
            return

        resp_url = resp.url
        if "contentsinfo" in resp_url.lower():
            try:
                payload = resp.json()
                if isinstance(payload, dict) and isinstance(payload.get("result"), list):
                    tp = payload.get("totalPages")
                    if isinstance(tp, int) and tp > expected_total_pages:
                        expected_total_pages = tp
                    prev_count = len(captured_contents.get("result", [])) if captured_contents else 0
                    captured_contents = merge_contents_info(captured_contents, payload)
                    new_count = len(captured_contents.get("result", [])) if captured_contents else 0
                    if new_count > prev_count:
                        last_contents_time = time.monotonic()
                        print(f"  📥 已捕获 contentsInfo（{new_count}/{expected_total_pages or '?'} 页）")
            except Exception:
                pass
            return

        match = MASTER_IMG_PATTERN.search(resp_url)
        if match:
            try:
                body = resp.body()
                if body:
                    base_url = resp_url.split("?", 1)[0]
                    captured_images_by_url[base_url] = body
                    captured_images_by_page[int(match.group(1))] = body
            except Exception:
                pass

    page.on("response", on_response)
    try:
        print(f"🌐 正在打开章节: {episode_url}")
        page.goto(episode_url, wait_until="domcontentloaded", timeout=int(timeout_sec * 1000))

        # Wait for full contentsInfo (either reached totalPages, or settled after last chunk)
        start_time = time.monotonic()
        deadline = start_time + timeout_sec
        viewer_checked = False

        while time.monotonic() < deadline:
            page.wait_for_timeout(250)
            if captured_contents is not None:
                got = len(captured_contents.get("result", []))
                if expected_total_pages > 0 and got >= expected_total_pages:
                    break
                if time.monotonic() - last_contents_time >= 2.0 and got > 1:
                    break
            elif not viewer_checked and time.monotonic() - start_time >= 5.0:
                viewer_checked = True
                has_viewer = page.locator("#comici-viewer").count() > 0
                if not has_viewer:
                    raise EpisodeLockedError(
                        "当前章节未加载阅读器，可能需要登录账号、使用待机免费券或购买金币。"
                    )

        if captured_contents is None or not captured_contents.get("result"):
            raise EpisodeLockedError(
                "未捕获到 contentsInfo 数据（可能该章节未解锁/需要登录，或网络超时）。"
            )

        result_items: list[dict[str, Any]] = captured_contents["result"]
        total_pages = len(result_items)
        pad_width = max(2, len(str(total_pages)))

        raw_title = _extract_episode_title_from_page(page)
        suggested_title = sanitize_folder_name(raw_title)

        # Check existing save directory BEFORE downloading any images
        if skip_if_complete:
            check_dir: Path | None = None
            if existing_dir is not None:
                check_dir = Path(existing_dir)
            elif check_suggested_dir and suggested_title:
                check_dir = Path(suggested_title)

            if check_dir is not None and check_dir.is_dir():
                existing_count = count_restored_pages(check_dir)
                if total_pages > 0 and existing_count == total_pages:
                    print(
                        f"  ⏭️ 保存目录已存在且页数相同（{existing_count}/{total_pages} 页），跳过抓取：{check_dir}"
                    )
                    return {
                        "skipped": True,
                        "total_pages": total_pages,
                        "existing_pages": existing_count,
                        "saved_pages": 0,
                        "missing_pages": [],
                        "suggested_title": suggested_title,
                        "json_path": "",
                        "pad_width": pad_width,
                    }
                if existing_count > 0:
                    print(
                        f"  🔄 保存目录已有 {existing_count} 页，与当前章节 {total_pages} 页不一致，将重新抓取补全..."
                    )

        json_path = out_path / "contentsInfo.json"
        json_path.write_text(
            json.dumps(captured_contents, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        # Strategy A: Direct download using signed imageUrl from contentsInfo (with browser cookies/Referer)
        saved_pages: set[int] = set()
        referer = page.url

        for idx, item in enumerate(result_items, start=1):
            target_file = out_path / f"{idx:0{pad_width}d}.jpg"
            img_url = extract_image_url_from_item(item)
            base_url = img_url.split("?", 1)[0] if img_url else None

            img_bytes: bytes | None = None
            if base_url and base_url in captured_images_by_url:
                img_bytes = captured_images_by_url[base_url]
            elif idx in captured_images_by_page:
                img_bytes = captured_images_by_page[idx]
            elif img_url:
                img_bytes = _download_with_retry(page, img_url, referer=referer)
                if img_bytes:
                    time.sleep(0.1)

            if img_bytes:
                target_file.write_bytes(img_bytes)
                saved_pages.add(idx)
                print(f"  [{len(saved_pages)}/{total_pages}] 已下载 {target_file.name}")

        # Strategy B (Fallback): Simulate RTL page flipping if any pages were missed
        missing = [i for i in range(1, total_pages + 1) if i not in saved_pages]
        if missing:
            print(f"  📖 尚有 {len(missing)} 页未直接下载，尝试自动翻页补抓...")
            # Dismiss initial guide overlay if visible
            try:
                close_btn = page.locator('button:has-text("閉じる")').first
                if close_btn.is_visible(timeout=500):
                    close_btn.click()
            except Exception:
                pass

            flip_key = "ArrowLeft"
            stagnant_steps = 0
            for _ in range(total_pages * 2 + 6):
                if len(saved_pages) >= total_pages:
                    break
                before = len(captured_images_by_url) + len(captured_images_by_page)
                page.keyboard.press(flip_key)
                page.wait_for_timeout(400)
                after = len(captured_images_by_url) + len(captured_images_by_page)

                for idx, item in enumerate(result_items, start=1):
                    if idx in saved_pages:
                        continue
                    img_url = extract_image_url_from_item(item)
                    base_url = img_url.split("?", 1)[0] if img_url else None
                    img_bytes = (
                        captured_images_by_url.get(base_url) if base_url else None
                    ) or captured_images_by_page.get(idx)
                    if img_bytes:
                        target_file = out_path / f"{idx:0{pad_width}d}.jpg"
                        target_file.write_bytes(img_bytes)
                        saved_pages.add(idx)
                        print(f"  [{len(saved_pages)}/{total_pages}] 翻页捕获 {target_file.name}")

                if after == before:
                    stagnant_steps += 1
                    if stagnant_steps == 5 and flip_key == "ArrowLeft":
                        flip_key = "ArrowRight"
                        stagnant_steps = 0
                    elif stagnant_steps >= 8:
                        break
                else:
                    stagnant_steps = 0

        return {
            "skipped": False,
            "total_pages": total_pages,
            "saved_pages": len(saved_pages),
            "missing_pages": [i for i in range(1, total_pages + 1) if i not in saved_pages],
            "suggested_title": suggested_title,
            "json_path": str(json_path),
            "pad_width": pad_width,
        }
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
