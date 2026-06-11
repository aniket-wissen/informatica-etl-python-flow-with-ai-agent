from loguru import logger


def request_approval(title: str, details: dict, options: list[str]) -> str:
    """
    CLI approval prompt. Returns the chosen option string.
    options: list of short option labels e.g. ["accept", "reject", "edit"]
    """
    print(f"\n{'═'*55}")
    print(f"  ⚠️  HUMAN APPROVAL REQUIRED")
    print(f"  {title}")
    print(f"{'─'*55}")
    for key, val in details.items():
        if isinstance(val, list):
            print(f"  {key}:")
            for item in val:
                print(f"    • {item}")
        elif isinstance(val, dict):
            print(f"  {key}:")
            for k, v in val.items():
                print(f"    {k} → {v}")
        else:
            print(f"  {key}: {val}")
    print(f"{'─'*55}")

    for i, opt in enumerate(options, 1):
        print(f"  [{i}] {opt}")

    while True:
        choice = input(f"\n  Your choice (1-{len(options)}): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(options):
            chosen = options[int(choice) - 1]
            logger.info(f"  Human chose: {chosen}")
            return chosen
        print(f"  Invalid — enter a number between 1 and {len(options)}")


def confirm(message: str) -> bool:
    """Simple Y/N confirmation."""
    while True:
        ans = input(f"\n  {message} (Y/N): ").strip().upper()
        if ans in ("Y", "N"):
            return ans == "Y"