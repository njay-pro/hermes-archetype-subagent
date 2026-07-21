# Skills

> Skills shipped with this plugin. The plugin's archetypes are most useful
> when paired with the orchestration + briefing skills — together they
> form a complete "archetype-based delegation" workflow.

---

## What's in this folder

| Skill | What it does | Lines |
|---|---|---|
| `knows_multiAgent-promptEngineering/` | 4 archetype briefing templates (XML prompt scaffolds for each archetype) — for when the orchestrator needs to write a goal for a specialist | 250 |
| `knows_multiAgent-orchestrationHowTo/` | Routing playbook: when to use which archetype, escalation codes, 3-level loop, anti-patterns, profile-aware defaults | 527 |

**Total:** 777 lines, 2 skills.

---

## Install

```bash
cd docs/skills
./install.sh                 # install to all 10 destinations
./install.sh --dry-run       # preview
./install.sh --uninstall     # remove
```

`install.sh` symlinks each skill to:

- `~/.hermes/skills/` (global)
- `~/.hermes/profiles/{default,ana-board,dua-branding,niqah,omca-development}/skills/` (per profile)
- `~/Desktop/AGENT-*` workspaces (any `AGENT-*/.opencode/skills/` that exists)

**Idempotent:** safe to re-run. Symlinks that already point to this skill
are skipped. Symlinks that point to a different source (e.g. the OMCA
hub) are NOT clobbered — they're reported and left alone.

**Hermes restart required** after install:

```bash
pkill -f 'hermes.*gateway run --replace' && hermes gateway run --replace &
```

---

## When to use each skill

### `knows_multiAgent-promptEngineering`

Load when **writing a goal for a specific archetype**. The skill gives
you:

- Per-archetype XML prompt templates (consultant / long_horizon /
  high_hallucination / speedster)
- Role postures (interaction mode per archetype)
- Memory injection firewall rules
- 3-level escalation loop (Retry → Replan & Upgrade → Decompose)

### `knows_multiAgent-orchestrationHowTo`

Load when **deciding which archetype to use, or recovering from a
subagent failure**. The skill gives you:

- Q1-Q6 routing decision tree
- 4 composition patterns (Extract→Reason→Validate, Ideate→Decompose→Execute,
  Cheap Cascade, Long-Running Pipeline)
- 10 escalation codes with orchestrator actions
- 7 anti-patterns
- Profile-aware defaults (ana-board, dua-branding, niqah, etc.)

---

## Why bundle the skills with the plugin?

You could install the skills separately from the OMCA skill hub
(`~/Desktop/OMCA-GODMODE/skills/`). But the archetype plugin's archetypes
are **most useful** with these two skills. Bundling means:

- A new user who clones the plugin gets a working setup in one command
- The skills + plugin version are kept in lockstep (no drift)
- The `docs/skills/` folder acts as a "minimum viable skill set" for
  archetype-based delegation

If you have a richer skill set in the OMCA hub, you can use those
instead. Use the bundled skills as a **fallback** that always works.

---

## Adding a new skill to this folder

1. Create `docs/skills/your_skill_name/SKILL.md` with frontmatter
   (see `knows_prompts-material` for the canonical format).
2. Run `./install.sh` from `docs/skills/`.
3. Restart Hermes.
4. Update the table in this file.

---

## Why the skills folder ships under `docs/`, not at the plugin root

Convention: `docs/` is for **read-the-codebase** content. Skills are
operational artifacts that get installed into the runtime, not part of
the plugin's own code. Keeping them under `docs/skills/` makes the
boundary clear:

- Plugin code is at the plugin root (router.py, archetype_delegate.py, etc.)
- Skills that the plugin USES are at `docs/skills/` and are installed by
  `install.sh`

When you `pip install` this plugin in the future, only the root + docs/
metadata (README, AGENTS.md, etc.) goes into the wheel. Skills stay
separate so you can choose to bundle them or not.