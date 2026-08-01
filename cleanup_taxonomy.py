import json

path = "memory/archive.json"

with open(path, "r", encoding="utf-8") as f:
    data = json.load(f)


for item in data:

    content = item.get("content", "")


    if "Vaelor's internal Spellbook uses mana crystal terminology" in content:
        item["category"] = "rule"


    if "The Architect is building Project Wyld" in content:
        item["category"] = "project"


with open(path, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=4)


print("Memory taxonomy cleanup complete.")
