# Roadmap

## Current state (Model A: pre-built packs)

Language packs — word lists plus their reference phoneme sequences — are
built **offline**, ahead of time, using the grapheme-to-phoneme (G2P) tooling
in [`authoring/`](../authoring/). An instructor who wants a new word added
today has to:

1. Send the word list to whoever maintains the deployment.
2. That person runs the offline G2P tooling (`authoring/build_pack.py` /
   `authoring/augment_spanish_pack.py`, or an equivalent script for a new
   language) to generate the phoneme reference records.
3. Those records are imported into a running jingo deployment (records tree
   under `JINGO_RECORDS_DIR`, see [`docs/DEPLOYMENT.md`](DEPLOYMENT.md)) and
   into ADAPT via the admin-only `libretexts:import-language-pack` artisan
   command (see
   [`adapt-integration/INTEGRATION.md`](../adapt-integration/INTEGRATION.md)).

This works, and it's how the pre-seeded packs in this deployment were built,
but it means instructors cannot add or adjust vocabulary themselves — every
new word is a round trip through someone with shell access to the deployment
and the G2P toolchain.

## Next major feature: Model B — on-demand G2P authoring

The goal is to let an instructor build and edit their own pronunciation word
lists **in ADAPT's UI**, with phoneme references generated on demand instead
of offline.

At a high level this means:

- A G2P service reachable from ADAPT (or from jingo) at authoring time, not
  just at deploy/import time. Today's G2P tooling in `authoring/` runs
  offline as a batch script; Model B turns the same capability into a
  request/response service an instructor-facing UI can call per word or
  per list.
- An authoring UI surface in ADAPT where an instructor types or pastes a word
  list, sees the generated phoneme sequences (with a way to review/correct
  them — G2P output isn't always right for proper nouns, loanwords, or
  irregular pronunciations), and saves the result as a pack scoped to their
  own course/section.
- A storage and import path for instructor-authored packs that doesn't
  require admin/CLI access — today's `libretexts:import-language-pack`
  command stays as the bulk/admin path, but an instructor shouldn't need it
  for their own course-scoped list.
- Versioning/audit for instructor-edited phoneme records, since these feed
  directly into what `jingo_engine` scores against — a bad G2P output that
  goes uncorrected produces a reference an instructor's own students can
  never match.

This is a design and implementation effort of its own (new service surface,
new ADAPT UI, new permission model for who can author packs) and is not yet
built. It is not covered elsewhere in this repository; when work on it
starts, it belongs in its own design doc and its own directory analogous to
`authoring/`, not as a modification to the existing offline G2P scripts.

## Interim workflow (today)

Until Model B ships, the supported way to add or extend vocabulary is the
offline path described above:

```
instructor collects word list
        │
        ▼
offline G2P  (authoring/build_pack.py or augment_*_pack.py)
        │
        ▼
records tree updated (service/records/<lang>/, tag_map/<lang>.json)
        │
        ▼
libretexts:import-language-pack   (admin/CLI, idempotent, safe to re-run)
        │
        ▼
pack usable in ADAPT courses
```

See [`authoring/README.md`](../authoring/README.md) for the offline tooling
itself, and
[`adapt-integration/INTEGRATION.md`](../adapt-integration/INTEGRATION.md#post-apply-wiring-checklist)
for the import step.
