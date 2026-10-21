# Prompt templates

Fill in the `{…}` parts. Run the designers in parallel, in the background.

## Research agent

> Research what makes a good design for {kind of app, e.g. "a data-heavy web app"}, then write a concise, practical brief for designers who will propose redesigns of this app: {two or three sentences on what it does and for whom}.
>
> Use web search (several searches, recent sources) to cover:
> 1. General principles: Rams, Nielsen's heuristics, visual hierarchy, progressive disclosure.
> 2. Best practice for this kind of interface: {e.g. dashboards and data visualisation: Tufte, Few, chart choice, colour-blind-safe palettes, accessibility}.
> 3. How the best products in this domain present things: {e.g. "investing tools", "budgeting apps"}.
> 4. What the framework can and can't do: {framework and version}, its layout primitives, theming and limits.
>
> Output, under about 900 words: "Principles" (10–15 numbered rules, each with a one-line reason), "Patterns from {domain} tools", "{framework} toolbox and limits", "Pitfalls", "Sources" (URLs). Don't edit files. Return the brief.

## Designer agent (one per direction)

> You are a product designer proposing a redesign of {app} in {repo path}. Your direction: **{letter}. "{name}": {one-sentence direction}.**
>
> Inputs:
> - The brief at `.claude/designs/BRIEF.md`. Read it first and cite its principles by number.
> - The code is read-only for you.
> - {If the app runs: the URL, and how to take screenshots with Playwright; screenshots go in `.claude/designs/{letter}/`.}
> - How the app works today: {short description of the screens and behaviour}.
> - Audience: {who}.
> - The user's feedback so far, quoted: {quotes}.
>
> Write ONE file, `.claude/designs/{letter}-{name}.md`, of at most about 900 words:
> 1. Concept, in 2–3 sentences.
> 2. ASCII wireframes (under 100 columns) for {the states: e.g. empty, typical, comparing}.
> 3. Changes compared with today: a numbered list, each tied to principle numbers.
> 4. Implementation sketch: which framework primitives, and what isn't feasible.
> 5. Effort (S/M/L per change) and the 3 changes to do first.
> 6. Trade-offs and risks.
>
> Don't modify repo files. Final message: the file path and a 5-line summary.

## Mockup checklist

For each `{letter}-{name}.html`:
- [ ] A static page: inline CSS, an `<svg>` per chart, no scripts. A Google Font `<link>` is fine.
- [ ] The same state and data as the other mockups, with numbers from the app's own code.
- [ ] Width 1440px. Real `<button>` and `<label>` elements. Text contrast at least 4.5:1.
- [ ] It shows what's distinctive about this direction, not just a different colour scheme.
