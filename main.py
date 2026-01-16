import importlib
import os
import shutil

from extract_list import extract_scramble_list
from restore_images import restore_image

# Step 1: Extract scramble list from JSON
scramble_list = extract_scramble_list("origin/contentsInfo.json")

# Step 2: Rename files in origin/ (if needed)
rename = importlib.import_module("rename")  # Executes renaming logic from rename.py

# Step 3: Restore images
os.makedirs("restored", exist_ok=True)

for i, scramble in enumerate(scramble_list, start=1):
    image_path = f"origin/{i:02}.jpg"
    output_path = f"restored/page-{i:02}.png"
    restore_image(image_path, scramble, output_path)

# Step 4: Clean up and recreate origin folder
try:
    shutil.rmtree("origin")
    os.makedirs("origin")
    print("✅ 已清空 origin 文件夹")
except Exception as e:
    print(f"❌ 清空 origin 文件夹出错：{e}")
