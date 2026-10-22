# ErrorMap — implementation brief for Lovable

## Status and supplied source

This package includes a runnable Python/SQLite implementation and a redesigned static frontend. It is **not a Lovable project export**, and no Lovable project has been created or published. Rebuilding on Lovable requires adapting the Python API to that project's supported server functions and database. Keep the source as the visual and behavioral reference; do not assume uploading the ZIP deploys Python there.

Product: **ErrorMap**, Grade 7 English, by **Assel Amanzholova, School No. 22**. The audience uses English, Kazakh and Russian. Create an elegant, coherent learning product with a real backend, not a decorative dashboard.

## Visual reference and direction

Reproduce `dist/index.html`, `dist/assets/welcome.css`, `dist/assets/welcome.js` as the public landing page reference. Use the role-entry and workspace layouts from `dist/classroom/`. Preserve the wordmark, the six-node English skill map, warm paper surface, ink typography, muted violet accents, and restrained leaf-green success states.

- Primary surface #f8f8f4; ink #252738; violet #6d5acb; pale green #d7ecb7.
- Editorial typography, clear hierarchy, concise copy. Maintain Kazakh Cyrillic glyph support.
- The hero map is an interactive vector diagram. Its six nodes open real rule previews.
- Keep separate learner and teacher entry cards. Their links must have distinct routes.
- Inside the app use a quiet sidebar, compact evidence metrics, and a spacious content area.
- No generated testimonials, fake student counts, unsupported success claims, or random progress numbers. Empty accounts show empty states. Sample diagrams must say “Example”.
- Animation is limited to subtle entrances, map-line movement, hover/focus feedback; respect reduced motion.
- Responsive layouts at 360, 390, 768, 1024 and 1440 CSS pixels, keyboard support and visible focus. Use semantic buttons, accessible labels and adequate text contrast.

## Required routes

`/` public landing; `/student/sign-in`; `/student/join`; `/student/overview`; `/student/map`; `/student/assignments`; `/student/attempt/:id`; `/student/results/:id`; `/teacher/sign-in`; `/teacher/overview`; `/teacher/classes`; `/teacher/questions`; `/teacher/assignments`; `/teacher/results`; `/teacher/settings`.

The supplied HTML implementation uses separate `classroom/student.html` and `classroom/teacher.html` pages. Preserve this clear separation when porting to a router.

## Identity and ownership

Use the platform's real supported authentication. Never implement a password comparison in client JavaScript or use browser storage as an account database. If the selected identity provider requires email at signup, make that distinction explicit: a teacher's optional **report recipient** is separate from the identity provider's login email. Do not pretend class codes themselves authenticate an existing student.

A teacher is provisioned by the administrator/invitation; no public signup can choose an arbitrary teacher role. Students join a class using a revocable, high-entropy class code and create their own account. Enforce the true role and class membership on the server, independently of route/UI selection. A learner cannot read another learner's attempt, result or reflection. Teachers access only their own classes. Protect writes with database ownership policies and authenticated server functions. An authenticated user must never be able to change their own role by updating a public profile field.

## Data model

Profiles (auth ID, name, protected role, class membership, locale); classes (teacher, name, join code); rule metadata; teacher questions; versioned assignment snapshots; attempts (assignment, student, server-owned random option order, answers, submission timestamp, result); immutable result details; optional teacher report address; durable report outbox.

The Python reference in `server/server.py` specifies the endpoint behavior. Migrate its secrets to managed server secrets, never frontend environment variables. For a Supabase implementation, keep answer keys in a server-only table or column path unavailable through student SELECT policies. A public learner-facing question view must omit keys. Restrict security-definer functions to the smallest intended RPC operations; prevent direct client writes to scores or finalized results.

## Question content

Use `dist/assets/question-bank.json`: 240 questions, 24 rules, 6 skill areas, three A/B assessment pairs and four practice examples per rule. Preserve question IDs, rule IDs, correct-answer indices, explanations, difficulty bands and use/form/pair metadata. Do not generate a replacement bank or silently change assessment wording. English exercise text stays English in every locale.

