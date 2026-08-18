#!/usr/bin/env python3
"""Self-bootstrap a compatible Python, prepare a dedicated environment, and run a command.

This launcher intentionally depends only on the Python standard library. It may
therefore be called with an arbitrary ``python`` command: it discovers a better
compatible CPython when needed, re-launches itself, creates or resumes a managed
virtual environment, verifies the CAD dependencies, and only then runs the
requested pipeline command.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import shutil
import site
import socket
import struct
import subprocess
import sys
import time
import venv
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence

COMMANDS: dict[str, tuple[str, list[str]] | None] = {
    "bootstrap": None,
    "discover": ("input_discovery.py", []),
    "preflight": ("preflight.py", []),
    "plan": ("cad_render.py", ["--plan-only"]),
    "prepare": ("cad_render.py", []),
    "stage": ("finalize_candidates.py", ["--stage-only"]),
    "finalize": ("finalize_candidates.py", []),
    "refine-stage": ("final_refinement.py", ["--stage-only"]),
    "finish": ("final_refinement.py", []),
    "metrics": ("geometry_metrics.py", []),
    "self-test": ("self_test.py", []),
}

REQUIRED_IMPORTS = (
    "yaml",
    "numpy",
    "PIL",
    "cv2",
    "requests",
    "cadquery",
    "OCP",
    "vtk",
    "trimesh",
)

# Prefer the Python versions that consistently have CadQuery/OCP and VTK wheels.
# Keep 3.10/3.13 as fallbacks, but never initialize the heavy environment under
# an older or bleeding-edge interpreter by accident.
SUPPORTED_MIN = (3, 10)
SUPPORTED_MAX = (3, 13)
INTERPRETER_PREFERENCE = ((3, 12), (3, 11), (3, 13), (3, 10))

METADATA_NAME = ".cad-ai-renderer-environment.json"
STATE_NAME = ".cad-ai-renderer-install-state.json"
OWNER_NAME = ".cad-ai-renderer-owned"
LEGACY_MARKER_NAME = ".cad-ai-renderer-requirements.sha256"
HOST_LINK_NAME = "cad_ai_renderer_host_packages.pth"
BOOTSTRAP_MARKER = "CAD_AI_RENDERER_BOOTSTRAPPED"
LOCK_WAIT_SECONDS = 900
LOCK_STALE_SECONDS = 1800
LOCK_OWNER_GRACE_SECONDS = 5


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_text(json.dumps(dict(payload), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def _version_supported(version: Sequence[int]) -> bool:
    pair = (int(version[0]), int(version[1]))
    return SUPPORTED_MIN <= pair <= SUPPORTED_MAX


def _interpreter_rank(candidate: Mapping[str, Any]) -> tuple[int, int, str]:
    version = tuple(candidate.get("version", (0, 0)))
    try:
        preference = INTERPRETER_PREFERENCE.index((int(version[0]), int(version[1])))
    except (ValueError, IndexError, TypeError):
        preference = len(INTERPRETER_PREFERENCE)
    current_penalty = 0 if os.path.normcase(str(candidate.get("executable", ""))) == os.path.normcase(sys.executable) else 1
    return preference, current_penalty, str(candidate.get("executable", ""))


def _select_best_interpreter(candidates: Sequence[Mapping[str, Any]]) -> dict[str, Any] | None:
    compatible = [
        dict(candidate)
        for candidate in candidates
        if _version_supported(candidate.get("version", (0, 0))) and int(candidate.get("bits", 0)) >= 64
    ]
    explicit = [candidate for candidate in compatible if candidate.get("source") == "explicit"]
    if explicit:
        return explicit[0]
    return min(compatible, key=_interpreter_rank) if compatible else None


def _probe_interpreter(command: Sequence[str], source: str) -> dict[str, Any] | None:
    code = (
        "import json,struct,sys;"
        "print(json.dumps({'executable':sys.executable,'version':[sys.version_info[0],sys.version_info[1],sys.version_info[2]],"
        "'bits':struct.calcsize('P')*8}))"
    )
    try:
        completed = subprocess.run(
            [*command, "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=12,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    try:
        payload = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not payload.get("executable"):
        return None
    payload["source"] = source
    payload["version"] = tuple(int(value) for value in payload.get("version", [])[:3])
    return payload


def _explicit_python_command(value: str) -> list[str]:
    expanded = Path(value).expanduser()
    if expanded.exists():
        return [str(expanded.resolve())]
    return shlex.split(value, posix=os.name != "nt")


def _discover_interpreters(explicit: str | None = None) -> list[dict[str, Any]]:
    commands: list[tuple[list[str], str]] = []
    if explicit:
        commands.append((_explicit_python_command(explicit), "explicit"))
    commands.append(([sys.executable], "current"))

    preferred = ("3.12", "3.11", "3.13", "3.10")
    if os.name == "nt":
        launcher = shutil.which("py")
        if launcher:
            commands.extend(([launcher, f"-{version}"], f"windows-py-{version}") for version in preferred)
    for version in preferred:
        executable = shutil.which(f"python{version}")
        if executable:
            commands.append(([executable], f"path-python{version}"))
    for name in ("python3", "python"):
        executable = shutil.which(name)
        if executable:
            commands.append(([executable], f"path-{name}"))

    found: list[dict[str, Any]] = []
    seen: set[str] = set()
    for command, source in commands:
        if not command:
            continue
        candidate = _probe_interpreter(command, source)
        if not candidate:
            continue
        key = os.path.normcase(os.path.realpath(str(candidate["executable"])))
        if key in seen:
            continue
        seen.add(key)
        found.append(candidate)
    return found


def _bootstrap_override(argv: Sequence[str]) -> str | None:
    env_value = os.environ.get("CAD_AI_RENDERER_BOOTSTRAP_PYTHON")
    if env_value:
        return env_value
    for index, value in enumerate(argv):
        if value.startswith("--bootstrap-python="):
            return value.split("=", 1)[1]
        if value == "--bootstrap-python" and index + 1 < len(argv):
            return argv[index + 1]
    return None


def _bootstrap_relaunch(argv: Sequence[str]) -> int | None:
    if os.environ.get(BOOTSTRAP_MARKER) == "1":
        if not _version_supported(sys.version_info[:2]) or struct.calcsize("P") * 8 < 64:
            raise SystemExit(
                "The selected bootstrap interpreter is incompatible. Use a 64-bit CPython 3.10-3.13 "
                "or set CAD_AI_RENDERER_BOOTSTRAP_PYTHON to one."
            )
        return None

    candidates = _discover_interpreters(_bootstrap_override(argv))
    selected = _select_best_interpreter(candidates)
    if selected is None:
        discovered = ", ".join(
            f"{item.get('executable')} ({'.'.join(map(str, item.get('version', ())[:2]))}, {item.get('bits')} bit)"
            for item in candidates
        ) or "none"
        raise SystemExit(
            "cad-ai-renderer needs a 64-bit CPython 3.10-3.13; 3.12 is preferred. "
            f"Compatible interpreter discovery failed. Discovered: {discovered}. "
            "Install a compatible Python or set CAD_AI_RENDERER_BOOTSTRAP_PYTHON."
        )

    selected_path = os.path.realpath(str(selected["executable"]))
    current_path = os.path.realpath(sys.executable)
    if os.path.normcase(selected_path) == os.path.normcase(current_path):
        os.environ[BOOTSTRAP_MARKER] = "1"
        return None

    version_text = ".".join(str(value) for value in selected["version"][:2])
    print(
        f"[cad-ai-renderer bootstrap] Re-launching with Python {version_text}: {selected_path}",
        flush=True,
    )
    env = os.environ.copy()
    env[BOOTSTRAP_MARKER] = "1"
    completed = subprocess.run([selected_path, str(Path(__file__).resolve()), *argv], env=env, check=False)
    return completed.returncode


def _default_venv_dir() -> Path:
    override = os.environ.get("CAD_AI_RENDERER_VENV")
    if override:
        return Path(override).expanduser().resolve()
    return (Path.home() / ".cache" / "cad-ai-renderer" / "venv").resolve()


def _managed_venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def _existing_environment_python(venv_dir: Path) -> Path | None:
    candidates = (
        [venv_dir / "Scripts" / "python.exe", venv_dir / "python.exe"]
        if os.name == "nt"
        else [venv_dir / "bin" / "python", venv_dir / "bin" / "python3"]
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def _requirements_digest(requirements: Path) -> str:
    payload = requirements.read_bytes() + f"\npython={sys.version_info.major}.{sys.version_info.minor}".encode()
    return hashlib.sha256(payload).hexdigest()


def _env_flag(name: str, default: bool = True) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() not in {"0", "false", "no", "off"}


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print(f"[cad-ai-renderer env] {' '.join(command)}", flush=True)
    subprocess.run(command, check=True, env=env)


def _probe_environment(python_path: Path) -> tuple[bool, dict[str, str]]:
    code = (
        "import importlib, json\n"
        f"names={list(REQUIRED_IMPORTS)!r}\n"
        "errors={}\n"
        "for name in names:\n"
        "    try:\n"
        "        importlib.import_module(name)\n"
        "    except Exception as exc:\n"
        "        errors[name]=f'{type(exc).__name__}: {exc}'\n"
        "print('CAD_AI_RENDERER_PROBE=' + json.dumps(errors, ensure_ascii=False))\n"
        "raise SystemExit(1 if errors else 0)\n"
    )
    try:
        completed = subprocess.run(
            [str(python_path), "-c", code],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "VTK_DEFAULT_RENDER_WINDOW_OFFSCREEN": "1"},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, {"probe": f"{type(exc).__name__}: {exc}"}
    marker = "CAD_AI_RENDERER_PROBE="
    errors: dict[str, str] = {}
    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(marker):
            try:
                parsed = json.loads(line[len(marker) :])
                if isinstance(parsed, dict):
                    errors = {str(key): str(value) for key, value in parsed.items()}
            except json.JSONDecodeError:
                errors = {"probe": "invalid dependency-probe output"}
            break
    else:
        detail = completed.stderr.strip() or completed.stdout.strip() or "dependency probe produced no result"
        errors = {"probe": detail[-1600:]}
    return completed.returncode == 0 and not errors, errors


def _python_pair(python_path: Path) -> tuple[int, int] | None:
    try:
        completed = subprocess.run(
            [str(python_path), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')"],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
        major, minor = completed.stdout.strip().split(".", 1)
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None


def _create_environment(venv_dir: Path) -> Path:
    venv_dir.mkdir(parents=True, exist_ok=True)
    # Mark ownership before the potentially interruptible venv creation step so
    # a killed first run can be recognized and safely rebuilt or resumed.
    (venv_dir / OWNER_NAME).write_text(
        "This directory is managed by cad-ai-renderer scripts/run.py.\n",
        encoding="utf-8",
    )
    venv.EnvBuilder(with_pip=True, clear=False).create(venv_dir)
    return _managed_venv_python(venv_dir)


def _install_requirements(python_path: Path, requirements: Path) -> None:
    pip_env = os.environ.copy()
    pip_env.setdefault("PIP_DISABLE_PIP_VERSION_CHECK", "1")
    pip_env.setdefault("PIP_NO_INPUT", "1")
    pip_env.setdefault("PIP_DEFAULT_TIMEOUT", "30")
    _run(
        [
            str(python_path),
            "-m",
            "pip",
            "install",
            "--disable-pip-version-check",
            "--no-input",
            "--prefer-binary",
            "--retries",
            "2",
            "--timeout",
            "30",
            "-r",
            str(requirements),
        ],
        env=pip_env,
    )


def _host_site_paths() -> list[Path]:
    candidates: list[str] = []
    try:
        candidates.extend(site.getsitepackages())
    except AttributeError:
        pass
    try:
        candidates.append(site.getusersitepackages())
    except AttributeError:
        pass
    candidates.extend(entry for entry in sys.path if "site-packages" in entry or "dist-packages" in entry)

    result: list[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(candidate).expanduser().resolve()
        key = os.path.normcase(str(path))
        if path.is_dir() and key not in seen:
            seen.add(key)
            result.append(path)
    return result


def _target_site_packages(python_path: Path) -> Path:
    code = "import json, site; print(json.dumps(site.getsitepackages()))"
    output = subprocess.check_output([str(python_path), "-c", code], text=True)
    paths = json.loads(output.strip())
    if not isinstance(paths, list) or not paths:
        raise RuntimeError("Could not locate the managed environment site-packages directory")
    target = Path(paths[0]).resolve()
    target.mkdir(parents=True, exist_ok=True)
    return target


def _host_link_path(python_path: Path) -> Path | None:
    """Locate the host-package link without creating directories."""

    code = "import json, site; print(json.dumps(site.getsitepackages()))"
    try:
        output = subprocess.check_output([str(python_path), "-c", code], text=True, timeout=20)
        paths = json.loads(output.strip())
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    if not isinstance(paths, list):
        return None
    for value in paths:
        candidate = Path(str(value)).resolve() / HOST_LINK_NAME
        if candidate.is_file():
            return candidate
    return None


def _create_host_linked_environment(venv_dir: Path) -> Path:
    host_ok, host_errors = _probe_environment(Path(sys.executable))
    if not host_ok:
        missing = ", ".join(sorted(host_errors))
        raise RuntimeError(
            "Package installation failed and the selected bootstrap Python cannot supply an offline fallback. "
            f"Missing or broken host imports: {missing}"
        )

    print(
        "[cad-ai-renderer env] Package installation failed; creating a dedicated environment "
        "linked to the selected runtime's installed packages.",
        flush=True,
    )
    if venv_dir.exists():
        shutil.rmtree(venv_dir)
    python_path = _create_environment(venv_dir)
    source_paths = _host_site_paths()
    if not source_paths:
        raise RuntimeError("No usable host site-packages directories were found for the offline fallback")
    target = _target_site_packages(python_path)
    (target / HOST_LINK_NAME).write_text(
        "".join(f"{path}\n" for path in source_paths),
        encoding="utf-8",
    )
    linked_ok, linked_errors = _probe_environment(python_path)
    if not linked_ok:
        missing = ", ".join(sorted(linked_errors))
        raise RuntimeError(f"The host-linked environment was created but dependency probing failed: {missing}")
    return python_path


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        # ``os.kill(pid, 0)`` is not a reliable existence probe on every
        # supported Windows Python build. Query the process handle directly so
        # a bootstrap interrupted on another machine does not leave a lock
        # that blocks a migrated installation until the age timeout expires.
        try:
            import ctypes

            process_query_limited_information = 0x1000
            still_active = 259
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
            kernel32.OpenProcess.restype = ctypes.c_void_p
            kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
            kernel32.GetExitCodeProcess.restype = ctypes.c_int
            kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
            kernel32.CloseHandle.restype = ctypes.c_int

            handle = kernel32.OpenProcess(process_query_limited_information, 0, pid)
            if not handle:
                # Access denied means the process exists but is owned by a
                # different security context. Other failures mean it is gone.
                return ctypes.get_last_error() == 5
            try:
                exit_code = ctypes.c_ulong()
                if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                    return True
                return exit_code.value == still_active
            finally:
                kernel32.CloseHandle(handle)
        except (AttributeError, OSError, ValueError):
            # Fall back to the portable probe below on unusual runtimes.
            pass
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True
    return True


def _lock_is_stale(lock_dir: Path) -> bool:
    owner = _read_json(lock_dir / "owner.json")
    try:
        age = time.time() - lock_dir.stat().st_mtime
    except OSError:
        return True
    if age > LOCK_STALE_SECONDS:
        return True

    owner_host = str(owner.get("hostname", "")).strip()
    current_host = socket.gethostname()
    if not owner_host:
        # Another process can observe the lock directory in the tiny interval
        # between mkdir and the atomic owner-file replace. Give that creator a
        # short grace period instead of deleting the directory underneath it.
        return age > LOCK_OWNER_GRACE_SECONDS
    if owner_host != current_host:
        # A lock copied with a project or cache cannot be owned by a process on
        # this machine. Treat host mismatch as a migration artifact instead of
        # waiting up to 30 minutes. Shared-network installations should give
        # each host a separate CAD_AI_RENDERER_VENV path.
        return True
    try:
        return not _pid_alive(int(owner.get("pid", -1)))
    except (TypeError, ValueError):
        return True


@contextmanager
def _environment_lock(venv_dir: Path) -> Iterator[None]:
    lock_dir = venv_dir.parent / f".{venv_dir.name}.bootstrap.lock"
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            lock_dir.mkdir(parents=True, exist_ok=False)
            _atomic_write_json(
                lock_dir / "owner.json",
                {"pid": os.getpid(), "hostname": socket.gethostname(), "started_at": time.time()},
            )
            break
        except FileExistsError:
            if _lock_is_stale(lock_dir):
                shutil.rmtree(lock_dir, ignore_errors=True)
                continue
            if time.monotonic() >= deadline:
                raise SystemExit(
                    f"Timed out waiting for another cad-ai-renderer bootstrap: {lock_dir}. "
                    "Re-run after the other process finishes."
                )
            print(f"[cad-ai-renderer env] Waiting for environment bootstrap lock: {lock_dir}", flush=True)
            time.sleep(2)
    try:
        yield
    finally:
        shutil.rmtree(lock_dir, ignore_errors=True)


def _managed_environment_action(
    *,
    exists: bool,
    recognized: bool,
    python_pair: tuple[int, int] | None,
    current_pair: tuple[int, int],
    refresh: bool,
) -> str:
    """Pure decision helper used by the self-test."""
    if refresh:
        return "rebuild"
    if not exists:
        return "create"
    if not recognized:
        return "external_or_refuse"
    if python_pair == current_pair:
        return "resume"
    return "rebuild"


def ensure_environment(
    venv_dir: Path,
    *,
    refresh: bool = False,
    no_install: bool = False,
    allow_host_packages: bool = True,
) -> tuple[Path, str]:
    skill_root = Path(__file__).resolve().parent.parent
    requirements = skill_root / "requirements.txt"
    expected = _requirements_digest(requirements)
    metadata_path = venv_dir / METADATA_NAME
    state_path = venv_dir / STATE_NAME
    owner_path = venv_dir / OWNER_NAME
    legacy_marker = venv_dir / LEGACY_MARKER_NAME

    existing_python = _existing_environment_python(venv_dir) if venv_dir.exists() else None
    metadata = _read_json(metadata_path)
    recognized = owner_path.exists() or legacy_marker.exists() or metadata.get("mode") in {"isolated", "host-linked"}

    # An explicitly supplied existing Python/conda environment is read-only.
    if venv_dir.exists() and not recognized:
        if existing_python:
            ok, errors = _probe_environment(existing_python)
            if not ok:
                missing = ", ".join(sorted(errors))
                raise SystemExit(
                    "Refusing to modify the existing non-managed environment because required imports failed: "
                    f"{missing}. Choose an empty --venv-dir or repair that environment yourself."
                )
            if refresh:
                raise SystemExit("--refresh cannot modify an external environment; choose an empty managed path instead")
            print(f"[cad-ai-renderer env] Using compatible external environment: {venv_dir}", flush=True)
            return existing_python, "external"
        if any(venv_dir.iterdir()):
            raise SystemExit(
                f"Refusing to replace non-empty non-managed directory: {venv_dir}. Choose an empty --venv-dir."
            )

    with _environment_lock(venv_dir):
        # Refresh state after waiting for a concurrent bootstrap.
        metadata = _read_json(metadata_path)
        existing_python = _existing_environment_python(venv_dir) if venv_dir.exists() else None
        recognized = owner_path.exists() or legacy_marker.exists() or metadata.get("mode") in {"isolated", "host-linked"}
        current_pair = (sys.version_info.major, sys.version_info.minor)
        existing_pair = _python_pair(existing_python) if existing_python else None
        host_link = _host_link_path(existing_python) if existing_python else None

        # A process may be terminated after the offline host link is written
        # but before metadata is committed. Recover that environment directly
        # instead of invoking pip again (which could incorrectly classify the
        # linked packages as an isolated install).
        host_link_metadata_stale = bool(
            host_link
            and (
                metadata.get("status") != "ready"
                or metadata.get("mode") != "host-linked"
                or metadata.get("requirements_sha256") != expected
                or tuple(metadata.get("python_version", []))[:2] != current_pair
            )
        )
        if existing_python and host_link_metadata_stale and allow_host_packages and not refresh:
            ok, errors = _probe_environment(existing_python)
            if ok:
                print(
                    f"[cad-ai-renderer env] Recovered interrupted host-linked environment: {venv_dir}",
                    flush=True,
                )
                previous_state = _read_json(state_path)
                attempt = max(1, int(previous_state.get("attempt", 0)))
                _atomic_write_json(
                    metadata_path,
                    {
                        "status": "ready",
                        "requirements_sha256": expected,
                        "mode": "host-linked",
                        "python_version": list(current_pair),
                        "python_executable": str(existing_python),
                        "source_python": sys.executable,
                        "recovered": True,
                        "finished_at": time.time(),
                    },
                )
                _atomic_write_json(
                    state_path,
                    {
                        "status": "ready",
                        "attempt": attempt,
                        "requirements_sha256": expected,
                        "python_version": list(current_pair),
                        "mode": "host-linked",
                        "recovered": True,
                        "finished_at": time.time(),
                    },
                )
                return existing_python, "host-linked"
            print(
                "[cad-ai-renderer env] Interrupted host-linked environment failed probing; rebuilding: "
                + ", ".join(sorted(errors)),
                flush=True,
            )

        if host_link and not allow_host_packages:
            if no_install:
                raise SystemExit(
                    "The existing managed environment uses host-linked packages, but host-package fallback is disabled. "
                    "Remove --no-install and use --refresh to build an isolated environment."
                )
            refresh = True

        synchronized = bool(
            existing_python
            and metadata.get("status", "ready") == "ready"
            and metadata.get("requirements_sha256") == expected
            and tuple(metadata.get("python_version", []))[:2] == current_pair
        )
        if synchronized and metadata.get("mode") == "host-linked" and not allow_host_packages:
            synchronized = False
        if synchronized and not refresh:
            ok, errors = _probe_environment(existing_python)
            if ok:
                return existing_python, str(metadata.get("mode", "isolated"))
            print(
                "[cad-ai-renderer env] Existing environment failed dependency probing; resuming repair: "
                + ", ".join(sorted(errors)),
                flush=True,
            )

        if no_install:
            raise SystemExit("Managed environment is missing, stale, or unhealthy and --no-install was supplied")

        action = _managed_environment_action(
            exists=venv_dir.exists(),
            recognized=recognized,
            python_pair=existing_pair,
            current_pair=current_pair,
            refresh=refresh,
        )
        if action == "rebuild":
            if venv_dir.exists() and not recognized:
                raise SystemExit(f"Refusing to rebuild non-managed directory: {venv_dir}")
            print(f"[cad-ai-renderer env] Rebuilding managed environment: {venv_dir}", flush=True)
            shutil.rmtree(venv_dir, ignore_errors=False)
            existing_python = None
        elif action == "resume":
            install_state = _read_json(state_path).get("status")
            label = "interrupted" if install_state == "installing" else "stale or partial"
            print(f"[cad-ai-renderer env] Resuming {label} environment: {venv_dir}", flush=True)
        elif action == "create":
            print(f"[cad-ai-renderer env] Creating isolated environment: {venv_dir}", flush=True)

        if not venv_dir.exists() or not _existing_environment_python(venv_dir):
            python_path = _create_environment(venv_dir)
        else:
            python_path = _existing_environment_python(venv_dir)
            assert python_path is not None
            if not owner_path.exists():
                owner_path.write_text(
                    "This directory is managed by cad-ai-renderer scripts/run.py.\n",
                    encoding="utf-8",
                )

        previous_state = _read_json(state_path)
        attempt = int(previous_state.get("attempt", 0)) + 1
        _atomic_write_json(
            state_path,
            {
                "status": "installing",
                "attempt": attempt,
                "requirements_sha256": expected,
                "python_version": list(current_pair),
                "python_executable": str(python_path),
                "started_at": time.time(),
            },
        )

        install_failure: BaseException | None = None
        try:
            _install_requirements(python_path, requirements)
            ok, errors = _probe_environment(python_path)
            if not ok:
                raise RuntimeError("Dependency installation completed but probing failed: " + ", ".join(sorted(errors)))
        except (subprocess.CalledProcessError, RuntimeError, OSError) as exc:
            install_failure = exc

        mode = "host-linked" if _host_link_path(python_path) else "isolated"
        if install_failure is not None:
            _atomic_write_json(
                state_path,
                {
                    "status": "failed",
                    "attempt": attempt,
                    "requirements_sha256": expected,
                    "python_version": list(current_pair),
                    "error": f"{type(install_failure).__name__}: {install_failure}",
                    "finished_at": time.time(),
                },
            )
            if not allow_host_packages:
                raise SystemExit(
                    "Could not install and verify the dedicated environment. Re-run the same bootstrap command to "
                    "resume cached downloads, or provide a compatible external environment."
                ) from install_failure
            try:
                python_path = _create_host_linked_environment(venv_dir)
                mode = "host-linked"
            except RuntimeError as fallback_error:
                raise SystemExit(
                    "Could not prepare the dedicated environment. Re-run the same command to resume the partial "
                    "installation. The isolated install failed and the selected Python could not supply an offline "
                    f"fallback: {fallback_error}"
                ) from install_failure

        _atomic_write_json(
            metadata_path,
            {
                "status": "ready",
                "requirements_sha256": expected,
                "mode": mode,
                "python_version": list(current_pair),
                "python_executable": str(python_path),
                "source_python": sys.executable if mode == "host-linked" else None,
                "finished_at": time.time(),
            },
        )
        _atomic_write_json(
            state_path,
            {
                "status": "ready",
                "attempt": attempt,
                "requirements_sha256": expected,
                "python_version": list(current_pair),
                "mode": mode,
                "finished_at": time.time(),
            },
        )
        if legacy_marker.exists():
            legacy_marker.unlink()
        return python_path, mode


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, add_help=False)
    parser.add_argument("-h", "--help", action="store_true", dest="launcher_help", help="Show launcher help; place after a command for command-specific help")
    parser.add_argument("--bootstrap-python", help="Preferred bootstrap Python path/command; 3.12 is recommended")
    parser.add_argument("--venv-dir", default=str(_default_venv_dir()))
    parser.add_argument("--refresh", action="store_true", help="Rebuild and resynchronize the managed environment")
    parser.add_argument("--no-install", action="store_true", help="Never create/install; fail if the environment is not ready")
    parser.add_argument(
        "--isolated-only",
        action="store_true",
        help="Forbid the offline fallback that links packages from the selected runtime",
    )
    parser.add_argument("--print-python", action="store_true", help="Print the managed interpreter path and exit")
    parser.add_argument("command", nargs="?", choices=sorted(COMMANDS))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    relaunched = _bootstrap_relaunch(arguments)
    if relaunched is not None:
        return relaunched

    parser = _build_parser()
    command_positions = [index for index, value in enumerate(arguments) if value in COMMANDS]
    command_position = command_positions[0] if command_positions else None
    help_positions = [index for index, value in enumerate(arguments) if value in {"-h", "--help"}]
    delegated_help = bool(
        command_position is not None
        and arguments[command_position] != "bootstrap"
        and any(index > command_position for index in help_positions)
    )
    args, remainder = parser.parse_known_args(arguments)
    if args.launcher_help and not delegated_help:
        parser.print_help()
        return 0
    if delegated_help:
        remainder.append("--help")

    allow_host_packages = _env_flag("CAD_AI_RENDERER_ALLOW_HOST_PACKAGES", True) and not args.isolated_only
    venv_dir = Path(args.venv_dir).expanduser().resolve()
    python_path, mode = ensure_environment(
        venv_dir,
        refresh=args.refresh,
        no_install=args.no_install,
        allow_host_packages=allow_host_packages,
    )

    if args.print_python:
        print(python_path)
        return 0
    if not args.command:
        parser.error("a command is required unless --print-python is used")
    if args.command == "bootstrap":
        print(
            json.dumps(
                {
                    "status": "ready",
                    "venv_dir": str(venv_dir),
                    "python": str(python_path),
                    "python_version": list(_python_pair(python_path) or ()),
                    "mode": mode,
                    "requirements": str(Path(__file__).resolve().parent.parent / "requirements.txt"),
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    command_spec = COMMANDS[args.command]
    assert command_spec is not None
    script_name, prefix_args = command_spec
    target = Path(__file__).resolve().parent / script_name
    env = os.environ.copy()
    env["CAD_AI_RENDERER_MANAGED_VENV"] = str(venv_dir)
    env["CAD_AI_RENDERER_VENV_MODE"] = mode
    env.setdefault("VTK_DEFAULT_RENDER_WINDOW_OFFSCREEN", "1")
    command = [str(python_path), str(target), *prefix_args, *remainder]
    return subprocess.run(command, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
