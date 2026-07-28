from core.memory import VaelorMemory


memory = VaelorMemory()


memory.remember(
    "fact",
    "The Architect is building Vaelor inside Project Wyld."
)


print(memory.recall())