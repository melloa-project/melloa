#!/usr/bin/env bash

# Shared, side-effect-free helpers for the Melloa server host-toolchain policy.
# Callers deliberately supply every path so this file cannot redirect a privileged
# command through ambient environment variables.

melloa_normalize_version() {
  local version="$1"
  local major
  local minor
  local patch

  version="${version#v}"
  version="${version#go}"
  version="${version%%+*}"
  version="${version%%-*}"
  [[ "$version" =~ ^([0-9]+)(\.([0-9]+))?(\.([0-9]+))?$ ]] || return 1
  major="${BASH_REMATCH[1]}"
  minor="${BASH_REMATCH[3]:-0}"
  patch="${BASH_REMATCH[5]:-0}"
  printf '%d.%d.%d\n' "$((10#$major))" "$((10#$minor))" "$((10#$patch))"
}

melloa_version_at_least() {
  local actual
  local required
  local actual_major
  local actual_minor
  local actual_patch
  local required_major
  local required_minor
  local required_patch

  actual="$(melloa_normalize_version "$1")" || return 1
  required="$(melloa_normalize_version "$2")" || return 1
  IFS=. read -r actual_major actual_minor actual_patch <<<"$actual"
  IFS=. read -r required_major required_minor required_patch <<<"$required"

  if ((actual_major != required_major)); then
    ((actual_major > required_major))
    return
  fi
  if ((actual_minor != required_minor)); then
    ((actual_minor > required_minor))
    return
  fi
  ((actual_patch >= required_patch))
}

melloa_python_version_is_supported() {
  local normalized
  local major

  normalized="$(melloa_normalize_version "$1")" || return 1
  major="${normalized%%.*}"
  [[ "$major" == 3 ]] && melloa_version_at_least "$normalized" "$2"
}

melloa_runtime_path() {
  local toolchain_bin="$1"
  [[ "$toolchain_bin" == /* ]] || return 1
  printf '%s:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin' \
    "$toolchain_bin"
}

melloa_find_host_command() {
  local host_path="$1"
  local name="$2"
  local command_path

  command_path="$(PATH="$host_path" command -v "$name" 2>/dev/null || true)"
  [[ "$command_path" == /* && -x "$command_path" ]] || return 1
  printf '%s\n' "$command_path"
}

melloa_link_tool() {
  local toolchain_bin="$1"
  local name="$2"
  local source="$3"
  local target

  [[ "$toolchain_bin" == /* && "$name" =~ ^[A-Za-z0-9._+-]+$ && \
    "$source" == /* && -x "$source" ]] || return 1
  install -d -m 0755 "$toolchain_bin"
  target="$toolchain_bin/$name"
  if [[ -e "$target" || -L "$target" ]]; then
    [[ -L "$target" ]] || return 1
  fi
  ln --symbolic --force --no-dereference "$source" "$target"
  [[ -L "$target" && "$(readlink -- "$target")" == "$source" ]]
}

melloa_tool_link_is_usable() {
  local toolchain_bin="$1"
  local name="$2"
  local target="$toolchain_bin/$name"
  local source

  [[ "$toolchain_bin" == /* && "$name" =~ ^[A-Za-z0-9._+-]+$ && -L "$target" ]] ||
    return 1
  source="$(readlink -- "$target")"
  [[ "$source" == /* && -x "$source" ]]
}

melloa_docker_apt_source_exists() {
  local source_root="$1"
  local host_os="$2"
  local codename="$3"
  local apt_directory
  local expected_uri="https://download.docker.com/linux/$host_os"
  local source_file

  [[ "$source_root" == /* && "$host_os" =~ ^[a-z]+$ && "$codename" =~ ^[a-z0-9.-]+$ ]] ||
    return 1
  if [[ "$source_root" == / ]]; then
    apt_directory=/etc/apt
  else
    apt_directory="$source_root/etc/apt"
  fi

  for source_file in \
    "$apt_directory/sources.list" \
    "$apt_directory/sources.list.d"/*.list \
    "$apt_directory/sources.list.d"/*.sources; do
    [[ -f "$source_file" && ! -L "$source_file" ]] || continue
    if [[ "$source_file" == *.sources ]]; then
      if awk -v expected_uri="$expected_uri" -v expected_suite="$codename" '
        BEGIN { RS=""; FS="\n" }
        {
          has_type = has_uri = has_suite = has_component = 0
          for (line_number = 1; line_number <= NF; line_number += 1) {
            line = $line_number
            if (line ~ /^[[:space:]]*Types:[[:space:]]*/) {
              sub(/^[[:space:]]*Types:[[:space:]]*/, "", line)
              if (line ~ /(^|[[:space:]])deb([[:space:]]|$)/) has_type = 1
            } else if (line ~ /^[[:space:]]*URIs:[[:space:]]*/) {
              sub(/^[[:space:]]*URIs:[[:space:]]*/, "", line)
              if (line == expected_uri) has_uri = 1
            } else if (line ~ /^[[:space:]]*Suites:[[:space:]]*/) {
              sub(/^[[:space:]]*Suites:[[:space:]]*/, "", line)
              if (line ~ ("(^|[[:space:]])" expected_suite "([[:space:]]|$)")) has_suite = 1
            } else if (line ~ /^[[:space:]]*Components:[[:space:]]*/) {
              sub(/^[[:space:]]*Components:[[:space:]]*/, "", line)
              if (line ~ /(^|[[:space:]])stable([[:space:]]|$)/) has_component = 1
            }
          }
          if (has_type && has_uri && has_suite && has_component) found = 1
        }
        END { exit(found ? 0 : 1) }
      ' "$source_file"; then
        return 0
      fi
    elif awk -v expected_uri="$expected_uri" -v expected_suite="$codename" '
      /^[[:space:]]*deb[[:space:]]/ {
        line = $0
        sub(/^[[:space:]]*deb[[:space:]]+/, "", line)
        if (line ~ /^\[[^]]+\][[:space:]]+/) sub(/^\[[^]]+\][[:space:]]+/, "", line)
        field_count = split(line, fields, /[[:space:]]+/)
        if (field_count < 3 || fields[1] != expected_uri || fields[2] != expected_suite) next
        for (field_number = 3; field_number <= field_count; field_number += 1) {
          if (fields[field_number] == "stable") found = 1
        }
      }
      END { exit(found ? 0 : 1) }
    ' "$source_file"; then
      return 0
    fi
  done
  return 1
}
