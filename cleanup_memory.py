import json

path = "memory/archive.json"

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)

bad_text = "The Wyldlands magic system uses mana crystals for spell casting"

data = [
    item for item in data
    if item.get("content") != bad_text
]

with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=4)

print("Removed incorrect memory if it existed.")
