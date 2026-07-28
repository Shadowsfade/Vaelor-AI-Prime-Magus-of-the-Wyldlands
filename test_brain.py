from core.runtime import get_runtime


runtime = get_runtime()


print("Brain Online")

response = runtime.brain.think(
    "What is the Wyldlands?"
)

print(response)