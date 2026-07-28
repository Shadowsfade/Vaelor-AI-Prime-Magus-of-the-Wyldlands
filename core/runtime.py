from .config_loader import config
from .brain import VaelorBrain


class VaelorRuntime:
    """
    Central runtime representation of Vaelor.

    This object connects:
    - configuration
    - identity
    - capabilities
    - models
    - reasoning systems
    """

    def __init__(self):
        self.identity = config.identity
        self.personality = config.personality
        self.settings = config.settings
        self.capabilities = config.capabilities
        self.lore = config.lore
        self.vaelor = config.vaelor
        self.world_authority = config.world_authority
        self.roadmap = config.roadmap
        self.models = getattr(config, "models", {})

        self.name = self.identity.get("name", "Unknown")
        self.title = self.identity.get("title", "Unknown")
        self.debug = self.settings.get("debug_mode", False)

        # Initialize reasoning layer
        self.brain = VaelorBrain(self)

    def describe(self):
        return {
            "name": self.name,
            "title": self.title,
            "debug": self.debug,
            "capabilities": self.capabilities,
            "models": self.models
        }

    def get_capabilities(self):
        return self.capabilities

    def get_identity(self):
        return self.identity

    def get_personality(self):
        return self.personality


runtime = VaelorRuntime()


def get_runtime():
    return runtime