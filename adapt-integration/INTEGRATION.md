# ADAPT Integration Guide — Pronunciation Question Engine

This directory packages the ADAPT-side changes that wire ADAPT's pronunciation
question type (`technology = 'pronunciation'`) to the jingo pronunciation
scoring service **and** the optional jingo-tts "Hear it" service. It is derived
from **16 committed commits** on `adapt-dev` — the original 10
(`8e198153^..b0adeef4`) plus 5 that add the "Hear it" exemplar button, the
login-free practice embed, and the word-level feedback view
(`bbb9503e`, `33dc2f80`, `91e7d2f1`, `600550a1`, `b5cbfdf4`), plus the
BUILD-05 self-contained embed shell and contrast repair. Patch `0016` was
rebased cleanly onto `b5cbfdf4` as `2dd032f65`; it is the same scoped delta as
the accepted BUILD-05 ADAPT commit `ef8daa55e`, without pulling in unrelated
BUILD-04 registry commits. Every patch is extracted from clean git objects;
no working-tree edits are involved. **Current through `2dd032f65`
(2026-07-13).**

**Note on naming:** `technology = 'pronunciation'`, `PronunciationQuestion.vue`,
and related ADAPT-side identifiers intentionally keep the full word
"pronunciation". Only the standalone jingo *service* (formerly "pron") was
renamed; ADAPT's own question-type token is unchanged and requires no DB
migration beyond the one shipped here.

## Files (14 across 16 patches)

Patches `0001`–`0010` are the original scoring integration; `0011`–`0015` add
the "Hear it" TTS button, the login-free practice embed, and word-level feedback;
`0016` makes the embed shell self-contained and fixes muted-text contrast.

| # | File (ADAPT-relative path) | What changed |
|---|---|---|
| 1 | `app/Console/Commands/LibreTexts/ImportLanguagePack.php` | New artisan command `libretexts:import-language-pack`. Patterned on `libretexts:seed-demo`: builds/loads a course + section graph, imports word-list JSON into `pronunciation_data`, seeds per-course defaults, idempotent against existing sections/enrollments (safe to re-run). Creates `assign_to_timings` + `assign_to_groups` (`group=course`) for every assignment via `ensureAssignmentTiming()` — required, or ADAPT's instructor Assignments view 500s on assignments with no timing. |
| 2 | `tests/Feature/ImportLanguagePackTest.php` | Feature tests for the importer above (idempotency, assessment-type mapping, defaults). |
| 3 | `database/migrations/2026_07_05_000001_add_pronunciation_to_questions.php` | Extends `questions.technology` ENUM to add `'pronunciation'` (preserving existing `h5p/webwork/imathas/qti/text` values) and adds a nullable `pronunciation_data` JSON column. `down()` restores `technology` to `VARCHAR(15)` (its pre-migration type), not to the ENUM without `pronunciation`. |
| 4 | `resources/js/components/questions/PronunciationQuestion.vue` | The core Vue component (patches 0004/0007/0008/0009 + **0011/0012/0013/0015/0016**): custom recorder (auto-stop VAD, explicit submit), `completion`/`score` grading, `preview` prop for the instructor read-only view, **a 🔊 "Hear it" button** (`ttsUrl` prop → jingo-tts `/say`, speaks only the target word via `spokenText()`), a **`mode='practice'`** path (inline `/practice-score`, feedback-only, "Speak again" retry loop), a **word-level feedback view** (colours real words via `wordGroups`; IPA per-phoneme chips under a "Show sounds (IPA)" toggle; flat fallback when the record has no per-word text), and WCAG AA muted-text contrast. |
| 5 | `app/Http/Controllers/JWTController.php` | `processAnswerJWT()` whitelist (`$problemJWT->adapt->technology`) extended to accept `'pronunciation'` alongside `'webwork'`/`'imathas'`, so the jingo service's signed answer callback is no longer rejected. |
| 6 | `app/Http/Controllers/AssignmentSyncQuestionController.php` | Question-sync path updated to carry `pronunciation_data` / `pronunciation_problem_jwt` fields through when syncing assignment questions. |
| 7 | `app/Question.php` | Model: `pronunciation_data` added to fillable/casts (JSON) so it round-trips through Eloquent. |
| 8 | `app/Submission.php` | Model: handles pronunciation submission shape (audio upload + score payload) alongside existing webwork/imathas submission handling. |
| 9 | `resources/js/pages/questions.view.vue` | Renders `<pronunciation-question>` when `technology === 'pronunciation'`; passes `problem-jwt`, `exercise-id`, `language`, `grading` (from `pronunciation_data`), `service-url` (`window.config.pronunciationServiceUrl`) and **`tts-url`** (`window.config.pronunciationTtsUrl`); handles `@scored`. Also renders the recorder for instructors (`user.role === 2`) with `:preview` + a banner. |
| 10 | `package.json` | Adds `lamejs` (`^1.2.0`, MP3 encoding for the recorder) and `vue-audio-recorder` (`^3.0.1`) as dependencies. |
| 11 | `resources/js/pages/pronunciation.embed.vue` **(new)** | Anonymous, login-free page (`layout: 'blank'`) that renders `<pronunciation-question mode="practice">` from URL params (`exercise_id`, `lang`, `prompt`) — the target of the `/embed/pronunciation` iframe used to embed ungraded practice in any page. Also posts its content height to the parent (`postMessage` `pron-embed-height`) so the host can auto-size the iframe, and hides the support widget. |
| 12 | `config/myconfig.php` | Adds `pronunciation_tts_url` (from env `PRONUNCIATION_TTS_URL`) alongside the existing `pronunciation_service_url`. (Small edit — see patch `0011`; not snapshotted whole to avoid carrying unrelated config.) |
| 13 | `resources/views/spa.blade.php` | Exposes the TTS URL to the SPA as `window.config.pronunciationTtsUrl` (patch `0011`). Patch `0016` detects `/embed/pronunciation` and omits unrelated iframe-resizer, support-widget, and MathJax CDN scripts from that shell. These are small edits and the shared template is not snapshotted whole. |
| 14 | `tests/Feature/PronunciationEmbedShellTest.php` | Proves the anonymous pronunciation embed returns the local SPA CSS/JS while omitting `cdnjs.cloudflare.com` and `cdn.libretexts.net`. |

