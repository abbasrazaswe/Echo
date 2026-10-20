import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import StylePanel from "./StylePanel";
import ArtifactPanel from "./ArtifactPanel";
import type { ArtifactDetail, StyleRecord } from "./reviewTypes";

const onBusy = vi.fn();
const base = "/profiles/p1";
const settings = {
  enabled: false,
  length: "balanced",
  tone: "neutral",
  punctuation: "standard",
  emoji_usage: "none",
  capitalization: "standard",
  language: "match_user",
  preferred_words: [],
} as const;
const initialStyle = (): StyleRecord => ({
  revision: 0,
  speaker: null,
  conversation_id: null,
  analysis: null,
  analysis_stale: false,
  suggested_settings: null,
  settings: { ...settings, preferred_words: [] },
});
const original = {
  id: "m1",
  speaker: "Sara",
  text: "We can study Python tonight.",
  timestamp: null,
  source_line_start: 2,
  source_line_end: 2,
  conversation_id: "c1",
};
const initialArtifact = (): ArtifactDetail => ({
  id: "a1",
  conversation_id: "c1",
  kind: "summary",
  status: "pending",
  content: "Study Python tonight.",
  generated_content: "Study Python tonight.",
  source_message_ids: ["m1"],
  generated_source_message_ids: ["m1"],
  method: "extractive-rules-v1",
  uncertain: true,
  revision: 1,
  sources: [original],
  generated_sources: [original],
});
let style: StyleRecord;
let artifact: ArtifactDetail;
let conflict = false;
let invalid = false;
let records = 1;
const fetcher = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
  const url = new URL(String(input), "http://localhost");
  const path = url.pathname;
  const body = init?.body ? JSON.parse(init.body as string) : undefined;
  let status = 200;
  let data: unknown;
  if (path.endsWith("/conversations"))
    data = [{ id: "c1", title: "Learning export", message_count: 4 }];
  else if (path.endsWith("/style/analyze")) {
    style = {
      ...style,
      revision: style.revision + 1,
      speaker: body.speaker,
      conversation_id: body.conversation_id ?? null,
      analysis: {
        metrics: {
          message_count: 2,
          mean_words: 6,
          emoji_message_rate: 0,
          terminal_punctuation_rate: 1,
        },
        common_words: [{ word: "Python", occurrences: 2 }],
        common_phrases: [],
        sample_limited: true,
        sample_truncated: false,
      },
      suggested_settings: {
        ...style.settings,
        length: "brief",
        preferred_words: ["Python"],
      },
    };
    data = style;
  } else if (path.endsWith("/style/evaluate"))
    data = {
      revision: style.revision,
      analysis_stale: false,
      checks: { length_band: true },
      preferred_words_present: ["Python"],
      not_evaluated: ["factual_grounding"],
    };
  else if (path.endsWith("/style")) {
    if (init?.method === "PATCH") {
      if (conflict) {
        status = 409;
        style.revision = 4;
        data = { detail: "Style changed elsewhere" };
      } else if (invalid) {
        status = 422;
        data = { detail: "Preferred words must be individual words" };
      } else {
        style = {
          ...style,
          revision: style.revision + 1,
          settings: body.settings,
        };
        data = style;
      }
    } else data = style;
  } else if (path.endsWith("/artifacts/generate"))
    data = { created: 1, refreshed: 2, preserved: 3 };
  else if (path.endsWith("/artifacts/a1")) {
    if (init?.method === "PATCH") {
      if (conflict) {
        status = 409;
        artifact.revision = 3;
        data = { detail: "Artifact was changed" };
      } else if (invalid) {
        status = 422;
        data = {
          detail: "All source IDs must belong to the artifact conversation",
        };
      } else {
        artifact = { ...artifact, ...body, revision: artifact.revision + 1 };
        data = artifact;
      }
    } else data = artifact;
  } else if (path.endsWith("/artifacts")) {
    const offset = Number(url.searchParams.get("offset"));
    data = { items: offset ? [] : [artifact], total: records };
  } else throw new Error(`Unexpected request ${path}`);
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
});
beforeEach(() => {
  style = initialStyle();
  artifact = initialArtifact();
  conflict = false;
  invalid = false;
  records = 1;
  fetcher.mockClear();
  onBusy.mockClear();
  vi.stubGlobal("fetch", fetcher);
});
afterEach(() => vi.unstubAllGlobals());
const writes = (suffix: string) =>
  fetcher.mock.calls.filter(
    ([path, init]) => String(path).endsWith(suffix) && init?.method === "PATCH",
  );
