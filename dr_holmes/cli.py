"""
Dr. Holmes CLI — interactive diagnostic session.
Run: python3 -m dr_holmes.cli

⚠️  NOT FOR CLINICAL USE. AI output only. No real patient data.
"""
from __future__ import annotations
import os
import sys
import json
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table

load_dotenv()
console = Console()

AGENT_STYLES = {
    "hauser": ("bold red",    "Dr. Hauser"),
    "forman": ("bold cyan",   "Dr. Forman"),
    "human":  ("bold yellow", "YOU (Doctor)"),
}


# ── Display callbacks ──────────────────────────────────────────────────────

def make_token_cb():
    _state = {"agent": None}

    def on_token(agent_id: str, token: str | None, start: bool = False, end: bool = False):
        style, name = AGENT_STYLES.get(agent_id, ("white", agent_id))
        if start:
            _state["agent"] = agent_id
            console.print()
            console.print(f"[{style}]{'─'*6} {name} {'─'*6}[/{style}]")
            return
        if end:
            console.print()
            _state["agent"] = None
            return
        if token:
            console.print(token, end="", highlight=False)

    return on_token


def make_tool_cb(trace: list):
    def on_tool_call(agent_id: str, tool_name: str, args: dict, result: str):
        style, name = AGENT_STYLES.get(agent_id, ("white", agent_id))
        arg_str = ", ".join(f"{k}={repr(v)}" for k, v in list(args.items())[:3])
        console.print(f"\n  [{style}]⚙ {name} → {tool_name}({arg_str})[/{style}]")

        # Parse and display probability delta if this was an update
        if tool_name in ("update_probabilities", "get_differentials_for_symptoms"):
            try:
                results = json.loads(result)
                if isinstance(results, list) and results:
                    _show_ddx_table(results[:5])
            except Exception:
                pass

        trace.append({
            "agent": agent_id,
            "tool": tool_name,
            "args": args,
            "result_preview": result[:200],
            "timestamp": datetime.now().isoformat(),
        })

    return on_tool_call


def _show_ddx_table(dx_list: list[dict]):
    table = Table(show_header=True, header_style="bold magenta", box=None, padding=(0, 1))
    table.add_column("Disease", style="white", min_width=28)
    table.add_column("Prob %", justify="right", style="green")
    table.add_column("Note", style="dim")

    for dx in dx_list:
        prob = dx.get("probability", 0.0)
        rationale = dx.get("update_rationale", "")[:40]
        table.add_row(dx.get("disease", "?"), f"{prob*100:.1f}%", rationale)

    console.print(table)


# ── Case input ─────────────────────────────────────────────────────────────

def collect_case() -> dict:
    console.print(Panel(
        "[bold white]DR. HOLMES — Diagnostic Deliberation System[/bold white]\n"
        "[dim]⚠  NOT FOR CLINICAL USE. AI simulation only.[/dim]\n\n"
        "[dim]Dr. Hauser (Grok) vs Dr. Forman (GPT-4o)[/dim]\n"
        "[dim]You can inject findings at any >>> prompt.[/dim]",
        border_style="red",
        title="[bold red]DISCLAIMER[/bold red]",
    ))
    console.print()

    def multiline(prompt: str) -> str:
        console.print(f"[cyan]{prompt}[/cyan] [dim](blank line to finish)[/dim]")
        lines = []
        while True:
            line = input()
            if not line:
                break
            lines.append(line)
        return " ".join(lines)

    complaint = multiline("Chief Complaint:")
    history   = multiline("History / PMH / ROS:")

    console.print("[cyan]Vitals[/cyan] [dim](e.g. HR 110, BP 90/60, Temp 38.9 — or blank)[/dim]")
    vitals_raw = input().strip()
    vitals = {}
    for part in vitals_raw.split(","):
        part = part.strip()
        if " " in part:
            k, _, v = part.partition(" ")
            vitals[k.strip()] = v.strip()

    console.print("[cyan]Labs[/cyan] [dim](e.g. WBC 14.2, Hgb 8.1 — or blank)[/dim]")
    labs_raw = input().strip()
    labs = {}
    for part in labs_raw.split(","):
        part = part.strip()
        if " " in part:
            k, _, v = part.partition(" ")
            labs[k.strip()] = v.strip()

    console.print("[cyan]Imaging / Other[/cyan] [dim](or blank)[/dim]")
    imaging_raw = input().strip()

    console.print("[cyan]Medications[/cyan] [dim](comma-separated or blank)[/dim]")
    meds_raw = input().strip()
    meds = [m.strip() for m in meds_raw.split(",") if m.strip()]

    console.print("[cyan]Patient age / sex[/cyan] [dim](e.g. 34 F — or blank)[/dim]")
    demo_raw = input().strip().split()
    age = int(demo_raw[0]) if demo_raw and demo_raw[0].isdigit() else 0
    sex = demo_raw[1].upper() if len(demo_raw) > 1 else "other"
    sex = sex if sex in ("M", "F") else "other"

    return {
        "presenting_complaint": complaint,
        "history": history,
        "vitals": vitals,
        "labs": labs,
        "imaging": {"notes": imaging_raw} if imaging_raw else {},
        "medications": meds,
        "_demographics": {"age": age, "sex": sex},
    }


