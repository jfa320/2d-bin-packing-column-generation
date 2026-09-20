"""Optional execution of the external PAVER report generator."""

from dataclasses import dataclass
from pathlib import Path
import subprocess

from utils.paver_constants import PaverConstants


PAVER = PaverConstants
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROPERTIES_PATH = PROJECT_ROOT / PAVER.PAVER_PROPERTIES_FILENAME


@dataclass(frozen=True)
class PaverRunResult:
    """Outcome of a best-effort PAVER invocation."""

    success: bool
    message: str
    report_path: Path
    command: tuple[str, ...] | None = None
    return_code: int | None = None


def default_report_path(trace_path):
    """Return the report directory derived from a trace path."""
    trace = Path(trace_path).resolve()
    return trace.with_name(f"{trace.stem}_paver")


def load_paver_root(properties_path=DEFAULT_PROPERTIES_PATH):
    """Load ``paver.path`` from the repository properties file."""
    properties = Path(properties_path)
    try:
        lines = properties.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(
            f"no se pudo leer {properties}: {type(error).__name__}: {error}"
        ) from error

    values = {}
    for line_number, raw_line in enumerate(lines, 1):
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        if "=" not in line:
            raise ValueError(
                f"línea inválida en {properties}:{line_number}; se esperaba clave=valor"
            )
        key, value = (part.strip() for part in line.split("=", 1))
        if not key or not value:
            raise ValueError(
                f"línea inválida en {properties}:{line_number}; clave y valor son obligatorios"
            )
        if key in values:
            raise ValueError(f"propiedad duplicada en {properties}: {key}")
        values[key] = value

    paver_root = values.get(PAVER.PAVER_PATH_PROPERTY)
    if paver_root is None:
        raise ValueError(
            f"falta la propiedad {PAVER.PAVER_PATH_PROPERTY!r} en {properties}"
        )
    return Path(paver_root)


def build_command(trace_path, paver_root, report_path, *, failtime,
                  mintime=PAVER.DEFAULT_PAVER_MIN_TIME):
    """Build the Windows command used by the installed PAVER distribution."""
    root = Path(paver_root).resolve()
    script = root.joinpath(*PAVER.PAVER_SCRIPT_RELATIVE_PATH)
    return (
        *PAVER.PAVER_PYTHON_COMMAND,
        str(script),
        str(Path(trace_path).resolve()),
        *(('--ignoredualbounds',) if PAVER.PAVER_IGNORE_DUAL_BOUNDS else ()),
        "--mintime", f"{mintime:g}",
        "--failtime", str(failtime),
        "--writehtml", str(Path(report_path).resolve()),
    )


def run_paver(trace_path, paver_root=None, report_path=None, *, failtime,
              mintime=PAVER.DEFAULT_PAVER_MIN_TIME,
              properties_path=DEFAULT_PROPERTIES_PATH):
    """Run PAVER without making its external availability fatal to the caller.

    The solver run and its trace are produced by the caller before this
    function is invoked. Missing PAVER, a missing Python launcher, or a
    nonzero PAVER exit code are returned as a failed result instead of raised.
    """
    trace = Path(trace_path).resolve()
    report = (default_report_path(trace) if report_path is None
              else Path(report_path).resolve())
    if paver_root is None:
        try:
            paver_root = load_paver_root(properties_path)
        except ValueError as error:
            return PaverRunResult(
                False,
                f"Configuración de PAVER inválida: {error}",
                report,
            )
    root = Path(paver_root).resolve()
    script = root.joinpath(*PAVER.PAVER_SCRIPT_RELATIVE_PATH)

    if not root.is_dir():
        return PaverRunResult(
            False,
            f"PAVER no encontrado: la carpeta no existe: {root}",
            report,
        )
    if not script.is_file():
        return PaverRunResult(
            False,
            f"PAVER no encontrado: falta el script: {script}",
            report,
        )

    command = build_command(trace, root, report, failtime=failtime, mintime=mintime)
    try:
        completed = subprocess.run(command, cwd=root, check=False)
    except OSError as error:
        return PaverRunResult(
            False,
            f"No se pudo ejecutar PAVER: {type(error).__name__}: {error}",
            report,
            command,
        )

    if completed.returncode != 0:
        return PaverRunResult(
            False,
            f"PAVER terminó con código {completed.returncode}",
            report,
            command,
            completed.returncode,
        )

    index = report / "index.html"
    if not index.is_file():
        return PaverRunResult(
            False,
            f"PAVER terminó correctamente pero no generó el informe esperado: {index}",
            report,
            command,
            completed.returncode,
        )

    return PaverRunResult(
        True,
        f"Informe PAVER generado: {index}",
        report,
        command,
        completed.returncode,
    )
