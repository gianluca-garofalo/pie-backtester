---
name: proposing-design-options
description: Use when the user wants to see different design options, redesign proposals, mockups or alternative layouts for an app, page or screen before deciding, or says they don't like how something looks and want alternatives.
---

# Proposing design options

## Overview
People choose designs by looking, not by reading. Ground the options in researched principles, have each direction designed independently, show every option as a picture of the **same screen with the same real data**, recommend one, and record what the user decided.

## Where things go

| What | Where |
|---|---|
| Research brief | `.claude/designs/BRIEF.md` |
| One spec per direction | `.claude/designs/<letter>-<name>.md` |
| Mockup source and picture | `.claude/designs/<letter>-<name>.html` and `.png` |
| The decision, including overrides ("keep the donut") | project memory, plus the ledger or plan if the project has one |

Keep `.claude/designs/` out of git if the repo is public. Never leave the pictures only in a scratch or temp folder: they're the record of why the design looks the way it does.

## Steps
1. **Scope, one question at a time, as multiple choice:** what bothers the user, which screen and state to mock, and anything that must stay. Default to 3 directions, each showing the main screen in its most informative state (e.g. with real content loaded, not empty).
2. **Research first.** Run one subagent with the research prompt in `prompts.md`, which searches the web. Save the brief. Every proposal cites its numbered principles.
3. **Directions in parallel.** Run one subagent per direction, using the designer prompt in `prompts.md`. Make the directions really different:
   - **refine:** today's layout, polished
   - **restructure:** a bolder change to the layout
   - **audience-led:** e.g. guided for beginners

   Give each one the brief, a description of the current app, the user's feedback so far (quoted), and the app's limits (framework, what can't be built).
4. **Mockups.** Write one static HTML file per direction: inline CSS, charts as inline SVG, no scripts. All of them show the same state with numbers computed by the app's own code. If the data is private (finances, health), use the app's example or demo data instead of the user's. Render them with `python <this skill's folder>/render_mockups.py .claude/designs`. The script ships next to this file and needs Playwright. Then look at each PNG before showing it.
5. **Present them.** Give the paths to the PNGs. Only if the user wants them in a browser, publish them on a temporary page and say it gets deleted after they decide. Then show:
   - a table comparing the directions (idea, what stands out, effort, main risk)
   - where the directions agree
   - your recommendation

   Ask for a pick as multiple choice, with "mix" as an option.
6. **After the choice:**
   - Save the decision and every override to memory.
   - Delete any hosted page.
   - Keep the PNGs and specs.
   - Implement in small batches with commits, re-running tests and screenshots after each.

## Common mistakes

| Mistake | Fix |
|---|---|
| Options designed from taste, with no shared principles | Research brief first; proposals cite its numbers |
| Each mockup shows a different state or made-up numbers | One state, real (or example) data, computed by the app |
| Mockups only in a scratch folder, or only on a hosted page | PNGs and specs in `.claude/designs/` |
| A gallery with no opinion | Comparison table, where they agree, and a recommendation |
| The user's override is forgotten in the next session | Write it to memory straight away |
| Designing something the framework can't build | Each proposal states what isn't feasible |
