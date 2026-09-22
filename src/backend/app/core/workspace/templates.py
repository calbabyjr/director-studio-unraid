"""Default workspace markdown. Seeded on first use; placeholders stay out of the prompt."""

from __future__ import annotations

USER_FILENAME = "user.md"
AGENTS_FILENAME = "AGENTS.md"
TASKS_FILENAME = "TASKS.md"

USER_TEMPLATE = """# User

Who you are and how you like the Director to work with you.

- How to address you
- Taste, tone, and hard limits that apply to every production
- Always / never rules about identity, wardrobe, or content
"""

GLOBAL_AGENTS_TEMPLATE = """# This director

Standing instructions for this directing soul across every production it leads.

- How this director names shots and assets
- Continuity rules that belong to this persona, not one film
"""

PROJECT_AGENTS_TEMPLATE = """# This production

Instructions that apply only to this film.
"""

DIRECTOR_TASKS_TEMPLATE = """# Tasks

Open work this director still owes. Unfinished items use `- [ ]`. The Director rereads this every 30 minutes.
"""

PROJECT_TASKS_TEMPLATE = """# Tasks

Open work for this film. Unfinished items use `- [ ]`. The Director rereads this every 30 minutes.
"""
