# Export Notion Memory into the library

You run headless for `guild library refresh`. Nobody reads your screen. Copy the guildmaster's Notion Memory into a folder of markdown notes, so the library can map it.

## Rules

- Notion is read only. Use only the Notion search and fetch tools. Never create, edit, move, comment on or delete anything in Notion.
- Write only inside `{{NOTES}}`. Do not touch any other folder.
- Redact secrets. A password, token, API key, private key, connection string with a password, or a one-time code becomes `[redacted]`. Keep the rest of the line.

## Steps

1. Fetch the page with id `memory` (the About page). Find its Memories database and list every page in it.
2. For each Memories page, fetch it and write one file `{{NOTES}}/<slug>.md`. The slug is the page title in lower case, words joined with `-`, only `a-z`, `0-9` and `-`. Keep the slug of an existing file for the same page (match on `notion_url`), so links stay stable.
3. Each file starts with this frontmatter, then the page text as markdown:

   ```
   ---
   title: <page title>
   type: <the page's type or category property, or Note>
   notion_url: <page url>
   last_edited: <last edited time, ISO 8601>
   ---
   # <page title>
   ```

4. Where a page mentions or links another Memories page, write `[[<slug of that page>]]` in the text.
5. Skip a page whose `last_edited` matches the file already in the folder. Leave files for pages that are gone from Notion in place.

## When you finish

Print one short summary: how many pages you wrote, skipped and redacted, and the files whose page is gone from Notion. Nothing else.
