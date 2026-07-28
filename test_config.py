from core.config_loader import config


print("Vaelor Config Loaded")
print()

print("Name:")
print(
    config.identity["name"]
)

print()

print("Title:")
print(
    config.identity["title"]
)

print()

print("Debug Mode:")
print(
    config.settings["debug_mode"]
)

print()

print("Capabilities:")
print(
    config.capabilities
)