## Apply path A — git am (preferred, preserves commit history)

```bash
cd /path/to/your/adapt/checkout
git am /path/to/adapt-jingo/adapt-integration/patches/*.patch
```

Applies all 16 commits in order, each with its original message and
`Co-Authored-By` trailer where present. Patches `0001`–`0015` were verified
2026-07-10 after the series was regenerated by
cherry-picking the 5 new pronunciation commits onto `b0adeef4` in an isolated
worktree; the resulting tree matches fork `main` (`b5cbfdf4`) byte-for-byte on
all five touched files. Patches `0001`–`0010` are the scoring integration;
`0011`–`0015` add Hear-it / practice-embed / word-level. Patch `0016` adds the
accepted BUILD-05 embed-shell repair on that exact clean base.

**Reverified 2026-07-13:** `git am patches/*.patch` applied all 16 commits in
order onto `8e198153^` in a disposable isolated worktree with zero conflicts.
`git diff --check` passed; all 12 copy-in snapshots byte-match the resulting
tree; and patch `0016`'s added lines exactly match accepted BUILD-05 commit
`ef8daa55e`.

Caveat: a plain bulk `git apply --check patches/*.patch` (checking all 10
files as one batch, not sequentially) reports false "No such file or
directory" errors on later patches, because bulk `apply --check` isn't
sequential-state-aware — earlier patches in the same invocation aren't
considered "applied" when checking later ones. This is a checking artifact,
not a real conflict. Applying one at a time, or via `git am` (which is
sequential by design), applies cleanly. If your target tree has diverged
from `8e198153^` (e.g. later ADAPT upstream changes touched the same files),
use `git am -3` for a 3-way merge instead of plain `git am`.

## Apply path B — hand-merge from files/

If you can't use `git am` (e.g. your ADAPT fork has diverged too far, or
you only want a subset), copy the file contents from `files/<path>` into
the same path in your ADAPT checkout, then diff against your local version
to reconcile any unrelated local changes before overwriting. `files/`
contains clean snapshots as of `2dd032f65` for the pronunciation-specific whole
files (`PronunciationQuestion.vue`, `questions.view.vue`, `pronunciation.embed.vue`,
the two feature tests, and the original scoring files); the small shared-file
edits (`config/myconfig.php`, `resources/views/spa.blade.php`) are **not**
snapshotted whole — take them from patches `0011` and `0016` so you do not carry
unrelated configuration or template changes.

## Post-apply wiring checklist

- [ ] **Rendering:** confirm `resources/js/pages/questions.view.vue` renders
      `<pronunciation-question>` when `technology === 'pronunciation'`
      (see file #9 above) — this is the SPA entry point for the question type.
- [ ] **JWT whitelist:** confirm `app/Http/Controllers/JWTController.php`'s
      `processAnswerJWT()` whitelist includes `'pronunciation'` in the
      allowed `$problemJWT->adapt->technology` values, so signed answer
      callbacks from the jingo service aren't rejected.
- [ ] **JS deps:** run `npm i` (picks up `lamejs` + `vue-audio-recorder`
      from `package.json`) and rebuild the SPA bundle.
- [ ] **Migration:** run `php artisan migrate` to apply
      `2026_07_05_000001_add_pronunciation_to_questions.php` (extends
      `technology` ENUM, adds `pronunciation_data` column).
- [ ] **Word-list import:** run
      `php artisan libretexts:import-language-pack` (admin/CLI-only step —
      there is no instructor-facing import UI) to load a word pack into a
      course.
- [ ] **Service wiring:** set the jingo scoring service's base URL
      (exposed to the SPA as `window.config.pronunciationServiceUrl`) and a
      shared `WEBWORK_JWT_SECRET` on both ADAPT and the jingo service — this
      is the HMAC secret used to sign/verify the problem/answer JWTs
      exchanged between them. **Do not commit the actual secret value** —
      set it via each environment's own `.env` / secrets store.
- [ ] **"Hear it" TTS (optional):** deploy the jingo-tts service (`tts/`) and
      set `PRONUNCIATION_TTS_URL` in ADAPT's `.env` (surfaced to the SPA as
      `window.config.pronunciationTtsUrl` via patch `0011`). Empty/unset = the
      button is simply hidden; scoring still works without it.
- [ ] **Practice embed (optional):** `pronunciation.embed.vue` renders at
      `/embed/pronunciation?exercise_id=…&lang=…&prompt=…` (client-side SPA
      route, `layout: 'blank'`). To embed ungraded practice in another page,
      iframe that URL with **`allow="microphone"`** (the real constraint — the
      iframe needs mic permission; no ADAPT login is required, it hits the
      jingo `/practice-score` endpoint). The host page can listen for the
      `postMessage` `pron-embed-height` to auto-size the iframe. Patch `0016`
      keeps this route on local SPA assets and omits the global support,
      iframe-resizer, and MathJax CDN scripts from the embed shell.

## What this bundle does NOT include

- Model weights (`facebook/wav2vec2-xlsr-53-espeak-cv-ft`, Apache-2.0) —
  fetched by the jingo service's own downloader at deploy time.
- The jingo scoring service itself (separate repo/deploy).
- Any secret values (JWT secret, service URLs, credentials).
