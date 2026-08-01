import json
import os
from .llm_client import chat as llm_chat, chat_stream
from .aider_spell import cast_aider_spell

BASE_DIR = os.path.dirname(__file__)

def load_json(filename):
    path = os.path.join(BASE_DIR, filename)
    with open(path, "r", encoding="utf-8") as file:
        return json.load(file)

def needs_aider(prompt):
    actions = ["create","make","build","implement","add","edit","modify","change","update","write"]
    targets = ["file",".py","script","class","function","module","project"]
    p = prompt.lower()
    return any(x in p for x in actions) and any(x in p for x in targets)

def cast_spell(spell_name, prompt, images=None, history=None):
    if spell_name == "code_forge" and needs_aider(prompt) and not images:
        return "[AiderSpell Summoned]\n\n" + cast_aider_spell(prompt)
    if spell_name == "vision" or images:
        return llm_chat(prompt, spell="core_reasoning", images=images, history=history)
    return llm_chat(prompt, spell=spell_name, images=images, history=history)

def cast_spell_stream(spell_name, prompt, history=None):
    return chat_stream(prompt, spell=spell_name, history=history)

if __name__ == "__main__":
    print(cast_spell("core_reasoning", "Confirm router."))