async function openStyle() {
  const user = userEvent.setup();
  render(<StylePanel base={base} onBusy={onBusy} />);
  await screen.findByRole("button", { name: "Save reviewed settings" });
  return user;
}
async function openArtifact() {
  const user = userEvent.setup();
  render(<ArtifactPanel base={base} onBusy={onBusy} />);
  await user.click(
    await screen.findByRole("button", { name: /summary · pending/ }),
  );
  await screen.findByLabelText("Reviewed content");
  return user;
}

test("analysis keeps draft settings, suggestions require copying, and enabling requires a reviewed save", async () => {
  const user = await openStyle();
  await user.selectOptions(screen.getByLabelText("Tone"), "warm");
  await user.type(screen.getByLabelText("Participant name"), "Sara");
  await user.selectOptions(screen.getByLabelText("Analysis scope"), "c1");
  await user.click(screen.getByRole("button", { name: "Analyze writing" }));
  expect(await screen.findByText(/Small sample/)).toBeVisible();
  expect(screen.getByLabelText("Tone")).toHaveValue("warm");
  expect(
    screen.getByLabelText("Enable reviewed style for future replies"),
  ).not.toBeChecked();
  expect(writes("/style")).toHaveLength(0);
  await user.click(
    screen.getByRole("button", { name: "Copy suggestions to draft" }),
  );
  expect(screen.getByLabelText("Reply length")).toHaveValue("brief");
  expect(writes("/style")).toHaveLength(0);
  await user.click(
    screen.getByLabelText("Enable reviewed style for future replies"),
  );
  await user.click(
    screen.getByRole("button", { name: "Save reviewed settings" }),
  );
  expect(
    await screen.findByText(
      "Reviewed style saved and enabled for future model replies.",
    ),
  ).toBeVisible();
  const body = JSON.parse(writes("/style")[0][1]!.body as string);
  expect(body).toMatchObject({
    revision: 1,
    settings: { enabled: true, length: "brief", preferred_words: ["Python"] },
  });
});

