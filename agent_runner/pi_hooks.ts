// agent-runner's bridge from a repo's Claude Code PreToolUse hooks to Pi (loaded with -e): a repo's guards
// (.claude/settings.json, then settings.local.json) hold in a Pi slot too. Each hook whose matcher names the
// tool gets Claude's hook JSON on stdin; exit 2 or a "deny" decision blocks the call with the hook's reason,
// and an updatedInput's command replaces the call's command. Other events (Stop, PostToolUse) aren't bridged.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { spawnSync } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

const CLAUDE_NAME: Record<string, string> = { bash: "Bash", read: "Read", edit: "Edit", write: "Write" };

function hooks(root: string): { matcher?: string; command: string }[] {
  const found: { matcher?: string; command: string }[] = [];
  for (const file of ["settings.json", "settings.local.json"]) {
    const path = join(root, ".claude", file);
    if (!existsSync(path)) continue;
    try {
      for (const entry of JSON.parse(readFileSync(path, "utf8"))?.hooks?.PreToolUse ?? [])
        for (const h of entry.hooks ?? [])
          if (h.type === "command" && h.command) found.push({ matcher: entry.matcher, command: h.command });
    } catch { /* a broken settings file guards nothing, as in Claude Code */ }
  }
  return found;
}

export default function (pi: ExtensionAPI) {
  const root = process.cwd();
  const list = hooks(root);
  if (!list.length) return;
  pi.on("tool_call", async (event) => {
    const tool = CLAUDE_NAME[event.toolName] ?? event.toolName;
    const input: Record<string, unknown> = { ...(event.input as Record<string, unknown>) };
    if (typeof input.path === "string") input.file_path = input.path; // Pi's read/edit/write say path
    for (const h of list) {
      if (h.matcher && !new RegExp(`^(?:${h.matcher})$`).test(tool)) continue;
      const r = spawnSync("sh", ["-c", h.command], {
        cwd: root,
        env: { ...process.env, CLAUDE_PROJECT_DIR: root },
        input: JSON.stringify({ hook_event_name: "PreToolUse", tool_name: tool, tool_input: input, cwd: root }),
        encoding: "utf8",
        timeout: 60_000,
      });
      if (r.status === 2) return { block: true, reason: (r.stderr || "blocked by a PreToolUse hook").trim() };
      let out: any;
      try { out = JSON.parse(r.stdout || "null")?.hookSpecificOutput; } catch { continue; }
      if (out?.permissionDecision === "deny")
        return { block: true, reason: out.permissionDecisionReason || "blocked by a PreToolUse hook" };
      const command = out?.updatedInput?.command; // timeouts are Claude's (ms) and Pi's bash has none by default
      if (typeof command === "string" && "command" in (event.input as object))
        (event.input as Record<string, unknown>).command = command;
    }
  });
}
