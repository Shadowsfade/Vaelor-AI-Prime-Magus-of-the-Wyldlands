import json
import os

from .ollama_client import ask_ollama
from .aider_spell import cast_aider_spell


BASE_DIR = os.path.dirname(__file__)



def load_json(filename):

    path = os.path.join(BASE_DIR, filename)

    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)



def get_spell_model(spell_name):

    models = load_json("models.json")

    mapping = models["spells"]


    category = mapping.get(
        spell_name,
        "primary"
    )


    return models["llm"][category]["model"]



def needs_aider(prompt):

    actions = [
        "create",
        "make",
        "build",
        "implement",
        "add",
        "edit",
        "modify",
        "change",
        "update",
        "write"
    ]


    targets = [
        "file",
        ".py",
        "script",
        "class",
        "function",
        "module",
        "project"
    ]


    prompt = prompt.lower()


    return (
        any(x in prompt for x in actions)
        and
        any(x in prompt for x in targets)
    )



def cast_spell(spell_name, prompt):


    if spell_name == "code_forge" and needs_aider(prompt):

        return (
            "[AiderSpell Summoned]\n\n"
            +
            cast_aider_spell(prompt)
        )


    model = get_spell_model(spell_name)


    return ask_ollama(
        model,
        prompt
    )



if __name__ == "__main__":

    print(
        cast_spell(
            "core_reasoning",
            "Confirm the Vaelor spell router is working."
        )
    )