import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, afterEach, expect, test, vi } from "vitest";
import App from "./App";

let revision = 0;
let turns: unknown[] = [];
let failChat = false;
let conflict = false;
let memories = [
  {
    id: "memory1",
    content: "I study at night",
    active: true,
    session_id: "session1",
  },
];
const session = () => ({
  id: "session1",
  title: "Learning chat",
  revision,
  turn_count: turns.length,
  topic: null,
});
const fetchMock = vi.fn(
  async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    let data: unknown;
    let status = 200;
    if (path === "/profiles")
      data = [{ id: "profile1", name: "Learning profile" }];
    else if (path.includes("/sessions?")) data = [session()];
    else if (path.endsWith("/sessions/session1")) data = session();
    else if (path.includes("/turns?"))
      data = { items: turns, total: turns.length };
    else if (path === "/chat") {
      if (failChat) {
        status = 503;
        data = { detail: "No model key configured" };
      } else if (conflict) {
        status = 409;
        revision = 3;
        data = { detail: "Session changed" };
      } else {
        const body = JSON.parse(init!.body as string);
        revision++;
        turns = [
          {
            id: "user1",
            role: "user",
            content: body.message,
            citations: [],
            live_citations: [],
          },
          {
            id: "assistant1",
            role: "assistant",
            content: "Saved locally.",
            status: "memory_saved",
            citations: [],
            live_citations: [{ memory_id: "memory1", quote: body.message }],
          },
        ];
        data = { session_revision: revision };
      }
    } else if (path.includes("/live-memories?"))
      data = { items: memories, total: memories.length };
    else if (path.endsWith("/live-memories/memory1")) {
      memories = [{ ...memories[0], active: false }];
      data = memories[0];
    } else if (path.includes("/messages?")) data = { items: [], total: 0 };
    else if (path.endsWith("/conversations")) data = [];
    else if (path.endsWith("/imports")) {
      data = { id: "import1" };
      status = 201;
    } else if (path.endsWith("/memories/index")) data = { chunks: 2 };
    else {
      throw new Error(`Unexpected request: ${path}`);
    }
    return new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    });
  },
);
beforeEach(() => {
  localStorage.clear();
  revision = 0;
  turns = [];
  failChat = false;
  conflict = false;
  memories = [
    {
      id: "memory1",
      content: "I study at night",
      active: true,
      session_id: "session1",
    },
  ];
  fetchMock.mockClear();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());
async function openChat() {
  const user = userEvent.setup();
  render(<App />);
  await waitFor(() => expect(screen.getByLabelText("Message")).toBeEnabled());
  return user;
}
test("saves explicit memory with session revision, renders persisted sources, and allows retraction", async () => {
  const user = await openChat();
  await user.type(screen.getByLabelText("Message"), "I study at night");
  await user.click(screen.getByLabelText("Save this message as live memory"));
  await user.click(screen.getByRole("button", { name: "Save memory ↑" }));
  expect(await screen.findByText("Saved locally.")).toBeVisible();
  const request = fetchMock.mock.calls.find(([path]) => path === "/chat")!;
  expect(JSON.parse(request[1]!.body as string)).toMatchObject({
    session_revision: 0,
    remember: ["I study at night"],
  });
  await user.click(screen.getByRole("button", { name: /Inspect 1 source/ }));
  expect(screen.getByText("memory1")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Memory" }));
  await user.click(
    await screen.findByRole("button", { name: "Retract memory" }),
  );
  expect(await screen.findByText("Retracted")).toBeVisible();
  expect(localStorage.getItem("echo.session.profile1")).toBe("session1");
  expect(JSON.stringify(localStorage)).not.toContain("I study at night");
});
test("provider failure keeps the draft and creates no optimistic turns", async () => {
  failChat = true;
  const user = await openChat();
  await user.type(screen.getByLabelText("Message"), "When do I study?");
  await user.click(screen.getByRole("button", { name: "Send ↑" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "No model key configured",
  );
  expect(screen.getByLabelText("Message")).toHaveValue("When do I study?");
  expect(turns).toHaveLength(0);
  expect(screen.getByRole("button", { name: "Send ↑" })).toBeEnabled();
});
test("revision conflicts refresh the stored revision before a deliberate retry", async () => {
  conflict = true;
  const user = await openChat();
  await user.type(screen.getByLabelText("Message"), "When do I study?");
  await user.click(screen.getByRole("button", { name: "Send ↑" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Review the refreshed conversation",
  );
  conflict = false;
  await user.click(screen.getByRole("button", { name: "Send ↑" }));
  await screen.findByText("Saved locally.");
  const requests = fetchMock.mock.calls.filter(([path]) => path === "/chat");
  expect(requests).toHaveLength(2);
  expect(JSON.parse(requests[1][1]!.body as string).session_revision).toBe(3);
});

test("imports selected text with explicit date order and surfaces the rebuild step", async () => {
  const user = await openChat();
  await user.click(screen.getByRole("button", { name: "↥ Import transcript" }));
  const file = new File(
    ["14/10/2026, 09:01 - Ali: Study Python"],
    "learning.txt",
    { type: "text/plain" },
  );
  // jsdom has no Blob.text implementation; browsers supply this native method.
  Object.defineProperty(file, "text", {
    value: async () => "14/10/2026, 09:01 - Ali: Study Python",
  });
  await user.upload(screen.getByLabelText("WhatsApp text export"), file);
  await user.selectOptions(screen.getByLabelText("Date order"), "month-first");
  // jsdom reports required file inputs invalid even after userEvent.upload.
  // Dispatch the form submission to exercise Echo's actual File.text/JSON flow.
  fireEvent.submit(
    screen.getByRole("button", { name: "Import transcript" }).closest("form")!,
  );
  await waitFor(() =>
    expect(
      fetchMock.mock.calls.some(([path]) => String(path).endsWith("/imports")),
    ).toBe(true),
  );
  expect(await screen.findByRole("status")).toHaveTextContent(
    "Transcript imported",
  );
  const request = fetchMock.mock.calls.find(([path]) =>
    String(path).endsWith("/imports"),
  )!;
  expect(JSON.parse(request[1]!.body as string)).toEqual({
    title: "learning",
    date_order: "month-first",
    transcript: "14/10/2026, 09:01 - Ali: Study Python",
  });
});

test("browse omits an empty keyword so FastAPI returns all original messages", async () => {
  const user = await openChat();
  await user.click(screen.getByRole("button", { name: "Transcript" }));
  await screen.findByText("No messages found.");
  const request = fetchMock.mock.calls.find(([path]) =>
    String(path).includes("/messages?"),
  )!;
  expect(
    new URL(String(request[0]), "http://localhost").searchParams.has("q"),
  ).toBe(false);
});
