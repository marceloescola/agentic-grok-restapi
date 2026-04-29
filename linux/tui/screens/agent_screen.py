from __future__ import annotations

from typing import Any, Dict, List

from textual.app import ComposeResult
from textual.containers import Horizontal, ScrollableContainer
from textual.screen import Screen
from textual.widgets import (
    Button,
    Header,
    Footer,
    Input,
    Label,
    RichLog,
    Static,
    Checkbox,
)


class AgentScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield ScrollableContainer(
            Label("Agent Mode — Tool-Calling Interface", classes="section-title"),
            Input(
                id="agent-prompt",
                placeholder="Enter your agent prompt...",
            ),
            Label("Tools:", classes="label"),
            Checkbox("Calculator", id="tool-calculator", value=True),
            Checkbox("Web Search", id="tool-web_search", value=True),
            Checkbox("File Read", id="tool-file_read", value=True),
            Horizontal(
                Label("Max Steps:", classes="label"),
                Input(id="max-steps", value="10"),
                classes="horizontal",
            ),
            Horizontal(
                Button("Run Agent", id="run-btn", variant="primary"),
                Button("Back", id="back-btn"),
                classes="horizontal",
            ),
            RichLog(id="agent-output", highlight=True, wrap=True, markup=True),
            Static(id="agent-status"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#agent-output", RichLog).write(
            "[bold cyan]Agent ready[/bold cyan]\n"
        )

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "back-btn":
            self.app.pop_screen()
        elif event.button.id == "run-btn":
            await self._run_agent()

    async def _run_agent(self) -> None:
        prompt = self.query_one("#agent-prompt", Input).value.strip()
        if not prompt:
            self.query_one("#agent-status", Static).update(
                "[red]Prompt is required[/red]"
            )
            return

        tools: List[str] = []
        for name in ["calculator", "web_search", "file_read"]:
            cb = self.query_one(f"#tool-{name}", Checkbox)
            if cb.value:
                tools.append(name)

        max_steps_input = self.query_one("#max-steps", Input)
        try:
            max_steps = int(max_steps_input.value or "10")
        except ValueError:
            max_steps = 10

        out = self.query_one("#agent-output", RichLog)
        status = self.query_one("#agent-status", Static)
        run_btn = self.query_one("#run-btn", Button)

        out.write(
            f"\n[bold yellow]Running agent:[/bold yellow] {prompt[:80]}..."
        )
        out.write(
            f"[dim]Tools: {tools or 'all available'} | "
            f"Max steps: {max_steps}[/dim]\n"
        )
        status.update("[yellow]Agent running...[/yellow]")
        run_btn.disabled = True

        try:
            result: Dict[str, Any] = await self.app.client.agent(
                prompt=prompt,
                timeout=self.app.config.get("agent_timeout", 120),
                tools=tools if tools else None,
                max_steps=max_steps,
            )

            resp_status = result.get("status", "error")
            response = result.get("response", "")
            agent_steps = result.get("steps", [])
            step_count = result.get("step_count", 0)

            out.write(
                f"\n[bold]Status:[/bold] {resp_status} | "
                f"Steps: {step_count}"
            )

            if agent_steps:
                out.write("\n[bold underline]Tool Calls:[/bold underline]")
                for s in agent_steps:
                    step_num = s.get("step", "?")
                    tool_name = s.get("tool", "?")
                    args = s.get("args", {})
                    tool_result = s.get("result", "")
                    out.write(
                        f"\n[bold cyan]Step {step_num}:[/bold cyan] "
                        f"[green]{tool_name}[/green]"
                    )
                    out.write(f"  Args: {args}")
                    preview = tool_result[:200]
                    if len(tool_result) > 200:
                        preview += "..."
                    out.write(f"  Result: {preview}")

            if response:
                out.write(
                    f"\n[bold green]Final Response:[/bold green]\n{response}"
                )

            status.update(f"[green]Agent finished[/green] ({resp_status})")

        except Exception as e:
            out.write(f"\n[bold red]Agent error:[/bold red] {e}")
            status.update("[red]Agent failed[/red]")
        finally:
            run_btn.disabled = False
