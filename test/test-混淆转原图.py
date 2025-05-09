from PIL import Image

image_path = "downloaded_image.jpg"
output_path = "restored_page01.png"

# scramble[i] 表示：正确图第 i 块 ← 混淆图中的第 scramble[i] 块（编号顺序为竖向）
scramble = [10, 0, 3, 5, 15, 7, 14, 8, 6, 13, 12, 1, 4, 2, 9, 11]

def restore_image(image_path, scramble, output_path):
    img = Image.open(image_path)
    width, height = img.size
    tile_w = width // 4
    tile_h = height // 4

    # 切块顺序：竖着编号（从上到下，再从左到右）
    tiles = []
    for x in range(4):
        for y in range(4):
            box = (x * tile_w, y * tile_h, (x + 1) * tile_w, (y + 1) * tile_h)
            tiles.append(img.crop(box))

    # 新图：还原图像，贴的位置也要按“竖向编号顺序”计算
    new_img = Image.new("RGB", (width, height))
    for i in range(16):
        # 竖向编号 → 位置（行、列）：
        x = (i // 4) * tile_w
        y = (i % 4) * tile_h
        tile = tiles[scramble[i]]
        new_img.paste(tile, (x, y))

    new_img.save(output_path, format="PNG")
    print(f"✅ 已按竖向编号还原图像：{output_path}")

restore_image(image_path, scramble, output_path)
