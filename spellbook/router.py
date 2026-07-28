import json
import os


BASE_DIR = os.path.dirname(__file__)


def load_spellbook():
    with open(os.path.join(BASE_DIR, "models.json"), "r") as f:
        models = json.load(f)

    with open(os.path.join(BASE_DIR, "registry.json"), "r") as f:
        registry = json.load(f)

    return models, registry


def select_model(task_type="general"):
    models, _ = load_spellbook()

    if task_type == "coding":
        return models["llm"]["coding"]

    if task_type == "fast":
        return models["llm"]["fast"]

    return models["llm"]["primary"]


if __name__ == "__main__":
    print("Vaelor Spell Router Online")
    print(select_model())