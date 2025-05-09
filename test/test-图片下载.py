import requests

url = "https://viewer.comic-growl.com/book/49b25cbec774e75f0f3b4f9e6d45af8e/master-1739335654766-01.jpg?Expires=1746073834&Signature=ELoE-8YTFU3dXLjpvQ7lH8ydwyGhK-UYgUQXp9IY2tORDEIju0Shk1LfTClHBH-CNWL0rAvRDnLgIB20kxQr8LUcClLuMjXb6obCYlV103RXsGHZKUCiA5aie9sgHrKeuLfeVKII5X3Nv6Ubj7lsQGucVNg5-jix2cO8S~O80hC2FPEmqS1UKd-qatuGWdX~6lraXf0tzPPJa4~hdwfeePOex5mZqirQT690IC4LHVF3eZYtehnWjiqQ6kGlRa-N3Odqbz5CReD7GkJGIGiiOcdhfQGqP8xeS3XiGmVhZ9fmRk9R8wHCF3j~MrdDA5lw13jeKffDm67auasEp8WAMQ__&Key-Pair-Id=K3KQVUDNN9LCAH"

headers = {
    "Referer": "https://comic-growl.com/episodes/6e043cd6ebc5b",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36 Edg/135.0.0.0",
    "Origin": "https://comic-growl.com",
}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    with open("downloaded_image1.jpg", "wb") as f:
        f.write(response.content)
    print("✅ 图片下载成功：downloaded_image1.jpg")
else:
    print(f"❌ 下载失败，状态码：{response.status_code}")
