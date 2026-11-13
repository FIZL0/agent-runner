// agent-runner's Stop hook for Pi (loaded with -e): end the session once it has sat at its prompt, all work
// settled, for --runner-idle seconds. A new run, a submitted message, or text left in the editor keeps it
// open, so a human can take a slot over by typing.
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.registerFlag("runner-idle", { description: "agent-runner: seconds idle before exiting", type: "string" });
  let timer: ReturnType<typeof setTimeout> | undefined;
  const cancel = () => { if (timer) clearTimeout(timer); timer = undefined; };
  pi.on("agent_start", cancel);
  pi.on("input", async () => { cancel(); });
  pi.on("session_shutdown", cancel);
  pi.on("agent_settled", async (_event, ctx) => {
    cancel();
    const idle = Number(pi.getFlag("runner-idle") || 90) * 1000;
    const check = () => {
      if (ctx.hasUI && ctx.ui.getEditorText().trim()) timer = setTimeout(check, idle); // someone is typing
      else ctx.shutdown();
    };
    timer = setTimeout(check, idle);
  });
}
