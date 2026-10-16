#!/usr/bin/env python3
"""The guild's lore: who the agents are and what each state looks like, in one place.

Models become classes (an Oracle, an Archmage, a Knight, a Scout), states become creatures and
places (an orc, a troll, the tavern, the castle gate). The campaign board, the docket, the
At-a-glance strip and the validation page all read from here, so they tell one story. The plain
meaning always travels next to the flavour, so nobody has to decode a page to know what is wrong.

  lore.py show        print the bestiary
"""
import sys

# ── classes: who is doing the work ────────────────────────────────────────────
# (word in the model name, class, icon, one line about them)
CLASSES = [
    ("fable", "Oracle", "crystal", "sees further than the rest, and is paid like it"),
    ("opus", "Archmage", "hat", "deep judgment, slow and sure"),
    ("thinking", "Archmage", "hat", "deep judgment, slow and sure"),
    ("gpt-5", "Archmage", "hat", "deep judgment, from another guild"),
    ("sonnet", "Knight", "helm", "steady hands for the build"),
    ("deepseek", "Knight", "helm", "steady hands, hired from another guild"),
    ("codex", "Artificer", "potion", "gears, images and long mechanical work"),
    ("haiku", "Scout", "bow", "fast and light, for the easy roads"),
    ("flash", "Scout", "bow", "fast and light, for the easy roads"),
    ("mini", "Scout", "bow", "fast and light, for the easy roads"),
]
TIER_CLASS = {"plan": ("Sage", "scroll", "thinks before anyone moves"),
              "build": ("Knight", "helm", "steady hands for the build"),
              "deep": ("Archmage", "hat", "deep judgment, slow and sure"),
              "light": ("Scout", "bow", "fast and light, for the easy roads")}
ROLES = {"quartermaster": ("Quartermaster", "horn", "sends the parties out and reads their reports"),
         "guildmaster": ("Guildmaster", "crown", "you: the one who rules"),
         "helper": ("Squire", "sword", "carries one part of a bigger quest"),
         "validator": ("Inquisitor", "shield", "checks the work without reading the diff"),
         "reviewer": ("Inspector", "scroll", "reads the diff and finds what the adventurer missed")}


def klass(model="", tier=""):
    """{"name", "icon", "blurb"} for an agent, from its model first, its tier second."""
    m = (model or "").lower()
    for word, name, icon, blurb in CLASSES:
        if word in m:
            return {"name": name, "icon": icon, "blurb": blurb}
    if tier in TIER_CLASS:
        name, icon, blurb = TIER_CLASS[tier]
        return {"name": name, "icon": icon, "blurb": blurb}
    if m:
        return {"name": "Wanderer", "icon": "torch", "blurb": "a model the guild does not know yet"}
    return None


# ── creatures and places: what a state looks like ─────────────────────────────
# state -> (what you see, icon, what it means in plain words, one dry line)
STATES = {
    "blocked": ("A troll holds the bridge", "troll", "blocked: it needs something it cannot get alone",
                "Trolls take tolls. Pay it, or find a ford."),
    "failed": ("Slain by an orc", "orc", "failed", "The orc read the stack trace and charged."),
    "stopped": ("Fled the dungeon, no tale told", "skull", "stopped without a report",
                "No tale, no loot. Send a scout to see what happened."),
    "checks-red": ("Goblins in the tests", "goblin", "the checks are failing",
                   "Goblins love a red test. Count them before they multiply."),
    "needs-decision": ("The oracle awaits your word", "crystal", "a decision only you can make",
                       "The oracle speaks only when asked. Your turn."),
    "asks you": ("The oracle awaits your word", "crystal", "a question only you can answer",
                 "The oracle speaks only when asked. Your turn."),
    "held": ("Camped until the day you set", "tent", "on hold", "The fire is banked. It wakes on its day."),
    "idle": ("Resting at the tavern", "mug", "idle", "Ale is cheap. Memory is not."),
    "to do": ("Posted at the tavern", "mug", "not started", "Every quest starts as a note on the tavern wall."),
    "working": ("On the road", "map", "an agent is working", ""),
    "planned": ("Reading the map", "map", "planning before the build", ""),
    "plan": ("Reading the map", "map", "planning before the build", ""),
    "done": ("Back with the loot", "chest", "finished", "Count the gold before you merge it."),
    "trial-pass": ("Back with the loot", "chest", "finished, trial passed", "Count the gold before you merge it."),
    "trial-skip": ("Back with the loot", "chest", "finished, trial skipped", "Count the gold before you merge it."),
    "closed": ("Loot in the treasury", "chest", "closed", ""),
    "merged": ("Loot in the treasury", "chest", "merged into the main branch", ""),
    "pr": ("At the castle gate", "gate", "PR open, waiting for review",
           "The gatekeeper reads slowly. Reviews are like that."),
}


def lore(state, column="", pr=None):
    """{"line", "icon", "plain", "quip"} for a card, or None when the state has no story."""
    key = state
    if pr and pr.get("state") == "merged":
        key = "merged"
    elif column == "trial" or (pr and pr.get("state") in ("open", "draft") and state in ("done", "trial-pass", "trial-skip")):
        key = "pr"
    if key not in STATES:
        return None
    line, icon, plain, quip = STATES[key]
    return {"line": line, "icon": icon, "plain": plain, "quip": quip}


# ── the map: columns and the steps of a quest ─────────────────────────────────
COLUMNS = [  # (key, place, plain hint, icon)
    ("todo", "The Tavern", "to do: not started, idle, or stopped", "mug"),
    ("road", "On the Road", "in progress: an agent is working", "map"),
    ("waiting", "The Oracle", "needs you: a decision only you can make", "crystal"),
    ("trial", "The Castle Gate", "in review: PR open, waiting for the gatekeeper", "gate"),
    ("done", "The Treasury", "done: merged or closed this week", "chest"),
]
STEPS = [  # (plain step, place, icon): the path on the At-a-glance strip
    ("Asked", "The call", "horn"),
    ("Plan", "The map", "map"),
    ("Build", "The forge", "anvil"),
    ("Checks", "The gauntlet", "shield"),
    ("Trial", "The trial", "swords"),
    ("PR open", "The gate", "gate"),
    ("Merged", "The treasury", "chest"),
]
STEP = {plain: (place, icon) for plain, place, icon in STEPS}


if __name__ == "__main__":
    if sys.argv[1:] != ["show"]:
        raise SystemExit(__doc__)
    print("classes")
    for word, name, icon, blurb in CLASSES:
        print(f"  {word:<9} {name:<10} {blurb}")
    for tier, (name, icon, blurb) in TIER_CLASS.items():
        print(f"  tier {tier:<4} {name:<10} {blurb}")
    print("states")
    for k, (line, icon, plain, quip) in STATES.items():
        print(f"  {k:<15} {line:<36} {plain}")
    print("places")
    for key, place, hint, icon in COLUMNS:
        print(f"  {key:<8} {place:<16} {hint}")
