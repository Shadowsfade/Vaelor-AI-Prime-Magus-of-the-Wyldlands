from core.runtime import VaelorRuntime
from core.brain import VaelorBrain


runtime = VaelorRuntime()

brain = VaelorBrain(
    runtime
)


brain.remember(
    "fact",
    "The Architect prefers careful incremental development."
)


print(
    brain.think(
        "Who is the Architect?"
    )
)