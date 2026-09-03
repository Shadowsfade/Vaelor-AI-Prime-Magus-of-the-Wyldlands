# Vaelor Architecture & Oz-Like Intelligence Roadmap

## Primary Goal

Create Vaelor as an Oz-like Arcane Intelligence:
a persistent, context-aware assistant capable of helping build,
manage, and eventually create Project Wyld.

The priority is not simply making Vaelor answer questions.
The priority is creating a reliable intelligence layer with:

- Memory
- Context awareness
- Safe tools
- Project understanding
- Development assistance
- World-building capability

---

# PHASE 1 � Stabilize the Tower

Goal:
"I can start Vaelor anywhere and trust that he works."

## Completed

[x] One-command startup
[x] One-command shutdown
[x] Diagnostics system
[x] Virtual environment recovery
[x] Memory foundation
[x] SSH remote workflow
[x] Ollama integration
[x] FastAPI foundation
[x] Web interface foundation

## Remaining

[x] Better memory retrieval
[x] Persistent chat history
[ ] User/session identity
[ ] Service management dashboard
[ ] Reliable remote launcher

---

# PHASE 2 � True Memory Architecture

Current:

archive.json
|
+-- facts


Future:

Memory System

+-- Identity Memory
�   - Who is the Architect?
�   - Vaelor identity
�
+-- Project Memory
�   - Project Wyld decisions
�   - Architecture choices
�
+-- Technical Memory
�   - Code locations
�   - Systems
�   - Dependencies
�
+-- World Memory
�   - Wyldlands lore
�   - Locations
�   - Creatures
�
+-- Conversation Memory
�   - Previous discussions
�   - Design decisions
�
+-- Experience Memory
    - What was tried
    - What failed
    - Lessons learned


Required upgrades:

[x] Memory tagging
[x] Relevance search
[x] Memory ranking
[x] Duplicate consolidation
[x] Automatic bounded summaries and recent-turn retention
[x] Chat history storage

---

# PHASE 3 � Give Vaelor Hands

Goal:
Move from "code advisor" to "controlled development partner."

Architecture:

stage
 |
proposal
 |
approve
 |
execute


Required systems:

[x] Tool calling architecture
[x] Project scanner
[x] Multi-file reader
[x] Code proposal system
[x] Approval workflow
[x] Automated testing
[x] Error recovery
[x] Safe execution layer

---

# PHASE 4 � Project Wyld Integration

Goal:
Vaelor assists in creating the game world.

Unity:

[ ] C# script awareness
[ ] Prefab awareness
[ ] Scene awareness
[ ] ScriptableObject support
[ ] Build pipeline support


Unreal:

[ ] C++ awareness
[ ] Blueprint awareness
[ ] Data Asset support
[ ] Behavior Tree support
[ ] Level data awareness


---

# PHASE 5 � Living World Intelligence

Long-term vision:

NPCs become more than dialogue trees.

NPC:

+-- Personality Memory
+-- World Knowledge
+-- Goals
+-- Relationships
+-- Current State
+-- Vaelor reasoning layer


The world remembers.

The world reacts.

The world evolves.

---

# Current Development Priority

1. Add ConPTY full-screen terminal input and resize support
2. Extend bounded lexical code discovery with persistent semantic indexing
3. Add reusable rules, workflows, and MCP tool extensibility
4. Add scheduling and recurring task support
5. Validate installer/runtime behavior on a clean machine
6. Strengthen user/session identity and remote authentication
7. Add hardware-aware model routing and multi-agent orchestration
8. Create Unity/Unreal bridges

The foundation comes first.

The intelligence grows from the foundation.
