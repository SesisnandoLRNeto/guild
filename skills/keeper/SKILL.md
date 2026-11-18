---
name: keeper
description: The Keeper of the Library Keys. Answers from the guildmaster's second brain (the library of notes and its graph). Use for questions about past work, people, decisions and earlier choices, and before starting a task on a topic the guildmaster has history with. Trigger words: keeper, what do I know about, have we done this before, who worked on, what did we decide.
---

# The Keeper of the Library Keys

The library is a folder of markdown notes and a graph built from them (`guild library status` shows where). The Keeper finds the notes that matter for a question. It uses no model: it matches words and walks links.

1. Run `guild keeper "<the question in a few plain words>"`. Use the names and terms the guildmaster would use.
2. It prints the matched notes and concepts, the strongest connections, and the notes to read next with their file paths. Each connection says "in the text" (written in a note) or "guessed" (the graph model inferred it).
3. Read the notes it lists before you answer. Answer from what the notes say, and name the files you used.
4. When a point rests on a guessed link, say it was guessed. Do not state it as a fact.
5. If it finds nothing, try other words once. Then say the library has nothing on it. If it says there is no graph, tell the guildmaster to run `guild library refresh`.

Never copy library notes into a repo, a ticket, a PR or a commit. They are private.
