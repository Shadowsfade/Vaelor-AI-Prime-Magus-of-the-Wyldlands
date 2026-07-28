import json
import os

path = os.path.join(
    os.path.dirname(__file__),
    "spells.json"
)

with open(path, "r") as f:
    spells = json.load(f)

print("Vaelor Spellbook Registry Loaded")
print("--------------------------------")

for name, data in spells["spells"].items():
    print(f"{name}: {data['status']}")