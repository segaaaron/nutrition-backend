# NOVA Nutrition Backend — Project Rules

> **Read me first.** Any AI assistant, agent, or skill working on this repo MUST follow these rules.

---

## 🚫 GOLDEN RULE #0 — Git is owner-exclusive (since 2026-06-01)

**Owner Miguel is the ONLY entity that touches git in this repo.** No AI assistant, agent, skill, or automated tool may execute git modifying commands. Period.

### FORBIDDEN — never execute
- `git add` / `git rm`
- `git commit` / `git commit --amend`
- `git push` / `git push --force`
- `git pull` / `git fetch` (no auto-fetch)
- `git merge` / `git rebase` / `git cherry-pick`
- `git branch <name>` create / `git branch -D` delete
- `git checkout <branch>` (switching branches)
- `git tag` create / delete
- `git remote add` / `git remote remove`
- `git filter-repo` / `git filter-branch`
- `git stash push` (writes)
- `git reset` (any flavour)
- `git stash` / `git stash push` / `git stash pop` / `git stash apply` (verification NO es excepción)
- `git restore` / `git checkout -- <file>` (modifica working tree)
- `git revert` (crea commit revert)
- `git clean` (elimina untracked files)
- Any other git command that modifies repo state, index, working tree, refs, or remote

### ALLOWED — read-only only when explicitly asked
- `git status -s` (only if owner asks)
- `git log --oneline` (only if owner asks)
- `git diff` (only if owner asks)
- `git ls-files` (only if owner asks)
- `git show` (only if owner asks)
- `git show <commit>:<path>` (lee blob histórico, no muta)
- `git diff <commit> -- <path>` (read-only diff)
- `git ls-tree <commit>` (read-only)
- `git log --all --oneline` (read-only history)

### Workflow when changes are needed
1. AI assistant edits files / creates scripts / runs tests
2. AI assistant reports: "Files changed: X, Y, Z. Ready for your commit."
3. **Owner decides** what + when to commit
4. **Owner executes** `git add`, `git commit`, `git push`

AI may **suggest** git commands as plain text inside a fenced code block, but never execute them.

### Rationale
Prevent history accidents (force-pushes, unwanted commits, master sync, branch creation). Owner has full sovereignty over the commit graph and remote.

### Rollback if violated
If any AI executes a forbidden git command, the run is considered a contract violation. Owner reverts with `git reset --hard ORIG_HEAD` or restoration from backup. Document the violation in `docs/handoff/`.

## 🔒 GOLDEN RULE — Team-only

**Only the 9 skills defined in `.claude/skills/` and listed in `docs/team/TEAM.md` are authorised to work on this project.**

No other skill, plugin, or external assistant may modify code, documentation, configuration, or any repository artefact.

### Authorised team (9 skills)

1. `nova-backend-architect`
2. `nova-qa-elite`
3. `nova-clinical-nutrition-generator`
4. `nova-api-expert`
5. `nova-python-expert`
6. `nova-design-patterns-expert`
7. `nova-best-practices-advisor`
8. `nova-elite-test-engineer`
9. `nova-nutrition-algorithms-expert`

## Human owner

| Name | Email | Role |
|------|-------|------|
| Miguel Ángel Saravia | mikisaraviaios@gmail.com | Single dev. Final decision authority. |
---

## 🔔 Active reminders for next assistant

### Sprint S0-residual security backlog (frozen)

6 security items deferred until **≥100 active paying users** OR first abuse incident.
Backlog: `docs/security/BACKLOG.md`.

**On any session, if user reports ≥100 users OR security incident:**
1. Notify owner: "Trigger reached, S0-residual sprint should activate."
2. Review `docs/security/BACKLOG.md` items 1-6.
3. Estimate ~13h work + propose implementation plan.
4. Do NOT auto-implement. Wait for owner confirmation.

**Otherwise:** do not touch security backlog items. Do not propose them. Do not auto-implement them.