Teachers can search/filter the bank, duplicate any seed question, create their own three-option questions, edit their own questions and archive them. Do not let one teacher edit another teacher's content. Copy snapshots into assignments, so editing a question later cannot alter past grades.

The existing independent-practice bank is publicly readable with keys. It is not a secure examination bank. If exam secrecy is later required, use a new private bank; moving a previously exposed question into a private table does not erase prior exposure.

## Classroom behavior

Teacher: create class → share code → author/select questions → save editable draft → publish → review submissions. Draft editing preserves selected IDs and title; publication freezes content. One submitted attempt per student per assignment. A teacher can create a fresh assignment for another check.

Student: see only published assignments for their class → start or resume → answer → review → submit → receive rule-level feedback. Shuffle options server-side once per attempt and persist that exact order. Autosave must finish successfully before navigation. Reload resumes. Require every answer. Grade only on the server and make submission atomic and idempotent. Never permit a finalized result to be edited by a client.

## Evidence and learning map

Use six groups: verb agreement, verb tenses, words/phrases, prepositions, word order and spelling. Each has four rules. A rule with no submitted answer says “Not assessed”. Summarize the latest submitted evidence for that rule; group by rule within one assessment and use submission time, not assignment creation time, when choosing the latest observation.

Display “Needs review” if the most recent observed answers include an error; otherwise “All correct in latest check”. Do not call one correct answer validated mastery. Show correct/observed counts. Clicking a skill reveals rules, English examples and targeted practice entry points. Teacher overview shows actual roster sizes, published assignments, submissions, weighted accuracy and missed-rule counts. Never render `0%` as a substitute for “no data”.

## Preserve the full independent learning cycle

`workspace.html`, diagnostic, error map, learning path, writing, library, teacher and about pages contain the established separate independent cycle. Its current data is browser-local; it is not automatically synced with classroom accounts. Keep this boundary visible until a real migration is implemented.

For a later full migration preserve: 24-rule baseline with balanced first-cycle bands; missed-rule targeting; four first-answer practice examples per rule; hints count as assistance; mandatory corrections do not overwrite the first answer; reflection completeness check with teacher language review; at least 3/4 independent practice plus reflection unlocks a two-question rule check; 2/2 completes; failed check returns to review; final matched B recheck excludes checkpoint items reserved for that cycle; exposure disclosure and less-used pair rotation; historical cycles. Preserve all existing tests as behavioral references.

## Email reports

Teacher report email is optional and can be added later. Submitting an assignment saves the grade immediately, even with email disabled or the provider unavailable. Insert one durable outbox job keyed by submission ID. A server worker sends score, student, class, assignment, timestamp and answer-level feedback to the teacher's configured recipient. Keep keys and sender credentials server-side. Retries use backoff and stop after a visible failure state; allow the teacher to retry failed jobs. Do not resend successful jobs when settings change. Explain whether previously queued submissions will be sent after an address is added. Show provider acceptance separately from guaranteed inbox delivery. A crash between provider acceptance and status update can create a duplicate unless the provider supports an idempotency key.

## Three languages

Use English / Қазақша / Русский everywhere. Reuse existing `i18n.js`, `translations.json`, `welcome.js`, and classroom dictionaries. Translate interface labels, rule descriptions, loading/errors/empty states and validation messages. Keep questions, answer options and user-authored text unchanged. Persist locale separately from the active attempt. Switching locale must not drop typed signup data, selected questions or answers.

## Acceptance evidence

Verify with two student accounts in different classes and a teacher account:

1. Each student can open only their own class work and attempts.
2. Students cannot obtain private answer keys, edit scores or promote themselves to teacher.
3. A draft can be edited; published content and completed scores remain unchanged after bank edits.
4. The saved option permutation and answer survive reload.
5. Blank submission is rejected; one final submission cannot be overwritten.
6. Empty dashboards show no fabricated accuracy, progress, streaks or counts.
7. An earlier-created assignment submitted later correctly becomes the latest evidence.
8. Email absent/failure does not lose results; retries do not duplicate successful jobs.
9. Mobile layouts have no horizontal overflow, and all three locales preserve input state.
10. The independent practice cycle still passes its existing checks.

Do not claim the site is live, the database is connected, or email delivery is working without a deployed URL and verified behavior.
