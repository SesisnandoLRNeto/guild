#!/usr/bin/env python3
"""The guild's lore: who the agents are and what each state looks like, in one place.

Models become classes (an Oracle, an Archmage, a Knight, a Scout), states become creatures and
places (an orc, a troll, the tavern, the castle gate). The campaign board, the docket, the
At-a-glance strip and the validation page all read from here, so they tell one story. The plain
meaning always travels next to the flavour, so nobody has to decode a page to know what is wrong.

  lore.py show        print the bestiary
"""
import sys

# ── races: the peoples of the guild, drawn in web/races.svg ──────────────────
# The guild's own side (the models, the roles) and the Horde side (what trouble looks like).
RACES = {
    "human": ("Human", "the guildmaster's people", "guild"),
    "highelf": ("High elf", "old magic, long memory", "guild"),
    "nightelf": ("Night elf", "sees in the dark, reads every line", "guild"),
    "dwarf": ("Dwarf", "born at the forge, steady hands", "guild"),
    "gnome": ("Gnome", "small, fast and clever with gears", "guild"),
    "dragon": ("Dragon", "sees further than anyone, and is paid like it", "guild"),
    "orc": ("Orc", "charges at the first stack trace", "horde"),
    "troll": ("Troll", "holds the bridge until the toll is paid", "horde"),
    "goblin": ("Goblin", "lives in red tests and multiplies there", "horde"),
    "undead": ("Undead", "a quest that stopped and told no tale", "horde"),
}

# ── classes: who is doing the work ────────────────────────────────────────────
# (word in the model name, class, icon, race, one line about them)
CLASSES = [
    ("fable", "Oracle", "crystal", "dragon", "sees further than the rest, and is paid like it"),
    ("opus", "Archmage", "hat", "highelf", "deep judgment, slow and sure"),
    ("thinking", "Archmage", "hat", "highelf", "deep judgment, slow and sure"),
    ("gpt-5", "Archmage", "hat", "highelf", "deep judgment, from another guild"),
    ("sonnet", "Knight", "helm", "dwarf", "steady hands for the build"),
    ("deepseek", "Knight", "helm", "dwarf", "steady hands, hired from another guild"),
    ("codex", "Artificer", "potion", "gnome", "gears, images and long mechanical work"),
    ("haiku", "Scout", "bow", "gnome", "fast and light, for the easy roads"),
    ("flash", "Scout", "bow", "gnome", "fast and light, for the easy roads"),
    ("mini", "Scout", "bow", "gnome", "fast and light, for the easy roads"),
]
TIER_CLASS = {"plan": ("Sage", "scroll", "highelf", "thinks before anyone moves"),
              "build": ("Knight", "helm", "dwarf", "steady hands for the build"),
              "deep": ("Archmage", "hat", "highelf", "deep judgment, slow and sure"),
              "light": ("Scout", "bow", "gnome", "fast and light, for the easy roads")}
ROLES = {"quartermaster": ("Quartermaster", "horn", "highelf", "sends the parties out and reads their reports"),
         "guildmaster": ("Guildmaster", "crown", "human", "you: the one who rules"),
         "helper": ("Squire", "sword", "human", "carries one part of a bigger quest"),
         "validator": ("Inquisitor", "shield", "human", "checks the work without reading the diff"),
         "reviewer": ("Elf", "elf", "nightelf", "reads every diff before the gate; nothing gets past those ears")}

# ── the bard: one dry line under a decision, picked by the board so it does not change on reload ──
BARD = [
    "Choose well. The bard writes down everything.",
    "A fork in the road is still a road. Pick one.",
    "The oracle has seen both paths. It still wants your word.",
    "No path is free. Ask what each one costs tomorrow.",
    "Knights wait. Orcs do not. Decide before the next one shows up.",
    "The map is not the road. Read the cases before you rule.",
    "Elves read the diff. Only you read the business.",
]


def quip(seed=""):
    """One line from the bard, the same one for the same seed."""
    return BARD[sum(ord(c) for c in str(seed)) % len(BARD)]


def klass(model="", tier=""):
    """{"name", "icon", "race", "blurb"} for an agent, from its model first, its tier second."""
    m = (model or "").lower()
    for word, name, icon, race, blurb in CLASSES:
        if word in m:
            return {"name": name, "icon": icon, "race": race, "blurb": blurb}
    if tier in TIER_CLASS:
        name, icon, race, blurb = TIER_CLASS[tier]
        return {"name": name, "icon": icon, "race": race, "blurb": blurb}
    if m:
        return {"name": "Wanderer", "icon": "torch", "race": "human", "blurb": "a model the guild does not know yet"}
    return None


def race(key):
    """{"key", "name", "blurb", "side"} for a race key, or None."""
    if key in RACES:
        name, blurb, side = RACES[key]
        return {"key": key, "name": name, "blurb": blurb, "side": side}
    return None


# the creature a state shows, when the state is trouble
STATE_RACE = {"blocked": "troll", "failed": "orc", "checks-red": "goblin", "stopped": "undead"}


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
    return {"line": line, "icon": icon, "plain": plain, "quip": quip, "race": STATE_RACE.get(key, "")}


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
    ("Trial", "The elves' court", "elf"),
    ("PR open", "The gate", "gate"),
    ("Merged", "The treasury", "chest"),
]
STEP = {plain: (place, icon) for plain, place, icon in STEPS}


if __name__ == "__main__":
    if sys.argv[1:] != ["show"]:
        raise SystemExit(__doc__)
    print("races")
    for key, (name, blurb, side) in RACES.items():
        print(f"  {key:<9} {name:<10} {side:<6} {blurb}")
    print("classes")
    for word, name, icon, race_, blurb in CLASSES:
        print(f"  {word:<9} {name:<10} {RACES[race_][0]:<10} {blurb}")
    for tier, (name, icon, race_, blurb) in TIER_CLASS.items():
        print(f"  tier {tier:<4} {name:<10} {RACES[race_][0]:<10} {blurb}")
    print("states")
    for k, (line, icon, plain, quip) in STATES.items():
        print(f"  {k:<15} {line:<36} {plain}")
    print("roles")
    for key, (name, icon, race_, blurb) in ROLES.items():
        print(f"  {key:<13} {name:<12} {RACES[race_][0]:<10} {blurb}")
    print("places")
    for key, place, hint, icon in COLUMNS:
        print(f"  {key:<8} {place:<16} {hint}")
