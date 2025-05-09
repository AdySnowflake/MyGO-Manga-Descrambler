import json


def extract_scramble_list(json_path):
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    scramble_list = []
    for item in data.get("result", []):
        scramble_str = item.get("scramble")
        if scramble_str:
            scramble = json.loads(scramble_str)
            scramble_list.append(scramble)

    return scramble_list


if __name__ == "__main__":
    path = "origin/contentsInfo.json"  # JSON 文件路径
    scramble_list = extract_scramble_list(path)

    print("scramble_list = [")
    for row in scramble_list:
        print("    " + str(row) + ",")
    print("]")
