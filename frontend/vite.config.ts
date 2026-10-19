import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Keep browser requests on one origin; credentials stay in the Python server.
const proxy = Object.fromEntries(
  ["/profiles", "/chat", "/health"].map((path) => [
    path,
    { target: "http://127.0.0.1:8001" },
  ]),
);
export default defineConfig({
  plugins: [react()],
  server: { host: "127.0.0.1", port: 5173, strictPort: true, proxy },
  preview: { host: "127.0.0.1", proxy },
  test: { environment: "jsdom", setupFiles: ["./src/test-setup.ts"] },
});
