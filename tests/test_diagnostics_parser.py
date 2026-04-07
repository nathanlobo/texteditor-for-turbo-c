from src.app.services.diagnostics_parser import parse_diagnostics


def test_parse_error_line_with_file_and_line() -> None:
    output = "main.c:12: Error: Undefined symbol x"
    diagnostics = parse_diagnostics(output)

    assert len(diagnostics) == 1
    assert diagnostics[0].file == "main.c"
    assert diagnostics[0].line == 12
    assert diagnostics[0].severity.value == "error"


def test_parse_info_line() -> None:
    diagnostics = parse_diagnostics("Compilation complete")
    assert len(diagnostics) == 1
    assert diagnostics[0].severity.value == "info"