# ── Main session ───────────────────────────────────────────────────────────

def run_session():
    from dr_holmes.models.core import PatientCase, DiagnosticState
    from dr_holmes.agents.hauser import HauserAgent
    from dr_holmes.agents.forman import FormanAgent
    from dr_holmes.rag.retriever import build_index
    from dr_holmes.intelligence.medical import MedicalIntelligence
    from dr_holmes.intelligence.dispatcher import ToolDispatcher
    from dr_holmes.db.schema import get_engine, get_session
    from dr_holmes.graph.nodes import make_hauser_node, make_forman_node, make_human_inject_node
    from dr_holmes.graph.builder import build_graph
    from dr_holmes.graph.state import make_graph_state

    openai_key = os.getenv("OPENAI_API_KEY", "")
    xai_key    = os.getenv("XAI_API_KEY", "")
    xai_model  = os.getenv("XAI_MODEL",    "grok-2-1212")
    oai_model  = os.getenv("OPENAI_MODEL", "gpt-4o")
    chroma_path = os.getenv("CHROMA_PATH", "./data/chroma")
    db_path     = os.getenv("SQLITE_PATH",  "./data/bayes.db")
    neo4j_uri   = os.getenv("NEO4J_URI",    "bolt://localhost:7687")
    neo4j_user  = os.getenv("NEO4J_USER",   "neo4j")
    neo4j_pass  = os.getenv("NEO4J_PASSWORD","drholmes123")
    redis_url   = os.getenv("REDIS_URL",    "redis://localhost:6379")

    if not openai_key:
        console.print("[red]OPENAI_API_KEY not set.[/red]"); sys.exit(1)
    if not xai_key:
        console.print("[red]XAI_API_KEY not set.[/red]"); sys.exit(1)

    # ── RAG ────────────────────────────────────────────────────────────────
    console.print("[dim]Initializing RAG...[/dim]")
    try:
        collection = build_index(chroma_path)
    except Exception as e:
        console.print(f"[yellow]RAG unavailable: {e}[/yellow]")
        collection = None

    # ── Neo4j (with retry — Neo4j 5.x can take 20-30s to boot) ───────────────
    neo4j_driver = None
    try:
        import time
        from neo4j import GraphDatabase
        _driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user, neo4j_pass))
        for _attempt in range(5):
            try:
                _driver.verify_connectivity()
                neo4j_driver = _driver
                console.print("[dim]Neo4j connected.[/dim]")
                break
            except Exception:
                if _attempt < 4:
                    console.print(f"[dim]Neo4j not ready, retrying ({_attempt+1}/5)...[/dim]")
                    time.sleep(5)
        if not neo4j_driver:
            console.print("[yellow]Neo4j unavailable after retries — graph tools disabled.[/yellow]")
    except Exception as e:
        console.print(f"[yellow]Neo4j unavailable: {e}[/yellow]")

    # ── Redis ──────────────────────────────────────────────────────────────
    redis_client = None
    try:
        import redis as redis_lib
        redis_client = redis_lib.from_url(redis_url)
        redis_client.ping()
        console.print("[dim]Redis connected.[/dim]")
    except Exception as e:
        console.print(f"[yellow]Redis unavailable: {e}[/yellow]")

    # ── Bayesian DB ────────────────────────────────────────────────────────
    engine = get_engine(db_path)
    db_session = get_session(engine)

    # ── MedicalIntelligence + Dispatcher ───────────────────────────────────
    mi = MedicalIntelligence(
        bayes_session=db_session,
        neo4j_driver=neo4j_driver,
        chroma_collection=collection,
        redis_client=redis_client,
    )
    dispatcher = ToolDispatcher(mi)

    # ── Agents ─────────────────────────────────────────────────────────────
    hauser = HauserAgent(api_key=xai_key,    model=xai_model, dispatcher=dispatcher)
    forman = FormanAgent(api_key=openai_key, model=oai_model, dispatcher=dispatcher)

    # ── Collect case ────────────────────────────────────────────────────────
    case_data = collect_case()
    demographics = case_data.pop("_demographics", {"age": 0, "sex": "other"})
    case = PatientCase(**case_data)

    # Inject demographics into symptoms for initial Ddx
    initial_symptoms = [case.presenting_complaint]

    initial_state = {
        "case": case.model_dump(),
        "messages": [],
        "differentials": [],
        "current_speaker": "hauser",
        "round_number": 0,
        "human_injection": "",
        "concluded": False,
        "pending_injection": "",
    }

    # ── Callbacks ───────────────────────────────────────────────────────────
    trace: list[dict] = []
    on_token    = make_token_cb()
    on_tool_call = make_tool_cb(trace)

    # ── Build graph ─────────────────────────────────────────────────────────
    graph = build_graph(
        holmes_node=make_hauser_node(hauser, on_token=on_token, on_tool_call=on_tool_call),
        foreman_node=make_forman_node(forman, on_token=on_token, on_tool_call=on_tool_call),
        human_inject_node=make_human_inject_node(),
    )

    console.print()
    console.print(Rule("[bold red]SESSION STARTED[/bold red]"))
    console.print("[dim]Type a finding to inject it. Press Enter to continue. 'done' to conclude.[/dim]")
    console.print()

    config = {"configurable": {"thread_id": case.id}}
    state = initial_state
    max_rounds = 12

    for _ in range(max_rounds):
        if state.get("concluded"):
            break

        for event in graph.stream(state, config=config, stream_mode="values"):
            state = event

        # Show current Ddx summary
        ddx = state.get("differentials", [])
        if ddx:
            console.print()
            console.print(Rule("[bold magenta]CURRENT DIFFERENTIAL[/bold magenta]", style="magenta"))
            _show_ddx_table(ddx[:5])

        console.print()
        console.print(Rule("[bold yellow]YOUR TURN[/bold yellow]", style="yellow"))
        console.print("[dim]Inject finding / question / or Enter to continue / 'done' to end.[/dim]")

        try:
            user_input = input(">>> ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if user_input.lower() in ("quit", "exit"):
            break
        if user_input.lower() == "done":
            state["concluded"] = True
            break
        if user_input:
            console.print()
            console.print(f"[bold yellow]{'─'*6} YOU (Doctor) {'─'*6}[/bold yellow]")
            console.print(f"[yellow]{user_input}[/yellow]")
            state["pending_injection"] = user_input
        else:
            state["pending_injection"] = ""

    console.print()
    console.print(Rule("[bold red]SESSION CONCLUDED[/bold red]"))
    console.print(f"[dim]Rounds: {state.get('round_number', 0)} | Tool calls: {len(trace)}[/dim]")

    # ── Save trace ──────────────────────────────────────────────────────────
    Path("./data").mkdir(exist_ok=True)
    trace_path = f"./data/trace_{case.id}.json"
    with open(trace_path, "w") as f:
        json.dump({
            "case_id": case.id,
            "case": case.model_dump(mode="json"),
            "messages": state.get("messages", []),
            "differentials": state.get("differentials", []),
            "tool_trace": trace,
        }, f, indent=2, default=str)
    console.print(f"[dim]Trace saved to {trace_path}[/dim]")

    db_session.close()


def main():
    run_session()


if __name__ == "__main__":
    main()
