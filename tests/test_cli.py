from scc.cli import build_parser


def test_build_parser_accepts_monitor_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["monitor"])
    assert args.command == "monitor"


def test_build_parser_accepts_snapshot_command() -> None:
    parser = build_parser()
    args = parser.parse_args(["snapshot"])
    assert args.command == "snapshot"
