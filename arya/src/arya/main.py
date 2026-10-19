"""Arya entrypoints: the chat REPL (`arya`) and the memory inspection CLI
(`arya memories ...`)."""

import argparse
import sys
import time


def print_chunk(chunk: str) -> None:
    from arya.config import settings

    if settings.stream_delay_ms <= 0:
        print(chunk, end="", flush=True)
        return

    delay = settings.stream_delay_ms / 1000
    for char in chunk:
        print(char, end="", flush=True)
        time.sleep(delay)


def run_repl() -> None:
    from arya.agent import Agent
    from arya.agent_loop import run_turn
    from arya.config import settings
    from arya.tracing import init_tracing

    init_tracing()
    agent = Agent()

    print("Arya is ready. Type 'exit' to quit.")
    while True:
        user_input = input("> ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        try:
            for chunk in run_turn(agent, user_input):
                print_chunk(chunk)
        except Exception as exc:  # one bad turn must not kill the session
            print(f"\n[error: {exc}]")
        print()


# --- `arya memories` inspection CLI ---------------------------------------


def run_memories(argv: list[str]) -> int:
    from arya.memory import store as memory

    parser = argparse.ArgumentParser(prog="arya memories", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    list_p = sub.add_parser("list", help="list active memories")
    list_p.add_argument("--category", choices=memory.CATEGORIES)

    show_p = sub.add_parser("show", help="show a memory and its supersession chain")
    show_p.add_argument("id", type=int)

    delete_p = sub.add_parser("delete", help="hard-delete a memory")
    delete_p.add_argument("id", type=int)
    delete_p.add_argument("--force", action="store_true")

    edit_p = sub.add_parser("edit", help="correct a memory's content in place")
    edit_p.add_argument("id", type=int)
    edit_p.add_argument("--content", required=True)

    args = parser.parse_args(argv)

    if args.command == "list":
        for m in memory.list_memories(category=args.category):
            print(f"[{m['id']}] ({m['category']}) {m['content']}")
        return 0
    if args.command == "show":
        result = memory.show_memory(args.id)
        if result is None:
            print(f"no memory with id {args.id}")
            return 1
        for link in result["chain"]:
            state = "active" if link["active"] else f"superseded by {link['superseded_by']}"
            print(f"[{link['id']}] ({link['category']}, {state}) {link['content']}")
        return 0
    if args.command == "delete":
        error = memory.delete_memory(args.id, force=args.force)
        if error:
            print(error)
            return 1
        print(f"deleted memory {args.id}")
        return 0
    if args.command == "edit":
        error = memory.edit_memory(args.id, args.content)
        if error:
            print(error)
            return 1
        print(f"updated memory {args.id}")
        return 0
    return 2


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv

    # `memories` is purely local: dispatch before importing arya.agent or
    # initializing tracing, neither of which should require a model API key.
    if argv and argv[0] == "memories":
        sys.exit(run_memories(argv[1:]))

    run_repl()


if __name__ == "__main__":
    main()
