"""Owner-invoked orchestration for the disposable local product preview.

This process may invoke the separately built Guardian CLI to create temporary
preview state. It never passes the Guardian private key, journal, lock, or a
mutation command to the Melloa core.
"""

from __future__ import annotations

import argparse
import os
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import IO, NoReturn
from urllib.error import HTTPError, URLError
from urllib.request import urlopen

from melloa.adapters.guardian.file import FileGuardianStatusReader
from melloa.adapters.models.openai_compatible import (
    OpenAICompatibleModelGateway,
    OpenAICompatibleRouteConfig,
    load_openai_compatible_route_config,
)
from melloa.domain.models import ModelRouteHealthState, ProcessingLocation
from melloa.release import CURRENT_RELEASE

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GUARDIAN_ROOT = ROOT.parent / "melloa-guardian"
_STATE_MARKER = ".melloa-local-preview"


class PreviewError(RuntimeError):
    """The local preview cannot start or remain healthy."""


@dataclass(frozen=True)
class PreviewPaths:
    root: Path
    owner_credential: Path
    guardian_status: Path
    guardian_audit: Path
    guardian_private_key: Path
    guardian_public_key: Path
    guardian_lock: Path
    core_log: Path
    web_log: Path


@dataclass
class ManagedProcess:
    name: str
    process: subprocess.Popen[bytes]
    log: IO[bytes]
    log_path: Path


def _paths(root: Path) -> PreviewPaths:
    return PreviewPaths(
        root=root,
        owner_credential=root / "owner-credential",
        guardian_status=root / "guardian-status.json",
        guardian_audit=root / "guardian-audit.jsonl",
        guardian_private_key=root / "guardian-private.pem",
        guardian_public_key=root / "guardian-public.pem",
        guardian_lock=root / "guardian.lock",
        core_log=root / "core.log",
        web_log=root / "owner-console.log",
    )


