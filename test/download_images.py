
import os
import requests

# 创建保存目录
os.makedirs("../test/新建文件夹/images", exist_ok=True)

# 所有图片的 URL 列表
image_urls = [

    ("https://viewer.comic-growl.com/book/49b25cbec774e75f0f3b4f9e6d45af8e/master-1739335655030-05.jpg?Expires=1746073834&Signature=aXI2qgthjLBYlBu~VXHX43jNCEC7AhnBcCGYRiC2XdxtZhV~KvBzhrCkZU2CsZBbi7g~nx0XHN3y2SgdVtyEIL48jsVrRCbeKab3-riEPr~kDzzvrtJVSsAOOkOoqYhMQp-ycGYMiug9izGYLLzszOq8~a2hhv0aC~3bN2tmRNjyVBkXOdH6k413KC2lIL4NYp3zGm7hvcRcL2X97O-Kz5BnUvzI6m22xpwQM0tz-XHm3YG49bgmQAckwBFEJV5mOlbRgcRCv66tRFlxSD6JVhs8nWDPRfxCOIk8s7cenw9BDijJ2MpB445xzsbL9k8OTy6qvwVEsqVVZ9RJmjIykA__&Key-Pair-Id=K3KQVUDNN9LCAH", "images/downloaded_image-05.jpg")

]


# 通用请求头
headers = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://comic-growl.com/episodes/6e043cd6ebc5b",
    "Origin": "https://comic-growl.com",
}

# 执行下载
for url, filename in image_urls:
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            with open(filename, "wb") as f:
                f.write(resp.content)
            print(f"✅ 成功下载: {filename}")
        else:
            print(f"❌ 下载失败: {filename}，状态码 {resp.status_code}")
    except Exception as e:
        print(f"⚠️ 错误: {filename} -> {e}")
