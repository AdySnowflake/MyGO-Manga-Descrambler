import os
import re

# 设置目标文件夹路径
folder_path = "origin/"

# 遍历文件夹中的所有文件
for filename in os.listdir(folder_path):
    # 匹配符合命名规则的文件
    match = re.match(r"master-\d+-([0-9]{2})\.jpg", filename)
    if match:
        new_name = f"{match.group(1)}.jpg"
        src = os.path.join(folder_path, filename)
        dst = os.path.join(folder_path, new_name)
        os.rename(src, dst)
        print(f"重命名: {filename} → {new_name}")
