# ADAPT Integration Guide — Pronunciation Question Engine

This directory packages the ADAPT-side changes that wire ADAPT's pronunciation
question type (`technology = 'pronunciation'`) to the jingo pronunciation
scoring service. It is derived from 8 committed commits on `adapt-dev`
(range `8e198153^..ee9478b0`), extracted from clean git objects — no
working-tree edits are involved.

**Note on naming:** `technology = 'pronunciation'`, `PronunciationQuestion.vue`,
and related ADAPT-side identifiers intentionally keep the full word
"pronunciation". Only the standalone jingo *service* (formerly "pron") was
renamed; ADAPT's own question-type token is unchanged and requires no DB
migration beyond the one shipped here.

## Files (10)

| # | File (ADAPT-relative path) | What changed |
|---|---|---|
| 1 | `app/Console/Commands/LibreTexts/ImportLanguagePack.php` | New artisan command `libretexts:import-language-pack`. Patterned on `libretexts:seed-demo`: builds/loads a course + section graph, imports word-list JSON into `pronunciation_data`, seeds per-course defaults, idempotent against existing sections/enrollments (safe to re-run). |
| 2 | `tests/Feature/ImportLanguagePackTest.php` | Feature tests for the importer above (idempotency, assessment-type mapping, defaults). |
| 3 | `database/migrations/2026_07_05_000001_add_pronunciation_to_questions.php` | Extends `questions.technology` ENUM to add `'pronunciation'` (preserving existing `h5p/webwork/imathas/qti/text` values) and adds a nullable `pronunciation_data` JSON column. `down()` restores `technology` to `VARCHAR(15)` (its pre-migration type), not to the ENUM without `pronunciation`. |
| 4 | `resources/js/components/questions/PronunciationQuestion.vue` | New Vue component: custom recorder (auto-stop VAD, explicit submit), per-phoneme score-chip breakdown with learner-friendly labels, `completion`/`score` grading modes, emits `scored`. |
| 5 | `app/Http/Controllers/JWTController.php` | `processAnswerJWT()` whitelist (`$problemJWT->adapt->technology`) extended to accept `'pronunciation'` alongside `'webwork'`/`'imathas'`, so the jingo service's signed answer callback is no longer rejected. |
| 6 | `app/Http/Controllers/AssignmentSyncQuestionController.php` | Question-sync path updated to carry `pronunciation_data` / `pronunciation_problem_jwt` fields through when syncing assignment questions. |
| 7 | `app/Question.php` | Model: `pronunciation_data` added to fillable/casts (JSON) so it round-trips through Eloquent. |
| 8 | `app/Submission.php` | Model: handles pronunciation submission shape (audio upload + score payload) alongside existing webwork/imathas submission handling. |
| 9 | `resources/js/pages/questions.view.vue` | Renders `<pronunciation-question>` when `questions[currentPage-1].technology === 'pronunciation'`; passes `problem-jwt`, `exercise-id`, `language`, `grading` (parsed from `pronunciation_data`), and `service-url` (`window.config.pronunciationServiceUrl`); handles the `@scored="submittedPronunciation"` event. |
| 10 | `package.json` | Adds `lamejs` (`^1.2.0`, MP3 encoding for the recorder) and `vue-audio-recorder` (`^3.0.1`) as dependencies. |

## Apply path A — git am (preferred, preserves commit history)

```bash
cd /path/to/your/adapt/checkout
git am /path/to/adapt-jingo/adapt-integration/patches/*.patch
```

Applies all 8 commits in order, each with its original message and
`Co-Authored-By` trailer. **Verified 2026-07-07:** applies cleanly via
`git am` onto `8e198153^` in an isolated worktree — 0 conflicts, exit 0.

Caveat: a plain bulk `git apply --check patches/*.patch` (checking all 8
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
contains clean snapshots of the 10 files as of `ee9478b0` (branch tip) —
not diffs.

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

## What this bundle does NOT include

- Model weights (`facebook/wav2vec2-xlsr-53-espeak-cv-ft`, Apache-2.0) —
  fetched by the jingo service's own downloader at deploy time.
- The jingo scoring service itself (separate repo/deploy).
- Any secret values (JWT secret, service URLs, credentials).
