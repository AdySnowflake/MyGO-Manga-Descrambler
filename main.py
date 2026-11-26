import argparse
import os
import shutil
import sys
from pathlib import Path
from typing import Any

from browser_fetcher import (
    DEFAULT_COOKIES_FILE,
    DEFAULT_PROFILE_DIR,
    DEFAULT_SERIES_URL,
    EdgeSession,
    EpisodeLockedError,
    MangaFetchError,
    fetch_episode_with_page,
    fetch_series_episodes,
    login_and_save_cookies,
    sanitize_folder_name,
)
from extract_list import extract_scramble_list
from rename import rename_origin_files
from restore_images import restore_image


def descramble_origin_to_dir(
    origin_dir: str | Path,
    target_dir: str | Path,
    keep_origin: bool = False,
) -> int:
    """Descramble all images in `origin_dir` and write PNGs directly to `target_dir`."""
    origin_path = Path(origin_dir)
    json_path = origin_path / "contentsInfo.json"
    if not json_path.is_file():
        raise FileNotFoundError(f"未找到元数据文件: {json_path}")

    scramble_list = extract_scramble_list(str(json_path))
    if not scramble_list:
        raise ValueError(f"{json_path} 中未解析出有效的 scramble 数据。")

    pad_width = max(2, len(str(len(scramble_list))))
    rename_origin_files(str(origin_path), pad_width=pad_width)

    out_path = Path(target_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    for stale_png in out_path.glob("page-*.png"):
        try:
            stale_png.unlink()
        except OSError:
            pass

    restored_count = 0
    for i, scramble in enumerate(scramble_list, start=1):
        image_path = origin_path / f"{i:0{pad_width}d}.jpg"
        if not image_path.is_file():
            print(f"  ⚠️ 缺少第 {i} 页图片，跳过: {image_path.name}")
            continue
        output_file = out_path / f"page-{i:0{pad_width}d}.png"
        restore_image(str(image_path), scramble, str(output_file))
        restored_count += 1

    print(f"🎉 还原完成：{restored_count}/{len(scramble_list)} 页 → {out_path}")

    if not keep_origin:
        try:
            shutil.rmtree(origin_path)
            origin_path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            print(f"⚠️ 清空临时目录 {origin_path} 出错：{exc}")

    return restored_count


def parse_episode_selection(selection: str, episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Parse user selection: 'free', 'all', or comma-separated indices/ranges like '1-5,8,10-12'."""
    sel = selection.strip().lower()
    if sel in ("free", "f"):
        return [ep for ep in episodes if ep["is_free"]]
    if sel in ("all", "a"):
        return list(episodes)

    chosen_indices: set[int] = set()
    for part in sel.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start_i, end_i = int(start_s.strip()), int(end_s.strip())
            for i in range(min(start_i, end_i), max(start_i, end_i) + 1):
                chosen_indices.add(i)
        else:
            chosen_indices.add(int(part))

    return [ep for ep in episodes if ep["index"] in chosen_indices]


def run_series_mode(
    series_url: str,
    args: argparse.Namespace,
) -> None:
    with EdgeSession(
        profile_dir=args.profile_dir,
        cookies_file=args.cookies_file,
        headless=args.headless,
    ) as session:
        page = session.get_page()
        series_info = fetch_series_episodes(page, series_url, timeout_sec=args.timeout)
        episodes = series_info["episodes"]
        series_dir_name = sanitize_folder_name(args.output) if args.output else series_info["safe_series_title"]

        if not episodes:
            print("❌ 未在系列页面找到任何章节链接。")
            sys.exit(1)

        free_count = sum(1 for ep in episodes if ep["is_free"])
        print(f"\n📖 系列：《{series_info['series_title']}》（共 {len(episodes)} 话，其中标注免费 {free_count} 话）")
        print("-" * 68)
        for ep in episodes:
            print(f"  [{ep['index']:02d}] {ep['title']:<18} | {ep['badge']:<12} | {ep['url']}")
        print("-" * 68)

        selection = args.select
        if not selection:
            print("请选择要抓取的章节：")
            print("  - 输入 free ：仅抓取当前标注免费的话数")
            print("  - 输入 all  ：尝试抓取全部话数（已登录/已购会自动抓取，未解锁自动跳过）")
            print("  - 输入范围  ：例如 1-5 或 1,2,6")
            selection = input("请输入选择（默认 free）：").strip() or "free"

        try:
            targets = parse_episode_selection(selection, episodes)
        except ValueError:
            print(f"❌ 无法解析选择范围：{selection}")
            sys.exit(1)

        if not targets:
            print("⚠️ 没有匹配的章节可抓取。")
            return

        series_root = Path(series_dir_name)
        series_root.mkdir(parents=True, exist_ok=True)

        success_eps = 0
        skipped_eps = 0
        locked_eps = 0
        used_folder_names: set[str] = set()

        for pos, ep in enumerate(targets, start=1):
            ep_folder_name = sanitize_folder_name(ep["title"]) or str(ep["index"])
            if ep_folder_name in used_folder_names:
                ep_folder_name = f"{ep_folder_name}_{ep['index']}"
            used_folder_names.add(ep_folder_name)
            ep_out_dir = series_root / ep_folder_name

            print(f"\n[{pos}/{len(targets)}] 处理第 {ep['index']} 话：{ep['title']} ({ep['badge']})")

            origin_dir = Path("origin")
            if origin_dir.exists():
                shutil.rmtree(origin_dir)
            origin_dir.mkdir(parents=True, exist_ok=True)

            try:
                result = fetch_episode_with_page(
                    page=page,
                    episode_url=ep["url"],
                    output_dir=str(origin_dir),
                    timeout_sec=args.timeout,
                    existing_dir=ep_out_dir,
                    skip_if_complete=not args.overwrite,
                )
                if result.get("skipped"):
                    skipped_eps += 1
                    continue

                missing = result.get("missing_pages", [])
                if missing:
                    print(f"  ⚠️ 第 {ep['index']} 话有缺失页：{missing}")

                descramble_origin_to_dir(
                    origin_dir=origin_dir,
                    target_dir=ep_out_dir,
                    keep_origin=args.keep_origin,
                )
                success_eps += 1
            except EpisodeLockedError as exc:
                print(f"  🔒 跳过未解锁章节：{exc}")
                locked_eps += 1
            except Exception as exc:
                print(f"  ❌ 抓取失败：{exc}")

        print(
            f"\n✅ 系列处理完成！输出目录：{series_root.resolve()}\n"
            f"   成功：{success_eps} 话 | 已存在且页数一致跳过：{skipped_eps} 话 | 未解锁跳过：{locked_eps} 话"
        )


def run_single_episode_mode(episode_url: str, args: argparse.Namespace) -> None:
    origin_dir = Path("origin")
    if origin_dir.exists():
        shutil.rmtree(origin_dir)
    origin_dir.mkdir(parents=True, exist_ok=True)

    pre_target_dir = Path(sanitize_folder_name(args.output)) if args.output else None

    with EdgeSession(
        profile_dir=args.profile_dir,
        cookies_file=args.cookies_file,
        headless=args.headless,
    ) as session:
        page = session.get_page()
        result = fetch_episode_with_page(
            page=page,
            episode_url=episode_url,
            output_dir=str(origin_dir),
            timeout_sec=args.timeout,
            existing_dir=pre_target_dir,
            skip_if_complete=not args.overwrite,
            check_suggested_dir=(args.output is None),
        )

    if result.get("skipped"):
        return

    suggested = result.get("suggested_title", "")
    episode_name = args.output
    if episode_name is None:
        if suggested:
            user_input = input(f"请输入输出目录名（直接回车使用 [{suggested}]）：").strip()
            episode_name = user_input or suggested
        else:
            episode_name = input("请输入输出目录名（直接回车使用 restored）：").strip() or "restored"

    target_dir = Path(sanitize_folder_name(episode_name) or "restored")
    descramble_origin_to_dir(origin_dir=origin_dir, target_dir=target_dir, keep_origin=args.keep_origin)


def run_local_mode(args: argparse.Namespace) -> None:
    episode_name = args.output
    if episode_name is None:
        episode_name = input("请输入话数/输出目录名（直接回车使用 restored）：").strip() or "restored"
    target_dir = Path(sanitize_folder_name(episode_name) or "restored")
    descramble_origin_to_dir(origin_dir="origin", target_dir=target_dir, keep_origin=args.keep_origin)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MyGO Manga Descrambler - 自动启动 Edge 保存 Cookie 并全流程抓取/还原 Comic Growl 漫画"
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--login",
        action="store_true",
        help="打开 Edge 登录 Comic Growl 并持久化保存 Cookie",
    )
    mode_group.add_argument(
        "--series",
        help=f"抓取整部漫画系列页（例如 {DEFAULT_SERIES_URL}）",
    )
    mode_group.add_argument(
        "--url",
        help="抓取单话链接（如果传入 /series/ 链接也会自动按系列页处理）",
    )
    mode_group.add_argument(
        "--local",
        action="store_true",
        help="使用本地 origin/ 文件夹中已有的图片和 contentsInfo.json（原模式）",
    )
    parser.add_argument(
        "--select",
        default=None,
        help="系列模式下要抓取的章节：free / all / 范围如 1-5,8",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="指定输出目录名称",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="使用无头模式运行 Edge（适合已保存 Cookie 后的全自动抓取）",
    )
    parser.add_argument(
        "--keep-origin",
        action="store_true",
        help="还原完成后保留 origin/ 目录中的原始文件",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="系列模式下覆盖重新抓取本地已存在的章节",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="单页加载超时秒数（默认: 30）",
    )
    parser.add_argument(
        "--profile-dir",
        default=DEFAULT_PROFILE_DIR,
        help=f"Edge 持久化配置目录（默认: {DEFAULT_PROFILE_DIR}）",
    )
    parser.add_argument(
        "--cookies-file",
        default=DEFAULT_COOKIES_FILE,
        help=f"Cookie 导出/加载文件路径（默认: {DEFAULT_COOKIES_FILE}）",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    try:
        if args.login:
            login_and_save_cookies(
                start_url=DEFAULT_SERIES_URL,
                profile_dir=args.profile_dir,
                cookies_file=args.cookies_file,
            )
            return

        if args.series:
            run_series_mode(args.series, args)
            return

        if args.url:
            if "/series/" in args.url:
                run_series_mode(args.url, args)
            else:
                run_single_episode_mode(args.url, args)
            return

        if args.local:
            run_local_mode(args)
            return

        # Interactive menu when launched with no arguments (e.g., via run.bat)
        print("请选择运行模式：")
        print("  1. 自动抓取整部漫画系列（支持批量与断点续传）")
        print("  2. 自动抓取单话漫画")
        print("  3. 打开 Edge 登录 Comic Growl 并保存 Cookie")
        print("  4. 使用本地 origin/ 文件夹（原模式）")
        choice = input("请输入选项 [1/2/3/4]（默认 1）：").strip() or "1"

        if choice == "3":
            login_and_save_cookies(
                start_url=DEFAULT_SERIES_URL,
                profile_dir=args.profile_dir,
                cookies_file=args.cookies_file,
            )
        elif choice == "4":
            run_local_mode(args)
        elif choice == "2":
            ep_url = input("请输入单话链接：").strip()
            if not ep_url:
                print("❌ 未输入链接，已退出。")
                sys.exit(1)
            run_single_episode_mode(ep_url, args)
        else:
            s_url = input(f"请输入系列页链接（直接回车默认 MyGO 雨中祈晴）：").strip() or DEFAULT_SERIES_URL
            run_series_mode(s_url, args)
    except (MangaFetchError, RuntimeError) as exc:
        print(f"\n❌ {exc}")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n⏹️ 用户已中断操作。")
        sys.exit(130)


if __name__ == "__main__":
    main()
