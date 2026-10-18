# Tester script: build your own agent (AC43, milestone M2)

A short session (about 20 minutes) with someone who doesn't write code. It checks that a non-technical person can create an agent **with one helper and one skill**, test it and publish it, **without help and without seeing Markdown**. Run it with 2 or 3 people; M2 is reached when they succeed.

## Before the session (you, 5 minutes)

1. A clean stack: `./setup.sh` (any model; a real one shows the most, the demo model works offline).
2. Open Nuria at http://localhost:3000 in a fresh browser window. Have this page and a notes file ready.
3. Don't show them the Agents or Skills pages beforehand.

## What you say (read it as written)

> "This is Nuria, an app for building your own AI assistants. I'd like you to build one that helps plan a family trip. It should have a helper that finds restaurants, and it should follow a packing checklist that you write yourself. Then try it, and when you're happy, make it available to everyone. Think aloud as you go. I can't help you, but there are no wrong answers: we're testing the app, not you."

Then stay quiet. If they're stuck for more than 2 minutes, note it, and only then say "What would you try next?" (that counts as help).

## What they should manage on their own

| # | Step | Done? | Notes (time, hesitations, words they used) |
|---|---|---|---|
| 1 | Find where to make a skill (**Skills → New skill**) and write the packing checklist | | |
| 2 | Start a new agent (**Agents → New agent**), by describing it or otherwise | | |
| 3 | End up with a helper for restaurants (drafted, or added by hand) | | |
| 4 | Attach their checklist skill to the agent (**Skills** section) | | |
| 5 | Try it in the **test chat** and see an answer | | |
| 6 | **Publish** it | | |
| 7 | Chat with the published agent | | |

**Pass:** steps 1 to 6 without help. **Also check:** they never saw Markdown, YAML or code (note any screen where they did).

## Afterwards (5 minutes)

Ask, and write down their words:
1. "What was the hardest part?"
2. "Was anything confusing or surprising?"
3. "What did you expect a 'skill' to be? Was it that?"
4. "Would you use this? For what?"

Record the result in `docs/progress/phase-L3c.md` (date, person's background in a few words, steps passed, quotes). Never record names or contact details.
