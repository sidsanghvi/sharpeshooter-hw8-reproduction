from .common import CodexRunner, run_cli


def main(argv: list[str] | None = None, *, runner: CodexRunner | None = None) -> int:
    return run_cli("scout", argv, runner=runner)
