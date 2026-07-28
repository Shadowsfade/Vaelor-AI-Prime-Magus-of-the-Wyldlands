from core.runtime import get_runtime


runtime = get_runtime()

print("Runtime Online")
print()

print("Name:")
print(runtime.name)

print()

print("Title:")
print(runtime.title)

print()

print("Debug:")
print(runtime.debug)

print()

print("Description:")
print(runtime.describe())