# Echo web workspace

This checkpoint turns the existing API into a browser application using React,
TypeScript, and Vite. It uses the real backend; there is no production demo mode
or simulated assistant. Network responses are mocked only in tests.

## Run it

Use Node.js 22.12 or newer (Node 24 was used for verification).
Start FastAPI in one terminal:

```sh
cd backend
source .venv/bin/activate
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001
```

In a second terminal, from the repository root:

```sh
cd frontend
npm ci
npm run dev
```

Open <http://127.0.0.1:5173/>. Both servers must be running. The Vite proxy
forwards `/profiles`, `/chat`, and `/health` to port 8001. Keep these servers
bound to loopback: authentication and remote deployment are later checkpoints.

```sh
npm test         # UI and client regressions with mocked fetch
npm run build    # TypeScript validation + optimized dist assets
npm run preview  # Preview the build locally; backend still required
npm run format   # Format source/configuration
```

The build is not served by FastAPI automatically. Preview uses Vite's local
proxy; a remote deployment will need its own serving/proxy arrangement.
No frontend environment file or API key is required. Do not put secrets in
browser code or `VITE_*` variables.

## Learn the flow

1. **App.tsx** loads the profile list and lets you create/select a profile.
   React state holds what is currently visible. Only selected IDs go into
   localStorage; chat text and transcript files do not.
2. **Workspace.tsx** loads sessions and their stored turns. Sending a message
   includes the session's current revision. Python decides whether to answer,
   decline for lack of evidence, or save an explicitly selected statement.
   After success, the UI reloads stored turns rather than inventing a reply.
3. **api.ts** gives the components typed JSON requests and readable errors.
   A 409 session conflict refreshes the conversation before a deliberate retry;
   there is no automatic chat resubmission. Provider errors keep the draft.
   Turn/session/memory pagination retrieves older records too.
4. **Tools.tsx** contains the import, transcript, and memory panels. `File.text()`
   reads the chosen `.txt` export in the browser, then posts its contents to the
   existing JSON import route. Select the date order explicitly. The client caps
   files at 8 MB and text at 2,000,000 characters; the server validates again.
5. **styles.css** defines the responsive layout and keyboard focus states.
   At narrower widths, the inspection panel moves below chat. No styling or
   component library is needed for this checkpoint.

The useful distinction: **state is the current screen; SQLite is the saved
record**. Reloading the page reconstructs the screen from the API. Profile
workspaces are keyed by ID so changing profile clears the previous screen's
state. Read effects cancel requests when their selection changes.

## Try it without a model key

Create a profile and a new chat. Type “I prefer studying in the evening”, select
**Save this message as live memory**, and save. This explicit action stores the
exact statement locally and does not call the model. Open **Memory** to retract
it; retraction stops future use as evidence but preserves earlier chat turns.
Reload to check persistence.

Import `../backend/tests/fixtures/whatsapp_sample.txt` into a tutorial profile
using day-first dates. It contains fictional messages. Click **Build search
index**; the first nonempty build may download the local embedding model.
Open **Transcript** and search for `functions`. Rebuild after new imports.

Normal grounded answers require the server's model configuration. With no key,
an evidence-backed question produces a clear error and retains your draft.
Questions with no supporting evidence may receive the backend's fixed
uncertainty reply without a provider call. Mocked-provider testing remains the
chosen approach for now.

## Evidence and limits

**Inspect sources** displays the saved exact quotes and IDs from a reply,
labelled as imported message or live memory. It does not display the whole
surrounding transcript or treat a quote as a guarantee of factual correctness.
Saved quotes describe the evidence at reply time; memories may later be retracted.

Eighteen tests cover explicit memory requests, stored-turn display, source quotes,
retraction, provider failure drafts, conflict revisions, file-to-JSON submission,
browsing without an empty query, error normalization, and multi-page evidence.
Review tests additionally cover explicit style enablement, retained drafts, stale
analysis, diagnostics, generation scope, artifact filtering/paging, source-backed
corrections, confirm/reject payloads, conflicts, invalid source IDs, and unsaved
correction guards.
They use jsdom and mocked fetch. The native file-picker round trip remains
unverified by browser automation because its chooser timed out. File reading
and submission are covered in the component test (jsdom requires dispatching
submit because its required-file validation does not recognize the uploaded file).

Real local browser checks covered profile/session creation, memory save and
retraction, reload persistence, transcript browsing/search, and index rebuild.
The fictional import was submitted separately over HTTP. Responsive checks at
390 and 1440 px found no horizontal overflow; no browser errors were reported.
No hosted model call was made.

## Reviewed style and derived records

Open **Style** to load the saved settings and a separate editable draft.
Analyze a participant using their exact imported label (e.g. `Sara`) and an
optional conversation scope. Analysis writes a new revision with metrics and
suggestions. It does not enable style or replace the draft. Small/truncated
samples and stale analyses are labelled. Review the measured words/phrases and
copy the suggestions to the draft only if useful. Copying preserves the draft's
current enable switch; it never enables style for you.

Edit length, tone, punctuation, emoji use, capitalization, language, and preferred
words. Select **Enable reviewed style for future replies** explicitly and save.
Preferred words must be individual words (maximum 10), not instructions. You can
configure style manually without any imported transcript. **Check sample** makes
local checks against the saved revision; unsaved changes are excluded. It neither
stores the sample nor calls a model, and does not establish identity or accuracy.

Open **Review** to generate extractive summaries, participant labels, candidate
topics, and candidate events. Conversation scope controls generation and browsing;
kind/status filters and pagination control the list. Generating again refreshes
pending records but preserves records already reviewed. No model is needed.

Select a record and read the current linked messages, including source lines and
IDs. Expand the original generated record to compare it with a correction. You
can confirm or reject the saved record, or edit its text and source IDs then save
a correction. The source IDs must belong to the same conversation (1–100 IDs,
validated by the server). Copy message IDs exactly, one per line; full record
inspection is also available in the API docs. Confirm/reject are disabled when
corrections are unsaved, so edits cannot be silently ignored.

`StylePanel.tsx` and `ArtifactPanel.tsx` keep the loaded revision beside the draft.
`reviewTypes.ts` describes the existing API data. A stale write returns 409: edits
stay visible, writes stop, and a clearly labelled reload button lets you discard
local edits and load the latest saved record. There is no automatic retry or
silent merge. Leaving a panel discards its unsaved draft. Navigation/profile
switches are disabled during review mutations; chat refreshes do not remount an
open review panel.

The lesson is the same as in chat: **the draft is editable screen state; saving
creates a reviewed database revision**. An original message, an extractive
candidate, and a reviewed correction remain distinct records. Source messages
are never rewritten to match a style or correction.

Direct HTTP smoke checks with a fictional transcript verified the real style
analysis/save/evaluate and artifact generation/inspect/correction APIs, including
stale-revision errors and preservation of reviewed records. The 18 component/client
tests use mocked fetch. Browser automation for these new panels was blocked by
the browser tool's URL security policy, so their visual/browser QA remains
unverified. Earlier browser checks above apply to the previous workspace checkpoint.
No hosted model was called.

**Next learning step:** authentication, logging, backups/deletion documentation,
and reproducible local/remote operation before exposing the app beyond loopback.
