"""Owner-invoked orchestration for the disposable local product preview.

Guardian state is an owner-supplied, read-only input. This process verifies the
signed projection but does not initialize, transition, or remove Guardian state.
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

from melloa.adapters.guardian.file import (
    FileGuardianStatusReader,
    GuardianVerificationError,
)
from melloa.adapters.models.openai_compatible import (
    OpenAICompatibleModelConfig,
    OpenAICompatibleModelGateway,
    load_openai_compatible_model_config,
)
from melloa.domain.guardian import GuardianMode
from melloa.domain.models import ModelHealthState, ProcessingLocation
from melloa.release import CURRENT_RELEASE

ROOT = Path(__file__).resolve().parents[3]
_STATE_MARKER = ".melloa-local-preview"


class PreviewError(RuntimeError):
    """The local preview cannot start or remain healthy."""


@dataclass(frozen=True)
class PreviewPaths:
    root: Path
    owner_credential: Path
    core_log: Path
    web_log: Path


@dataclass(frozen=True)
class GuardianHandoff:
    status: Path
    public_key: Path
    receipt_hash: str


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


def validate_guardian_projection(
    status_path: Path,
    public_key_path: Path,
) -> GuardianHandoff:
    status = Path(os.path.abspath(status_path.expanduser()))
    public_key = Path(os.path.abspath(public_key_path.expanduser()))
    try:
        verified = FileGuardianStatusReader(status, public_key).read_status()
    except GuardianVerificationError as error:
        raise PreviewError(f"Guardian signed status was rejected: {error}") from error
    if verified.payload.mode is not GuardianMode.OFFLINE:
        raise PreviewError("Guardian status must already be in offline mode")
    return GuardianHandoff(
        status=status,
        public_key=public_key,
        receipt_hash=verified.receipt_hash,
    )


def verify_guardian_handoff(args: argparse.Namespace) -> int:
    guardian = validate_guardian_projection(
        args.guardian_status,
        args.guardian_public_key,
    )
    print(
        "Guardian handoff verified offline "
        f"(receipt {guardian.receipt_hash}).",
        flush=True,
    )
    return 0


def core_command(
    paths: PreviewPaths,
    guardian: GuardianHandoff,
    port: int,
    model_config: Path | None = None,
) -> tuple[str, ...]:
    command = (
        sys.executable,
        "-m",
        "melloa.apps.cli",
        "serve",
        "--status",
        str(guardian.status),
        "--public-key",
        str(guardian.public_key),
        "--expected-guardian-receipt",
        guardian.receipt_hash,
        "--owner-credential-file",
        str(paths.owner_credential),
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
    )
    if model_config is None:
        return command
    return (*command, "--model-config", str(model_config))


def load_preview_model(path: Path) -> tuple[Path, OpenAICompatibleModelConfig]:
    resolved = _required_file(
        path.expanduser(),
        "Local model config is not a readable regular file.",
    )
    try:
        config = load_openai_compatible_model_config(resolved)
    except (OSError, ValueError) as error:
        raise PreviewError("Local model config could not be validated.") from error
    if config.processing_location is not ProcessingLocation.DEVICE:
        raise PreviewError("Local preview accepts only an on-device model.")
    return resolved, config


def preflight_model(config: OpenAICompatibleModelConfig) -> None:
    health = OpenAICompatibleModelGateway(config).health()
    if health.state is ModelHealthState.HEALTHY:
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


def preview_contract(config: OpenAICompatibleModelConfig | None) -> str:
    if config is None:
        return (
            "Preview contract: loopback only · Guardian verified offline at launch · "
            "no external model calls · process-local disposable state · "
            "conversation unavailable."
        )
    return (
        "Preview contract: loopback services · Guardian verified offline at launch · "
        f"owner text and selected memory go to the on-device {config.display_name} model "
        f"({config.model_id}) · no external disclosure · process-local disposable state."
    )


def preview_next_action(config: OpenAICompatibleModelConfig | None) -> str:
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
    model_paths = tuple(getattr(args, "model_config", ()))
    if len(model_paths) > 1:
        raise PreviewError("Local preview accepts at most one model config.")
    model_path: Path | None = None
    model_config: OpenAICompatibleModelConfig | None = None
    if model_paths:
        model_path, model_config = load_preview_model(model_paths[0])
        preflight_model(model_config)

    guardian = validate_guardian_projection(
        args.guardian_status,
        args.guardian_public_key,
    )
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

        core = _start_process(
            "Melloa core",
            core_command(
                paths,
                guardian,
                args.core_port,
                model_path,
            ),
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
            f"\n\n{preview_next_action(model_config)}"
            f"\n\n{preview_contract(model_config)}"
            "\nPress Ctrl-C to stop both services and delete only Melloa's "
            "credential and logs. Guardian state remains owner-managed.\n",
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
            print(
                "Melloa's disposable credential and logs were removed; "
                "Guardian state was not changed.",
                flush=True,
            )
            print(
                "From the Guardian checkout, run `make preview-state-clean` "
                "when this public handoff is no longer needed.",
                flush=True,
            )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="melloa-local-preview",
        description="Start the complete disposable Melloa Owner Console journey.",
    )
    parser.add_argument(
        "--guardian-status",
        dest="guardian_status",
        type=Path,
        required=True,
        help="Path to the owner-supplied signed Guardian status projection.",
    )
    parser.add_argument(
        "--guardian-public-key",
        dest="guardian_public_key",
        type=Path,
        required=True,
        help="Path to the owner-supplied Guardian verification key.",
    )
    parser.add_argument(
        "--state-dir",
        type=Path,
        default=None,
        help="Create preview state at this new path instead of a secure temporary path.",
    )
    parser.add_argument(
        "--verify-guardian-only",
        action="store_true",
        help="Verify the signed offline Guardian handoff, then exit.",
    )
    parser.add_argument(
        "--model-config",
        type=Path,
        action="append",
        default=[],
        help="Use one OpenAI-compatible on-device model after an exact-model preflight.",
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
            result = (
                verify_guardian_handoff(args)
                if args.verify_guardian_only
                else run_preview(args)
            )
        except PreviewError as error:
            print(f"Melloa preview could not start: {error}", file=sys.stderr)
            result = 2
    finally:
        signal.signal(signal.SIGTERM, previous_term)
    raise SystemExit(result)


if __name__ == "__main__":
    main()