test("style conflicts retain draft and block writes until the latest saved settings are reviewed", async () => {
  const user = await openStyle();
  conflict = true;
  await user.selectOptions(screen.getByLabelText("Tone"), "formal");
  await user.click(
    screen.getByRole("button", { name: "Save reviewed settings" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Style changed elsewhere",
  );
  expect(screen.getByLabelText("Tone")).toHaveValue("formal");
  expect(
    screen.getByRole("button", { name: "Save reviewed settings" }),
  ).toBeDisabled();
  expect(writes("/style")).toHaveLength(1);
  conflict = false;
  await user.click(
    screen.getByRole("button", {
      name: "Reload saved settings (discard draft)",
    }),
  );
  await waitFor(() =>
    expect(screen.getByLabelText("Tone")).toHaveValue("neutral"),
  );
  await user.click(
    screen.getByRole("button", { name: "Save reviewed settings" }),
  );
  await waitFor(() => expect(writes("/style")).toHaveLength(2));
  expect(JSON.parse(writes("/style")[1][1]!.body as string).revision).toBe(4);
});

test("style validation keeps preferred-word edits and diagnostics reference saved settings", async () => {
  const user = await openStyle();
  invalid = true;
  await user.type(
    screen.getByLabelText("Preferred words (comma separated)"),
    "not a word",
  );
  await user.click(
    screen.getByRole("button", { name: "Save reviewed settings" }),
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "individual words",
  );
  expect(
    screen.getByLabelText("Preferred words (comma separated)"),
  ).toHaveValue("not a word");
  await user.type(
    screen.getByLabelText("Sample reply"),
    "Study Python tonight.",
  );
  await user.click(screen.getByRole("button", { name: "Check sample" }));
  expect(await screen.findByText("Checks · saved revision 0")).toBeVisible();
  expect(screen.getByText(/do not establish identity/)).toBeVisible();
});

test("source-backed correction sends revision and scoped IDs while retaining original generated evidence", async () => {
  const user = await openArtifact();
  expect(screen.getAllByText(original.text).length).toBe(2);
  await user.clear(screen.getByLabelText("Reviewed content"));
  await user.type(
    screen.getByLabelText("Reviewed content"),
    "Python study was suggested for tonight.",
  );
  await user.click(screen.getByRole("button", { name: "Save correction" }));
  expect(await screen.findByText(/Review saved: corrected/)).toBeVisible();
  expect(JSON.parse(writes("/artifacts/a1")[0][1]!.body as string)).toEqual({
    revision: 1,
    status: "corrected",
    content: "Python study was suggested for tonight.",
    source_message_ids: ["m1"],
  });
  expect(artifact.generated_content).toBe("Study Python tonight.");
});

test("confirmation and rejection send only saved-record status and revision", async () => {
  const user = await openArtifact();
  await user.click(
    screen.getByRole("button", { name: "Confirm saved record" }),
  );
  await screen.findByText(/Review saved: confirmed/);
  await user.click(screen.getByRole("button", { name: "Reject saved record" }));
  await screen.findByText(/Review saved: rejected/);
  expect(
    writes("/artifacts/a1").map((call) => JSON.parse(call[1]!.body as string)),
  ).toEqual([
    { revision: 1, status: "confirmed" },
    { revision: 2, status: "rejected" },
  ]);
});

test("artifact conflicts preserve content and require a deliberate reload before another write", async () => {
  const user = await openArtifact();
  conflict = true;
  await user.type(screen.getByLabelText("Reviewed content"), " Edited");
  await user.click(screen.getByRole("button", { name: "Save correction" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Artifact was changed",
  );
  expect(screen.getByLabelText("Reviewed content")).toHaveValue(
    "Study Python tonight. Edited",
  );
  expect(
    screen.getByRole("button", { name: "Confirm saved record" }),
  ).toBeDisabled();
  conflict = false;
  await user.click(
    screen.getByRole("button", {
      name: "Reload latest record (discard edits)",
    }),
  );
  await waitFor(() =>
    expect(screen.getByLabelText("Reviewed content")).toHaveValue(
      "Study Python tonight.",
    ),
  );
  await user.click(
    screen.getByRole("button", { name: "Confirm saved record" }),
  );
  await waitFor(() => expect(writes("/artifacts/a1")).toHaveLength(2));
  expect(
    JSON.parse(writes("/artifacts/a1")[1][1]!.body as string).revision,
  ).toBe(3);
});

test("invalid source corrections remain editable and do not change saved evidence", async () => {
  const user = await openArtifact();
  invalid = true;
  await user.clear(screen.getByLabelText("Source message IDs (one per line)"));
  await user.type(
    screen.getByLabelText("Source message IDs (one per line)"),
    "another-profile-message",
  );
  await user.click(screen.getByRole("button", { name: "Save correction" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "artifact conversation",
  );
  expect(
    screen.getByLabelText("Source message IDs (one per line)"),
  ).toHaveValue("another-profile-message");
  expect(artifact.source_message_ids).toEqual(["m1"]);
});

test("generation uses conversation scope, reports preserved reviews, and filters reset paging", async () => {
  records = 21;
  const user = userEvent.setup();
  render(<ArtifactPanel base={base} onBusy={onBusy} />);
  await screen.findByRole("button", { name: /summary · pending/ });
  await user.click(screen.getByRole("button", { name: "Next records" }));
  await screen.findByText(/No records in this view/);
  await user.selectOptions(screen.getByLabelText("Conversation scope"), "c1");
  await screen.findByRole("button", { name: /summary · pending/ });
  await user.click(
    screen.getByRole("button", { name: "Generate summaries & references" }),
  );
  expect(await screen.findByText(/3 reviewed records preserved/)).toBeVisible();
  expect(
    fetcher.mock.calls.some(([path]) =>
      String(path).endsWith("/generate?conversation_id=c1"),
    ),
  ).toBe(true);
  await user.selectOptions(screen.getByLabelText("Record kind"), "event");
  await waitFor(() =>
    expect(
      fetcher.mock.calls.some(([path]) =>
        String(path).includes("offset=0&conversation_id=c1&kind=event"),
      ),
    ).toBe(true),
  );
});

test("confirmation is blocked while unsaved edits would otherwise be ignored", async () => {
  const user = await openArtifact();
  await user.type(screen.getByLabelText("Reviewed content"), " New draft");
  expect(
    screen.getByRole("button", { name: "Confirm saved record" }),
  ).toBeDisabled();
  expect(
    screen.getByRole("button", { name: "Reject saved record" }),
  ).toBeDisabled();
  expect(screen.getByRole("button", { name: "Save correction" })).toBeEnabled();
  expect(writes("/artifacts/a1")).toHaveLength(0);
});

test("stale analysis is visible and copying suggestions does not enable an inactive style", async () => {
  style.analysis_stale = true;
  style.suggested_settings = { ...style.settings, enabled: true, tone: "warm" };
  const user = await openStyle();
  expect(screen.getByText(/Analysis is stale after imports/)).toBeVisible();
  await user.click(
    screen.getByRole("button", { name: "Copy suggestions to draft" }),
  );
  expect(screen.getByLabelText("Tone")).toHaveValue("warm");
  expect(
    screen.getByLabelText("Enable reviewed style for future replies"),
  ).not.toBeChecked();
  expect(writes("/style")).toHaveLength(0);
});
