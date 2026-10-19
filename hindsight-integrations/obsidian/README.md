# ContextBase for Obsidian

> ContextBase source distribution: build/install this integration from this repository until its ContextBase package is published. Package names below identify the new build; they do not imply registry availability. Configure your own service URL; localhost URLs are self-hosted examples. The underlying Hindsight SDK dependency keeps its published package/import names.

Give your [Obsidian](https://obsidian.md) vault an AI agent that actually knows your notes, powered by [ContextBase](https://github.com/RSIXDB/hindsight).

The plugin syncs your vault into a ContextBase memory bank and adds a chat panel whose answers are **grounded on your notes — and cite them**.

## Source of truth stays in Obsidian

A hard rule of this plugin: **ContextBase is never a second source of truth.**

- Sync is **one-way**: Obsidian → ContextBase. Your vault is canonical.
- Every chat answer **cites the note it came from**, so you fix things at the source.
- Chat conversations are **not stored by default** (toggle in settings).
- Edit a note and ContextBase reconverges on the next sync.

## What it does

- **Incremental vault sync** — each note becomes a ContextBase document. Edits upsert, deletes remove. A content hash skips unchanged notes.
- **Implicit scoping** — every note is auto-tagged on ingest with its **vault**, **folder** (and sub-folders), and **created/updated dates**. You never think about scope until you recall — then filter by any combination (vault + folder + date) via ContextBase's `tag_groups`. Multiple vaults share one bank and stay separable by their `vault:` tag.
- **Same data from UI and API** — the Obsidian chat panel and your external automations (n8n, Hermes, etc.) hit the same bank with the same tags, so they see exactly the same scoped view.
- **Grounded chat** — a side panel that answers questions over your notes via ContextBase `reflect`. Each answer lists the **notes retrieved** (click to open) and a **reasoning** disclosure showing what each step queried. Scope a question with the **vault / folder** dropdowns above the ask bar, start a fresh thread with **New chat**, and flip on **Debug logging** to see the exact `reflect` request + retrieved notes in the console.
- **Manual or automatic** — sync on every edit, or run _Sync vault now_ on demand.
- **Always-visible sync status** — a live indicator in the status bar (and the chat header) shows how many notes are synced, when the last sync ran, and any pending edits — e.g. `ContextBase ✓ 412 notes · 2m ago`. A refresh button beside it (which spins while syncing) triggers a sync on click, so nothing happens invisibly.

### Scoping

| Dimension            | Tag(s)                               | Example recall filter    |
| -------------------- | ------------------------------------ | ------------------------ |
| Vault                | `vault:<name>`                       | only the Work vault      |
| Folder (+ ancestors) | `folder:Work`, `folder:Work/Clients` | everything under `Work/` |
| Date                 | `created:2026-03`, `updated:2026-06` | notes updated this month |

Your own frontmatter `tags`/`aliases` are carried through too.

## Installation

> Configure your ContextBase service URL and credentials from your deployment administrator. For a local service, build and run this repository first.

While in beta, install via [BRAT](https://github.com/TfTHacker/obsidian42-brat): add the repo [`RSIXDB/hindsight-obsidian`](https://github.com/vectorize-io/hindsight-obsidian) — the dedicated plugin repo BRAT installs from (see [Distribution](#distribution--maintainers)) — then enable it under **Settings → Community plugins**.

**Self-hosting alternative:**

```bash
pip install hindsight-all
export CONTEXTBASE_API_LLM_API_KEY=your-openai-key
hindsight-api
```

## Configuration

Open **Settings → ContextBase**:

| Setting                   | Default                              | Description                                                                                    |
| ------------------------- | ------------------------------------ | ---------------------------------------------------------------------------------------------- |
| API URL                   | `http://localhost:8888` | ContextBase server (use `http://localhost:8888` for self-hosted)                                 |
| API key                   | —                                    | ContextBase remote service API key                                                                        |
| Bank name                 | `obsidian`                           | Shared bank for all your vaults (separated by `vault:` tags)                                   |
| Include / exclude folders | —                                    | Limit which notes sync                                                                         |
| Sync on edit              | on                                   | Re-ingest notes automatically as you edit                                                      |
| Observation consolidation | server default                       | Optional named observation scope for newly ingested content                                    |
| Default chat depth        | low                                  | Reflect budget for chat answers                                                                |
| Remember conversations    | **off**                              | When on, chat turns are stored in Hindsight (creates memory outside your vault)                |
| Prefix document IDs       | on                                   | Vault-prefixes ids so shared-bank vaults don't collide; turn off only for a single-vault setup |

## Commands

- **Sync vault now** — full reconcile (ingest changed notes, prune deleted ones).
- **Ingest current note** — force-sync the active note.
- **Open chat** — open the grounded chat panel.

## Headless / CLI ingestion (no desktop app)

Running your vault on an always-on headless server (kept current on disk by Obsidian Sync)? The same ingestion runs without the Obsidian app, via the `contextbase-obsidian-sync` CLI shipped in this package. It drives the **same sync engine** as the plugin, so it produces identical document ids, scope tags, and prune-ownership — a vault can be synced from a server and later opened interactively elsewhere without the two ingesters fighting or duplicating documents.

```bash
npm install -g contextbase-obsidian

# one-shot reconcile (cron-friendly)
contextbase-obsidian-sync reconcile \
  --vault ~/Vaults/Brain --bank my-vault \
  --api-url http://localhost:8888 --api-token hsk_...

# or keep it running and sync changes live
contextbase-obsidian-sync reconcile --vault ~/Vaults/Brain --bank my-vault --watch
```

`--api-url` / `--api-token` fall back to `CONTEXTBASE_API_URL` / `CONTEXTBASE_API_TOKEN`. Other flags: `--include <folder>` / `--exclude <folder>` (repeatable), `--vault-name <name>` (defaults to the vault dir name), `--prefix-doc-id` (prefix document ids with the vault name for multi-vault banks), `--observation-scopes <combined|shared|per_tag|all_combinations>`, `--index <file>`, and `--help`.

Observation consolidation is optional. When unset, the integration omits `observation_scopes` and preserves the ContextBase server's default. Source tags are still retained for filtering and provenance in every mode. Changing this setting affects new ingestion work; it does not automatically move existing memories or observations into the new scope, so historical scope migration requires deliberate document reingestion.

The sync index (the CLI's equivalent of the plugin's `data.json`) defaults to a **per-target** file under `~/.contextbase/obsidian/` — `<vault>-<bank>-<fingerprint>.json`, deliberately **outside** the vault so Obsidian Sync never propagates it. The index is bound to the destination it was built against (API origin, bank, vault path, and the `--vault-name`/`--prefix-doc-id` document-id namespace); pointing a saved index at a different bank or API — whether via the default path or an explicit `--index` — **fails closed** with an actionable message rather than silently skipping files or mis-attributing deletes to a bank it never wrote to. Changing `--include`/`--exclude` on the _same_ destination is fine (it reuses the index and prunes newly-excluded notes it owns there).

> **Running the CLI and the plugin against the same bank + vault?** Keep their config identical (`--include`/`--exclude`, `--vault-name`, `--prefix-doc-id`, and `--observation-scopes` matching the plugin's settings). They each keep their own index, and a reconcile prunes only what its own index tracks — so mismatched folder/id scope on the two frontends could let one prune documents the other owns, while mismatched observation scope would produce inconsistent consolidation.

## How it works

```
note created / edited ──▶ retain(documentId = note path)     (upsert; replaces prior version)
note renamed         ──▶ deleteDocument(old) + retain(new)
note deleted         ──▶ deleteDocument(path)
"Sync vault now"     ──▶ reconcile: ingest drifted notes, prune orphans

chat turn            ──▶ reflect(question) over the whole bank
                         └─ answer + citations (→ source notes) + reasoning
```

A local index (note path → content hash + mtime) means only changed notes are re-ingested.

## Development

```bash
npm install
npm run lint     # tsc --noEmit
npm test         # vitest
npm run build    # esbuild → main.js
```

To try it in a real vault, copy `main.js`, `manifest.json`, and `styles.css` into
`<vault>/.obsidian/plugins/contextbase/` and enable the plugin.

## Distribution & maintainers

> **Edit only this monorepo.** The dedicated repo is generated automatically on release — never commit to it directly.

| Repo                                                                                    | Role                                                                                                                                                                    |
| --------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `hindsight-integrations/obsidian/` (this monorepo)                                      | **Source of truth.** All code, tests, and the npm package (`contextbase-obsidian`) live here.                                                               |
| [`RSIXDB/hindsight-obsidian`](https://github.com/vectorize-io/hindsight-obsidian) | **Generated distribution repo** for BRAT + the Obsidian community store. The release workflow mirrors this folder here (via `git subtree`) and cuts the GitHub Release. |

**Why two repos?** Obsidian's BRAT and community store install from a repo's **latest GitHub Release**. We can't use this monorepo's releases — they pollute the core product's release list and steal the "Latest" badge, and BRAT reads a repo's _latest_ release (the core app), not a tag. So distribution releases go to a dedicated repo.

**Releasing an update** — just cut the monorepo release as usual:

```bash
./scripts/release-integration.sh obsidian <version>
```

The `Release Integration` workflow then automatically (see `.github/workflows/release-integration.yml` → "Mirror Obsidian plugin"):

1. publishes the npm package `contextbase-obsidian`,
2. mirrors this folder to the **root** of `RSIXDB/hindsight-obsidian` with `git subtree push --prefix=hindsight-integrations/obsidian`, and
3. cuts a GitHub Release there tagged with the bare version (e.g. `0.1.0`, matching `manifest.json`) so BRAT / the community store pick it up.

No manual second-repo step. The mirror needs a repo/org secret **`OBSIDIAN_DIST_TOKEN`** — a token with `contents: write` on `RSIXDB/hindsight-obsidian`.
