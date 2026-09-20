from pathlib import Path

import utils.paver_runner as runner


def make_paver_tree(tmp_path):
    root = tmp_path / "Paver"
    script = root / "src" / "paver" / "paver.py"
    script.parent.mkdir(parents=True)
    script.write_text("# test paver\n", encoding="utf-8")
    return root


def test_build_command_uses_paver_runtime_and_failtime(tmp_path):
    root = make_paver_tree(tmp_path)
    trace = tmp_path / "Results" / "comparison.trc"
    report = tmp_path / "Results" / "comparison_paver"

    command = runner.build_command(trace, root, report, failtime=37)

    assert command[:2] == ("py", "-3.6")
    assert command[2] == str((root / "src" / "paver" / "paver.py").resolve())
    assert command[3] == str(trace.resolve())
    assert command[4] == "--ignoredualbounds"
    assert command[-6:] == (
        "--mintime", "0.001", "--failtime", "37", "--writehtml", str(report.resolve())
    )


def test_load_paver_root_from_properties(tmp_path):
    properties = tmp_path / "paver.properties"
    properties.write_text(
        "# local installation\npaver.path=I:\\Mi unidad\\Tesina\\Paver\n",
        encoding="utf-8",
    )

    assert runner.load_paver_root(properties) == Path(r"I:\Mi unidad\Tesina\Paver")


def test_missing_path_property_is_reported_without_stopping(tmp_path):
    properties = tmp_path / "paver.properties"
    properties.write_text("other.value=test\n", encoding="utf-8")

    result = runner.run_paver(
        tmp_path / "trace.trc",
        failtime=10,
        properties_path=properties,
    )

    assert not result.success
    assert "paver.path" in result.message


def test_missing_paver_is_reported_without_running_process(tmp_path, monkeypatch):
    called = False

    def forbidden(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(runner.subprocess, "run", forbidden)

    result = runner.run_paver(tmp_path / "trace.trc", tmp_path / "missing", failtime=10)

    assert not result.success
    assert "no existe" in result.message
    assert not called


def test_paver_failure_is_non_fatal(tmp_path, monkeypatch):
    root = make_paver_tree(tmp_path)
    trace = tmp_path / "trace.trc"
    report = tmp_path / "report"

    class Completed:
        returncode = 2

    monkeypatch.setattr(runner.subprocess, "run", lambda *args, **kwargs: Completed())

    result = runner.run_paver(trace, root, report, failtime=10)

    assert not result.success
    assert result.return_code == 2
    assert "código 2" in result.message


def test_success_requires_generated_index(tmp_path, monkeypatch):
    root = make_paver_tree(tmp_path)
    trace = tmp_path / "trace.trc"
    report = tmp_path / "report"

    class Completed:
        returncode = 0

    def fake_run(*args, **kwargs):
        report.mkdir()
        (report / "index.html").write_text("<html></html>", encoding="utf-8")
        return Completed()

    monkeypatch.setattr(runner.subprocess, "run", fake_run)

    result = runner.run_paver(trace, root, report, failtime=10)

    assert result.success
    assert result.report_path == report.resolve()
    assert Path(result.report_path / "index.html").is_file()
