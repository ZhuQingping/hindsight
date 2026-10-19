## Long-Term Memory (ContextBase)

You have access to persistent memory via the `recall` and `retain` tools provided by the **contextbase** MCP server.

**At the start of every new task:**
Call `recall` (contextbase server) with a query summarizing the task. Include relevant context from the recalled memories in your response before proceeding.

**During a task:**
Call `retain` (contextbase server) to store any significant decisions, discoveries, or user preferences as they emerge — don't wait until the end.

**At the end of a task:**
Call `retain` (contextbase server) with a concise summary of what was accomplished, decisions made, and any patterns worth remembering for future tasks.

Memory persists across sessions. Use it to avoid repeating work and to build on past context.