def _write_private(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(descriptor, value.encode("utf-8"))
    finally:
        os.close(descriptor)


def create_preview_state(requested_root: Path | None = None) -> tuple[PreviewPaths, str]:
    if requested_root is None:
        root = Path(tempfile.mkdtemp(prefix="melloa-preview-"))
    else:
        root = requested_root.expanduser().resolve()
        try:
            root.mkdir(mode=0o700)
        except FileExistsError as error:
            raise PreviewError(f"preview state path already exists: {root}") from error
        except OSError as error:
            raise PreviewError(f"preview state path could not be created: {root}") from error
    try:
        root.chmod(0o700)
        paths = _paths(root)
        credential = secrets.token_urlsafe(32)
        _write_private(root / _STATE_MARKER, "disposable Melloa local preview\n")
        _write_private(paths.owner_credential, f"{credential}\n")
    except OSError as error:
        shutil.rmtree(root, ignore_errors=True)
        raise PreviewError("private preview state could not be initialized") from error
    return paths, credential


def remove_preview_state(paths: PreviewPaths) -> None:
    marker = paths.root / _STATE_MARKER
    if not marker.is_file():
        raise PreviewError(f"refusing to remove unmarked preview state: {paths.root}")
    shutil.rmtree(paths.root)


def guardian_commands(binary: Path, paths: PreviewPaths) -> tuple[tuple[str, ...], ...]:
    flags = (
        "--status-file",
        str(paths.guardian_status),
        "--audit-file",
        str(paths.guardian_audit),
        "--private-key-file",
        str(paths.guardian_private_key),
        "--public-key-file",
        str(paths.guardian_public_key),
        "--lock-file",
        str(paths.guardian_lock),
    )
    return (
        (
            str(binary),
            "init",
            "--instance-id",
            "local-preview-guardian",
            "--key-id",
            "guardian.status-v1",
            *flags,
        ),
        (
            str(binary),
            "transition",
            "--mode",
            "offline",
            "--reason",
            "owner.local_preview",
            *flags,
        ),
    )


def initialize_guardian(
    binary: Path,
    paths: PreviewPaths,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    for command in guardian_commands(binary, paths):
        try:
            runner(command, check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError) as error:
            detail = ""
            if isinstance(error, subprocess.CalledProcessError) and error.stderr:
                detail = f": {error.stderr.strip().splitlines()[-1]}"
            raise PreviewError(f"Guardian preview setup failed{detail}") from error
    try:
        verified = FileGuardianStatusReader(
            paths.guardian_status,
            paths.guardian_public_key,
        ).read_status()
    except (OSError, ValueError) as error:
        raise PreviewError("Guardian signed preview status could not be verified") from error
    if verified.payload.mode.value != "offline":
        raise PreviewError("Guardian preview did not enter the required offline mode")


def core_command(
    paths: PreviewPaths,
    port: int,
    model_route_config: Path | None = None,
) -> tuple[str, ...]:
    command = (
        sys.executable,
        "-m",
        "melloa.apps.cli",
        "serve",
        "--status",
        str(paths.guardian_status),
        "--public-key",
        str(paths.guardian_public_key),
        "--owner-credential-file",
        str(paths.owner_credential),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    )
    if model_route_config is None:
        return command
    return (*command, "--model-route-config", str(model_route_config))


def load_preview_model_route(path: Path) -> tuple[Path, OpenAICompatibleRouteConfig]:
    resolved = _required_file(
        path.expanduser(),
        "Local model route config is not a readable regular file.",
    )
    try:
        config = load_openai_compatible_route_config(resolved)
    except (OSError, ValueError) as error:
        raise PreviewError("Local model route config could not be validated.") from error
    if config.processing_location is not ProcessingLocation.DEVICE:
        raise PreviewError("Local preview accepts only a DEVICE model route config.")
    return resolved, config


def preflight_model_route(config: OpenAICompatibleRouteConfig) -> None:
    health = OpenAICompatibleModelGateway(config).health()
    if health.state is ModelRouteHealthState.HEALTHY:
        return
    if config.provider_id == "provider.ollama-local":
        raise PreviewError(
            "The configured on-device Ollama model is not ready. Run `ollama serve` "
            f"and `ollama pull {config.model_id}`, then retry "
            f"(reason: {health.reason_code})."
        )
    raise PreviewError(
        f"The configured on-device model is not ready (reason: {health.reason_code})."
    )


def preview_contract(config: OpenAICompatibleRouteConfig | None) -> str:
    if config is None:
        return (
            "Preview contract: loopback only · signed Guardian offline · no external "
            "model calls · process-local disposable state · guided output is not Melli."
        )
    return (
        "Preview contract: loopback services · signed Guardian offline · owner text and "
        f"selected memory go to the on-device {config.display_name} model "
        f"({config.model_id}) · no external disclosure · process-local disposable state."
    )


def preview_next_action(config: OpenAICompatibleRouteConfig | None) -> str:
    if config is None:
        return (
            "Open the console and paste the credential to inspect private access and data "
            "controls. No model is configured, so conversation is unavailable in this launch."
        )
    return (
        "Open the console, paste the credential, and start a conversation naturally. "
        'After Melli replies, use "Why this answer?" when the context or privacy '
        "behind the answer matters."
    )


def web_command(node: Path) -> tuple[str, ...]:
    return (str(node), str(ROOT / "apps/web/server.mjs"))


def validate_node(
    node: Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> None:
    try:
        result = runner(
            (str(node), "--version"),
            check=True,
            capture_output=True,
            text=True,
        )
        major = int(result.stdout.strip().removeprefix("v").split(".", 1)[0])
    except (OSError, subprocess.CalledProcessError, ValueError) as error:
        raise PreviewError("Node.js version could not be verified") from error
    if major < 22:
        raise PreviewError(f"Node.js 22 or newer is required; found major version {major}")


def _start_process(
    name: str,
    command: Sequence[str],
    log_path: Path,
    *,
    environment: dict[str, str] | None = None,
) -> ManagedProcess:
    log = log_path.open("xb")
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed executables and argv, no shell
            command,
            cwd=ROOT,
            env=environment,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    except OSError as error:
        log.close()
        raise PreviewError(f"{name} could not start: {error}") from error
    return ManagedProcess(name=name, process=process, log=log, log_path=log_path)


def _log_tail(path: Path, *, maximum_lines: int = 12) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return "\n".join(lines[-maximum_lines:])


def wait_for_endpoint(
    url: str,
    process: ManagedProcess,
    *,
    timeout_seconds: float,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "not reachable"
    while time.monotonic() < deadline:
        return_code = process.process.poll()
        if return_code is not None:
            tail = _log_tail(process.log_path)
            suffix = "" if not tail else f"\n{tail}"
            raise PreviewError(
                f"{process.name} exited before it became ready (status {return_code}){suffix}"
            )
        try:
            with urlopen(url, timeout=0.5) as response:  # noqa: S310 - fixed loopback URLs
                if response.status < 500:
                    return
                last_error = f"HTTP {response.status}"
        except HTTPError as error:
            last_error = f"HTTP {error.code}"
        except (TimeoutError, URLError, OSError) as error:
            last_error = str(error.reason) if isinstance(error, URLError) else str(error)
        time.sleep(0.1)
    tail = _log_tail(process.log_path)
    suffix = "" if not tail else f"\n{tail}"
    raise PreviewError(
        f"{process.name} did not become ready at {url}: {last_error}{suffix}"
    )


def _stop_process(process: ManagedProcess) -> None:
    if process.process.poll() is None:
        try:
            os.killpg(process.process.pid, signal.SIGTERM)
            process.process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            if process.process.poll() is None:
                try:
                    os.killpg(process.process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.process.wait(timeout=5)
    process.log.close()


def _monitor(processes: Sequence[ManagedProcess]) -> NoReturn:
    while True:
        for process in processes:
            return_code = process.process.poll()
            if return_code is not None:
                tail = _log_tail(process.log_path)
                suffix = "" if not tail else f"\n{tail}"
                raise PreviewError(
                    f"{process.name} stopped unexpectedly (status {return_code}){suffix}"
                )
        time.sleep(0.5)


def _required_file(path: Path, message: str) -> Path:
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise PreviewError(message) from error
    if not resolved.is_file():
        raise PreviewError(message)
    return resolved


def _validate_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def run_preview(args: argparse.Namespace) -> int:
    route_paths = tuple(getattr(args, "model_route_config", ()))
    if len(route_paths) > 1:
        raise PreviewError("Local preview accepts at most one model route config.")
    model_route_path: Path | None = None
    model_route_config: OpenAICompatibleRouteConfig | None = None
    if route_paths:
        model_route_path, model_route_config = load_preview_model_route(route_paths[0])
        preflight_model_route(model_route_config)

    guardian_root = args.guardian_root.expanduser().resolve()
    guardian_binary = _required_file(
        guardian_root / "bin/guardianctl",
        "Guardian is not built. Run `make -C ../melloa-guardian check build` and retry.",
    )
    if not os.access(guardian_binary, os.X_OK):
        raise PreviewError(f"Guardian binary is not executable: {guardian_binary}")
    _required_file(
        ROOT / "apps/web/dist/index.html",
        "Owner Console is not built. Run `npm --prefix apps/web run build` and retry.",
    )
    node_value = shutil.which("node")
    if node_value is None:
        raise PreviewError("Node.js 22 or newer is required to serve the Owner Console.")
    node = Path(node_value).resolve(strict=True)
    validate_node(node)

    paths: PreviewPaths | None = None
    processes: list[ManagedProcess] = []
    try:
        paths, credential = create_preview_state(args.state_dir)
        print("Preparing signed offline Guardian state…", flush=True)
        initialize_guardian(guardian_binary, paths)

        core = _start_process(
            "Melloa core",
            core_command(paths, args.core_port, model_route_path),
            paths.core_log,
        )
        processes.append(core)
        wait_for_endpoint(
            f"http://127.0.0.1:{args.core_port}/health/ready",
            core,
            timeout_seconds=args.startup_timeout,
        )

        web_environment = dict(os.environ)
        web_environment.update(
            {
                "MELLOA_CORE_URL": f"http://127.0.0.1:{args.core_port}",
                "MELLOA_WEB_PORT": str(args.web_port),
            }
        )
        web = _start_process(
            "Owner Console",
            web_command(node),
            paths.web_log,
            environment=web_environment,
        )
        processes.append(web)
        console_url = f"http://127.0.0.1:{args.web_port}"
        wait_for_endpoint(console_url, web, timeout_seconds=args.startup_timeout)

        print(
            "\nMelloa is ready.\n"
            f"\n  Release:           {CURRENT_RELEASE.release_display}"
            f"\n  Owner Console:     {console_url}"
            f"\n  Owner credential:  {credential}"
            f"\n\n{preview_next_action(model_route_config)}"
            f"\n\n{preview_contract(model_route_config)}"
            "\nPress Ctrl-C to stop both services and delete the credential and preview state.\n",
            flush=True,
        )
        _monitor(processes)
    except KeyboardInterrupt:
        print("\nStopping Melloa…", flush=True)
        return 0
    finally:
        for process in reversed(processes):
            _stop_process(process)
        if paths is not None and paths.root.exists():
            remove_preview_state(paths)
            print("Disposable preview state removed.", flush=True)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="melloa-local-preview",
        description="Start the complete disposable Melloa Owner Console journey.",
    )
    parser.add_argument(
        "--guardian-root",
        type=Path,
        default=DEFAULT_GUARDIAN_ROOT,
        help="Path to the independently built melloa-guardian checkout.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Create preview state at this new path instead of a secure temporary path.",
    )
    parser.add_argument(
        "--model-route-config",
        type=Path,
        action="append",
        default=[],
        help="Use one OpenAI-compatible DEVICE route after an exact-model preflight.",
    )
    parser.add_argument("--core-port", type=_validate_port, default=8000)
    parser.add_argument("--web-port", type=_validate_port, default=8787)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    return parser


def _signal_as_interrupt(signum: int, _frame: FrameType | None) -> None:
    # Process supervisors can deliver SIGTERM directly and then forward it to
    # the child. Treat shutdown as a one-shot request so a duplicate cannot
    # interrupt child termination or disposable-state removal.
    signal.signal(signum, signal.SIG_IGN)
    raise KeyboardInterrupt


def main() -> None:
    args = build_parser().parse_args()
    previous_term = signal.signal(signal.SIGTERM, _signal_as_interrupt)
    try:
        try:
            result = run_preview(args)
        except PreviewError as error:
            print(f"Melloa preview could not start: {error}", file=sys.stderr)
            result = 2
    finally:
        signal.signal(signal.SIGTERM, previous_term)
    raise SystemExit(result)


if __name__ == "__main__":
    main()
