import time

from arya.agent import Agent
from arya.config import settings
from arya.tracing import init_tracing


def print_chunk(chunk: str) -> None:
    if settings.stream_delay_ms <= 0:
        print(chunk, end="", flush=True)
        return

    delay = settings.stream_delay_ms / 1000
    for char in chunk:
        print(char, end="", flush=True)
        time.sleep(delay)


def main() -> None:
    init_tracing()
    agent = Agent()

    print("Arya is ready. Type 'exit' to quit.")
    while True:
        user_input = input("> ").strip()
        if user_input.lower() in {"exit", "quit"}:
            break
        if not user_input:
            continue

        for chunk in agent.step(user_input):
            print_chunk(chunk)
        print()


if __name__ == "__main__":
    main()
