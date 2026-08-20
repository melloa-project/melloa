#!/usr/bin/env bash
set -euo pipefail

umask 077

readonly ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SOURCE="$ROOT"
ORIGIN="https://github.com/melloa-project/melloa.git"
DESTINATION_ROOT=/

usage() {
  cat >&2 <<'EOF'
Usage: infra/server/install.sh [--source PATH] [--origin HTTPS_URL] [--root PATH]

Without --root, installs host worker assets and systemd units but does not start services.
A non-root --root stages only the immutable files for packaging tests.
EOF
  exit 2
}

while (($#)); do
  case "$1" in
    --source)
      [[ $# -ge 2 ]] || usage
      SOURCE="$2"
      shift 2
      ;;
    --origin)
      [[ $# -ge 2 ]] || usage
      ORIGIN="$2"
      shift 2
      ;;
    --root)
      [[ $# -ge 2 ]] || usage
      DESTINATION_ROOT="$2"
      shift 2
      ;;
    *)
      usage
      ;;
  esac
done

fail() {
  echo "Server installation failed: $1" >&2
  exit 1
}

destination() {
  local path="$1"
  if [[ "$DESTINATION_ROOT" == / ]]; then
    printf '%s' "$path"
  else
    printf '%s%s' "$DESTINATION_ROOT" "$path"
  fi
}

install_if_absent() {
  local source="$1"
  local target="$2"
  local mode="$3"
  if [[ -e "$target" || -L "$target" ]]; then
    [[ -f "$target" && ! -L "$target" ]] || fail "existing configuration path is unsafe: $target"
    return 0
  fi
  install -m "$mode" "$source" "$target"
}

[[ "$SOURCE" == /* && -d "$SOURCE" && ! -L "$SOURCE" ]] || fail "source must be an absolute directory"
[[ "$DESTINATION_ROOT" == /* ]] || fail "installation root must be absolute"
if [[ -e "$DESTINATION_ROOT" && ( ! -d "$DESTINATION_ROOT" || -L "$DESTINATION_ROOT" ) ]]; then
  fail "installation root must be a directory, not a symlink"
fi
if [[ "$DESTINATION_ROOT" == / ]]; then
  ((EUID == 0)) || fail "installation must run as root"
  "$SOURCE/infra/server/preflight.sh" --source "$SOURCE" --origin "$ORIGIN"
fi

readonly LIBEXEC_DIR="$(destination /usr/local/libexec/melloa)"
readonly SYSTEMD_DIR="$(destination /etc/systemd/system)"
readonly CONFIG_DIR="$(destination /etc/melloa)"
readonly PRIVATE_DIR="$(destination /etc/melloa/private)"
readonly WORKER_DIR="$(destination /opt/melloa/worker)"
readonly APPLIER_HOME="$(destination /var/lib/melloa/applier-home)"
readonly SOURCE_REVISION="$(git -C "$SOURCE" rev-parse HEAD)"

[[ "$SOURCE_REVISION" =~ ^[0-9a-f]{40}$ ]] || fail "source revision is invalid"

install -d -m 0755 "$LIBEXEC_DIR" "$SYSTEMD_DIR"
install -d -m 0700 "$CONFIG_DIR" "$PRIVATE_DIR" "$WORKER_DIR" "$APPLIER_HOME"
install -m 0755 "$SOURCE/infra/server/codex-wrapper.sh" "$LIBEXEC_DIR/codex"
install -m 0755 "$SOURCE/infra/server/self-change-plan.sh" "$LIBEXEC_DIR/self-change-plan"
install -m 0755 "$SOURCE/infra/server/self-change-apply.sh" "$LIBEXEC_DIR/self-change-apply"
install -m 0755 "$SOURCE/tools/self_change_verify.sh" "$LIBEXEC_DIR/self-change-verify"
for unit in "$SOURCE"/infra/server/systemd/*.service; do
  install -m 0644 "$unit" "$SYSTEMD_DIR/$(basename "$unit")"
done
install_if_absent "$SOURCE/infra/server/server.env.example" "$CONFIG_DIR/server.env" 0600
install_if_absent "$SOURCE/infra/server/self-change.env.example" "$CONFIG_DIR/self-change.env" 0600
install_if_absent /dev/null "$CONFIG_DIR/release.env" 0600
install_if_absent /dev/null "$PRIVATE_DIR/codex-api-key" 0600
install_if_absent /dev/null "$PRIVATE_DIR/git-credentials" 0600
install -m 0600 "$SOURCE/infra/server/applier.gitconfig" "$APPLIER_HOME/.gitconfig"

WORKER_SOURCE="$(mktemp -d /tmp/melloa-worker-source.XXXXXX)"
cleanup_worker_source() {
  if [[ "$WORKER_SOURCE" == /tmp/melloa-worker-source.* && -d "$WORKER_SOURCE" ]]; then
    rm -rf -- "$WORKER_SOURCE"
  fi
}
trap cleanup_worker_source EXIT HUP INT TERM

git -C "$SOURCE" archive --format=tar "$SOURCE_REVISION" \
  README.md pyproject.toml uv.lock src migrations |
  tar --extract --directory "$WORKER_SOURCE" --no-same-owner
[[ -z "$(find "$WORKER_SOURCE" -type l -print -quit)" ]] ||
  fail "worker source must not contain symlinks"
install -m 0644 "$WORKER_SOURCE/pyproject.toml" "$WORKER_DIR/pyproject.toml"
install -m 0644 "$WORKER_SOURCE/uv.lock" "$WORKER_DIR/uv.lock"
install -m 0644 "$WORKER_SOURCE/README.md" "$WORKER_DIR/README.md"
install -d -m 0755 "$WORKER_DIR/src" "$WORKER_DIR/migrations"
rsync --archive --delete --no-owner --no-group --chmod=D0755,F0644 \
  "$WORKER_SOURCE/src/" "$WORKER_DIR/src/"
rsync --archive --delete --no-owner --no-group --chmod=D0755,F0644 \
  "$WORKER_SOURCE/migrations/" "$WORKER_DIR/migrations/"
cleanup_worker_source
trap - EXIT HUP INT TERM

if [[ "$DESTINATION_ROOT" != / ]]; then
  echo "Server service assets staged below $DESTINATION_ROOT."
  exit 0
fi

if ! id melloa-codex >/dev/null 2>&1; then
  useradd \
    --system \
    --user-group \
    --home-dir /var/lib/melloa/codex-agent \
    --shell /usr/sbin/nologin \
    melloa-codex
fi
readonly CODEX_UID="$(id -u melloa-codex)"
readonly CODEX_GID="$(id -g melloa-codex)"
[[ "$CODEX_UID" =~ ^[1-9][0-9]*$ && "$CODEX_GID" =~ ^[1-9][0-9]*$ ]] ||
  fail "melloa-codex must be a non-root identity"

install -d -m 0755 /opt/melloa /srv/melloa /var/lib/melloa
install -d -m 0700 \
  /opt/melloa/verifier \
  /var/lib/melloa/applying-work \
  /var/lib/melloa/planning-work \
  /var/lib/melloa/runtime-state
install -d -m 0711 /var/lib/melloa/release-state
install -d -o "$CODEX_UID" -g "$CODEX_GID" -m 0700 \
  /var/lib/melloa/codex-agent \
  /var/lib/melloa/codex-agent/codex
chown -R root:root /opt/melloa/worker /var/lib/melloa/applier-home

prepare_repository() {
  local repository="$1"
  if [[ ! -e "$repository" ]]; then
    git clone --no-tags --branch main --origin origin "$ORIGIN" "$repository"
  fi
  [[ -d "$repository/.git" && ! -L "$repository" && ! -L "$repository/.git" ]] ||
    fail "managed repository is invalid: $repository"
  [[ "$(git -C "$repository" remote get-url origin)" == "$ORIGIN" ]] ||
    fail "managed repository has the wrong origin: $repository"
  [[ -z "$(git -C "$repository" status --porcelain --untracked-files=normal)" ]] ||
    fail "managed repository is dirty: $repository"
  git -C "$repository" fetch --quiet --no-tags origin main
  [[ "$(git -C "$repository" rev-parse refs/remotes/origin/main)" == "$SOURCE_REVISION" ]] ||
    fail "managed repository and installer source are at different revisions"
  [[ "$(git -C "$repository" symbolic-ref --quiet --short HEAD)" == main ]] ||
    fail "managed repository must have main checked out: $repository"
  git -C "$repository" reset --quiet --hard "$SOURCE_REVISION"
  [[ "$(git -C "$repository" rev-parse HEAD)" == "$SOURCE_REVISION" ]] ||
    fail "managed repository checkout has the wrong revision: $repository"
}

prepare_repository /srv/melloa/planning-source
prepare_repository /srv/melloa/release-source

UV_PROJECT_ENVIRONMENT=/opt/melloa/worker/.venv \
UV_NO_PROGRESS=1 \
UV_SYSTEM_CERTS=1 \
  uv sync --frozen --no-dev --project /opt/melloa/worker

UV_PROJECT_ENVIRONMENT=/opt/melloa/verifier/.venv \
UV_NO_PROGRESS=1 \
UV_SYSTEM_CERTS=1 \
  uv sync --frozen --all-groups --no-install-project --project "$SOURCE"
install -m 0644 "$SOURCE/apps/web/package.json" /opt/melloa/verifier/package.json
install -m 0644 "$SOURCE/apps/web/package-lock.json" /opt/melloa/verifier/package-lock.json
npm --prefix /opt/melloa/verifier ci --ignore-scripts

systemd-analyze verify \
  /etc/systemd/system/melloa-release-recovery.service \
  /etc/systemd/system/melloa-self-change-planner.service \
  /etc/systemd/system/melloa-self-change-applier.service
systemctl daemon-reload

echo "Server services installed but not started. Complete private configuration, then run:"
echo "  sudo infra/server/preflight.sh --source $SOURCE --origin $ORIGIN --installed"
