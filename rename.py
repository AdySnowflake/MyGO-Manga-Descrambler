import os
import re

MASTER_FILE_PATTERN = re.compile(r"master-\d+-([0-9]+)\.jpg$", re.IGNORECASE)


def rename_origin_files(folder_path: str = "origin", pad_width: int = 2) -> int:
    """Rename `master-xxxxx-XX.jpg` files in `folder_path` to zero-padded `{page}.jpg`."""
    if not os.path.isdir(folder_path):
        return 0

    renamed_count = 0
    for filename in sorted(os.listdir(folder_path)):
        match = MASTER_FILE_PATTERN.match(filename)
        if not match:
            continue
        page_num = int(match.group(1))
        new_name = f"{page_num:0{pad_width}d}.jpg"
        src = os.path.join(folder_path, filename)
        dst = os.path.join(folder_path, new_name)
        if src == dst:
            continue
        if os.path.exists(dst):
            os.remove(dst)
        os.rename(src, dst)
        print(f"重命名: {filename} → {new_name}")
        renamed_count += 1

    return renamed_count


if __name__ == "__main__":
    rename_origin_files()
