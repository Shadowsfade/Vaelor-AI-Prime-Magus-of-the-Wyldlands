import json
import os


BASE_DIR = os.path.dirname(
    os.path.dirname(__file__)
)

CONFIG_DIR = os.path.join(
    BASE_DIR,
    "config"
)


def load_json(filename):
    """
    Load a Vaelor configuration file.
    """
    path = os.path.join(
        CONFIG_DIR,
        filename
    )

    if not os.path.exists(path):
        raise FileNotFoundError(
            f"Vaelor configuration missing: {path}"
        )

    with open(
        path,
        "r",
        encoding="utf-8"
    ) as file:
        return json.load(file)


class VaelorConfig:
    """
    Central configuration registry.

    All Vaelor systems should access configuration
    through this object rather than reading files directly.
    """

    def __init__(self):
        self.identity = load_json("identity.json")
        self.personality = load_json("personality.json")
        self.settings = load_json("settings.json")
        self.capabilities = load_json("capabilities.json")
        self.lore = load_json("lore.json")
        self.vaelor = load_json("vaelor.json")
        self.world_authority = load_json("world_authority.json")
        self.models = load_json("models.json")
        self.roadmap = load_json("roadmap.json")


config = VaelorConfig()