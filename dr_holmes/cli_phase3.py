"""
Dr. Holmes CLI — Phase 3 multi-agent diagnostic deliberation.
Run: python3 -m dr_holmes.cli_phase3 [--mock --case <fixture.json>]

NOT FOR CLINICAL USE. AI simulation only.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich.align import Align

from dr_holmes.schemas.responses import (
    AgentResponse, Differential, TestProposal, Challenge,
    CaddickSynthesis, HauserDissent, FinalReport,
)

# ── Agent color palette ────────────────────────────────────────────────────
AGENT_COLORS: dict[str, str] = {
    "Hauser":  "bright_red",
    "Forman":  "blue",
    "Carmen":  "green",
    "Chen":    "cyan",
    "Wills":   "yellow",
    "Caddick": "magenta",
}
DOCTOR_STYLE = "bold white"


def _agent_color(name: str) -> str:
    return AGENT_COLORS.get(name, "white")


# ── Probability bar helpers ────────────────────────────────────────────────

def _prob_color(p: float) -> str:
    if p <= 0.3:
        return "red"
    if p < 0.7:
        return "yellow"
    return "green"


def _prob_bar(p: float, width: int = 14) -> Text:
    p = max(0.0, min(1.0, float(p)))
    filled = int(round(p * width))
    empty = width - filled
    color = _prob_color(p)
    bar = Text()
    bar.append("█" * filled, style=color)
    bar.append("░" * empty, style="dim")
    return bar


# ── Renderers ──────────────────────────────────────────────────────────────

def render_disclaimer_banner(console: Console) -> None:
    """Big yellow Panel: 'NOT FOR CLINICAL USE — AI simulation only'."""
    body = Text()
    body.append("NOT FOR CLINICAL USE — AI simulation only\n", style="bold yellow")
    body.append("\n")
    body.append("Dr. Holmes Phase 3 — six-agent diagnostic deliberation.\n", style="white")
    body.append("Hauser • Forman • Carmen • Chen • Wills • Caddick (moderator)\n", style="dim")
    body.append("No real patient data. No clinical decisions. Educational only.", style="dim italic")
    console.print(Panel(
        Align.center(body),
        border_style="bold yellow",
        title="[bold yellow]⚠  DISCLAIMER  ⚠[/bold yellow]",
        padding=(1, 4),
    ))


def render_round_header(console: Console, round_n: int) -> None:
    """Print: ═══ ROUND 3 ═══ in bold white centered."""
    console.print()
    console.print(Rule(f"[bold white]═══ ROUND {round_n} ═══[/bold white]", style="white"))
    console.print()


def render_caddick_routing(console: Console, next_speakers: list[str], reason: str) -> None:
    """[Caddick → calling on Carmen, Wills] (reason: challenge_response) — magenta dim."""
    speakers = ", ".join(next_speakers) if next_speakers else "(none)"
    console.print(
        f"[magenta dim][Caddick → calling on {speakers}] "
        f"(reason: {reason or 'n/a'})[/magenta dim]"
    )


def render_agent_response(console: Console, response: AgentResponse) -> None:
    """Block layout for a single agent turn."""
    color = _agent_color(response.agent_name)
    name = f"Dr. {response.agent_name}"

    # Header bar
    header = Text()
    header.append("── ", style=color)
    header.append(name, style=f"bold {color}")
    header.append(f"  ──── (turn {response.turn_number})", style=color)
    console.print(header)

    # Reasoning
    if response.reasoning:
        console.print(Text(response.reasoning, style="dim italic"))

    # Differentials
    if response.differentials:
        console.print(Text("  Differentials:", style=f"{color}"))
        for d in response.differentials:
            line = Text("    • ")
            line.append(f"{d.diagnosis:<20}", style="white")
            line.append(" [")
            line.append_text(_prob_bar(d.probability))
            line.append("] ")
            line.append(f"{int(round(d.probability*100))}%", style=_prob_color(d.probability))
            if d.rationale:
                snippet = d.rationale[:50] + ("…" if len(d.rationale) > 50 else "")
                line.append(f"  {snippet}", style="dim")
            console.print(line)

    # Proposed tests
    if response.proposed_tests:
        console.print(Text("  Proposed tests:", style=f"{color}"))
        for t in response.proposed_tests:
            tline = Text(f"    → {t.test_name:<22}", style=f"dim italic {color}")
            if t.rules_in:
                tline.append(f" rules_in: {', '.join(t.rules_in)}", style="dim")
            if t.rules_out:
                tline.append(f"  rules_out: {', '.join(t.rules_out)}", style="dim")
            console.print(tline)

    # Challenges
    if response.challenges:
        console.print(Text("  Challenges:", style=f"{color}"))
        for c in response.challenges:
            cline = Text("    ⚡ → ", style="bright_red bold")
            cline.append(f"{c.target_agent}", style=f"bold {_agent_color(c.target_agent)}")
            cline.append(f": '{c.content}'", style="white")
            console.print(cline)

    # Footer
    footer = Text()
    footer.append(f"  Confidence: {response.confidence:.2f}", style=color)
    footer.append("  | ", style="dim")
    footer.append(f"request_floor: {str(response.request_floor).lower()}", style="dim")
    if response.force_speak:
        footer.append("  | force_speak: true", style="bold bright_red")
    console.print(footer)
    console.print()


def render_differential_dashboard(
    console: Console,
    differentials: list[Differential],
    top_n: int = 5,
) -> None:
    """Live team-level differential dashboard."""
    if not differentials:
        console.print("[dim]  (no differentials yet)[/dim]")
        return

    sorted_dx = sorted(differentials, key=lambda d: d.probability, reverse=True)[:top_n]

    table = Table(
        title="[bold magenta]TEAM DIFFERENTIAL[/bold magenta]",
        show_header=True,
        header_style="bold magenta",
        box=None,
        padding=(0, 1),
    )
    table.add_column("Diagnosis", style="white", min_width=22)
    table.add_column("Bar", min_width=16)
    table.add_column("Prob", justify="right")
    table.add_column("Rationale", style="dim", min_width=20)

    for d in sorted_dx:
        bar = _prob_bar(d.probability)
        prob_txt = Text(f"{int(round(d.probability*100))}%", style=_prob_color(d.probability))
        rationale = (d.rationale or "")[:48]
        table.add_row(d.diagnosis, bar, prob_txt, rationale)

    console.print(table)


def render_challenge_sidebar(console: Console, active_challenges: list[Challenge]) -> None:
    """Compact panel listing unresolved challenges."""
    if not active_challenges:
        return

    body = Text()
    body.append("⚡ Active challenges:\n", style="bold bright_red")
    for c in active_challenges:
        body.append("  ")
        body.append(f"{c.target_agent}", style=f"bold {_agent_color(c.target_agent)}")
        body.append(" ← ", style="dim")
        # We don't know the source — show challenge_type instead.
        body.append(f"[{c.challenge_type}]", style="dim italic")
        body.append(f": '{c.content}'\n", style="white")

    console.print(Panel(
        body,
        border_style="bright_red",
        title="[bold bright_red]Open Challenges[/bold bright_red]",
        padding=(0, 2),
    ))


def render_final_report(console: Console, report: FinalReport) -> None:
    """Multi-panel final report with prominent Hauser dissent."""
    # Consensus
    consensus = Text()
    consensus.append("▶ CONSENSUS DIAGNOSIS: ", style="bold white")
    consensus.append(f"{report.consensus_dx} ", style="bold green")
    consensus.append(f"({int(round(report.confidence*100))}% confidence)", style="green")
    console.print(Panel(
        consensus,
        border_style="bold green",
        title="[bold green]FINAL REPORT[/bold green]",
        padding=(1, 2),
    ))

    # Hauser dissent — prominent, never collapsed
    if report.hauser_dissent:
        hd = report.hauser_dissent
        dbody = Text()
        dbody.append(f"{hd.hauser_dx} ", style="bold bright_red")
        dbody.append(f"({int(round(hd.hauser_confidence*100))}%)\n\n", style="bright_red")
        dbody.append("Why: ", style="bold yellow")
        dbody.append(f"{hd.rationale}\n", style="white")
        if hd.recommended_test:
            dbody.append("\nRecommended additional test: ", style="bold yellow")
            dbody.append(f"{hd.recommended_test.test_name}", style="white")
            if hd.recommended_test.rationale:
                dbody.append(f" — {hd.recommended_test.rationale}", style="dim")
        console.print(Panel(
            dbody,
            border_style="bold yellow",
            title="⚠ DISSENT FROM DR. HAUSER",
            padding=(1, 2),
        ))

    # Recommended workup
    if report.recommended_workup:
        wtable = Table(
            title="[bold cyan]Recommended Workup[/bold cyan]",
            show_header=False, box=None, padding=(0, 1),
        )
        wtable.add_column("#", style="dim", justify="right")
        wtable.add_column("Test", style="white")
        wtable.add_column("Rationale", style="dim")
        for i, t in enumerate(report.recommended_workup, 1):
            wtable.add_row(str(i), t.test_name, t.rationale or "")
        console.print(wtable)

    # Deliberation summary
    if report.deliberation_summary:
        console.print(Panel(
            Text(report.deliberation_summary, style="white"),
            border_style="dim",
            title="[bold]Deliberation Summary[/bold]",
            padding=(1, 2),
        ))

    # Footer
    footer = Text()
    footer.append(f"Rounds taken: {report.rounds_taken}", style="white")
    footer.append("  |  ", style="dim")
    footer.append(f"Convergence: {report.convergence_reason}", style="cyan")
    console.print(footer)
    console.print()


# ── Mock session orchestration ─────────────────────────────────────────────

def run_mock_session(fixture_path: str, max_rounds: int) -> None:
    """Load fixture, build mock agents, render UI as state machine progresses."""
    console = Console()
    render_disclaimer_banner(console)

    # Load fixture
    fpath = Path(fixture_path)
    if not fpath.exists():
        console.print(f"[bold red]Fixture not found:[/bold red] {fixture_path}")
        sys.exit(1)
    try:
        fixture = json.loads(fpath.read_text())
    except Exception as e:
        console.print(f"[bold red]Failed to parse fixture:[/bold red] {e}")
        sys.exit(1)

    case_id = fixture.get("case_id", fpath.stem)
    console.print(f"[dim]Loaded case: {case_id}[/dim]")
    console.print()

    try:
        from dr_holmes.orchestration.builder import build_phase3_graph, RenderHooks
        from dr_holmes.orchestration.mock_agents import build_mock_agents
        from dr_holmes.schemas.responses import Differential as RenderDifferential

        registry, caddick = build_mock_agents(fixture)

        def _adapt_team_dx(team_dx_list):
            """Convert team-level Differentials (models.core, has .disease)
            into render-compatible Differentials (schemas.responses, has
            .diagnosis + .rationale)."""
            out = []
            for d in team_dx_list:
                rationale = ""
                if d.proposed_by:
                    rationale = f"proposers: {d.proposed_by}"
                out.append(RenderDifferential(
                    diagnosis=d.disease,
                    probability=d.probability,
                    rationale=rationale,
                    supporting_evidence=d.supporting_evidence,
                    contradicting_evidence=d.against_evidence,
                ))
            return out

        # Render hooks fire as the state machine runs
        hooks = RenderHooks(
            on_round_start    = lambda rn: render_round_header(console, rn),
            on_agent_response = lambda r: render_agent_response(console, r),
            on_caddick        = lambda c: render_caddick_routing(
                console, c.get("next_speakers", []), c.get("routing_reason", "")
            ),
            on_team_dx        = lambda dx: render_differential_dashboard(console, _adapt_team_dx(dx)),
            on_final          = lambda f: render_final_report(console, f),
        )

        graph = build_phase3_graph(registry, caddick, hooks)

        initial_state: dict = {
            "case_id": case_id,
            "patient_presentation": fixture.get("patient_presentation", {}),
        }
        graph.invoke(initial_state, config={"recursion_limit": max(80, max_rounds * 12)})

    except ImportError as e:
        console.print(Panel(
            Text(
                "Phase 3 orchestration components are not yet integrated.\n\n"
                f"Missing: {e}\n\n"
                "The CLI is ready — once builder/mock_agents are implemented, "
                "this mock session will run end-to-end.",
                style="white",
            ),
            border_style="yellow",
            title="[bold yellow]Integration Pending[/bold yellow]",
        ))
    except Exception as e:
        console.print(Panel(
            Text(f"Mock session error: {e}", style="red"),
            border_style="red",
            title="[bold red]Error[/bold red]",
        ))


# ── Live session stub ──────────────────────────────────────────────────────

def run_live_session(case_id: str, max_rounds: int) -> None:
    """Live LLM session — stub. Warns and exits if API keys missing."""
    import os
    console = Console()
    render_disclaimer_banner(console)

    missing = []
    if not os.getenv("OPENAI_API_KEY"):
        missing.append("OPENAI_API_KEY")
    if not os.getenv("XAI_API_KEY"):
        missing.append("XAI_API_KEY")

    if missing:
        console.print(Panel(
            Text(
                "Live session requires the following API keys:\n  "
                + "\n  ".join(missing)
                + "\n\nSet them in your environment or .env file, then retry.",
                style="white",
            ),
            border_style="red",
            title="[bold red]Missing API Keys[/bold red]",
        ))
        sys.exit(1)

    console.print(Panel(
        Text(
            f"Live session for case '{case_id}' — not yet implemented.\n"
            f"max_rounds={max_rounds}.\n\n"
            "Agent assignments:\n"
            "  Hauser   = Grok-2 (xAI)\n"
            "  Forman   = GPT-4o (OpenAI)\n"
            "  Caddick  = GPT-4o (OpenAI)\n"
            "  Chen     = GPT-4o-mini (OpenAI)\n"
            "  Carmen   = GPT-4o-mini (OpenAI)\n"
            "  Wills    = GPT-4o-mini (OpenAI)",
            style="white",
        ),
        border_style="cyan",
        title="[bold cyan]Live Session (stub)[/bold cyan]",
    ))


# ── Entrypoint ─────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dr_holmes.cli_phase3",
        description="Dr. Holmes Phase 3 — multi-agent diagnostic deliberation.",
    )
    parser.add_argument("--mock", action="store_true",
                        help="Run with scripted mock agents (no API calls).")
    parser.add_argument("--case", type=str, default=None,
                        help="Path to fixture JSON (required with --mock).")
    parser.add_argument("--max-rounds", type=int, default=6,
                        help="Maximum deliberation rounds (default 6).")
    parser.add_argument("--no-banner", action="store_true",
                        help="Skip the disclaimer banner.")
    args = parser.parse_args()

    console = Console()
    if not args.no_banner and not args.mock:
        # Mock path renders banner inside run_mock_session; for live also there.
        # If neither flag chosen we render once here before usage error.
        pass

    if args.mock:
        if not args.case:
            console.print("[bold red]--mock requires --case <fixture.json>[/bold red]")
            sys.exit(2)
        run_mock_session(args.case, args.max_rounds)
        return

    # Default: live session needs a case id
    if not args.case:
        if not args.no_banner:
            render_disclaimer_banner(console)
        console.print("[yellow]No --case provided. Use --mock --case <path> "
                      "to run a scripted session.[/yellow]")
        sys.exit(2)

    run_live_session(args.case, args.max_rounds)


if __name__ == "__main__":
    main()
