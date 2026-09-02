# Shared helpers for the presentation scripts.

demo_lib_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# Needed by demo_host_for; absent for a local run, which is the "local" case.
# DEMO_LOCAL=1 ignores a generated aws.env and keeps everything on this machine.
if [ "${DEMO_LOCAL:-0}" != "1" ] && [ -f "$demo_lib_dir/aws.env" ]; then
  # shellcheck source=/dev/null
  . "$demo_lib_dir/aws.env"
fi

DEMO_PROMPT=${DEMO_PROMPT:-"$ "}
DEMO_RULE_WIDTH=${DEMO_RULE_WIDTH:-72}

if [ -t 1 ]; then
  _dim=$'\033[2m'
  _bold=$'\033[1m'
  _cyan=$'\033[36m'
  _green=$'\033[32m'
  _reset=$'\033[0m'
else
  _dim=""
  _bold=""
  _cyan=""
  _green=""
  _reset=""
fi

demo_pause() {
  if [ -t 0 ]; then read -rs || true; fi
}

demo_done() {
  printf '\n%s%sDONE%s\n' "${_bold}" "${_green}" "${_reset}"
}

# Projector-facing name for a role. Never include the SSH target / IP.
demo_role_label() {
  case "$1" in
    app) echo "Application host" ;;
    data) echo "Data host" ;;
    models) echo "Models host" ;;
    *) echo "$1 host" ;;
  esac
}

demo_host_for() {
  case "$1" in
    data) echo "${DEMO_HOST_DATA:-}" ;;
    models) echo "${DEMO_HOST_MODELS:-}" ;;
    app) echo "${DEMO_HOST_APP:-}" ;;
  esac
}

# Run one command on every distinct host, labelled by the roles it carries.
# Roles sharing a host (the whole local run) collapse into one block.
demo_run_all_nopause() {
  local seen="" role key labels other other_key

  printf '%s%s%s%s\n' "${_cyan}" "$DEMO_PROMPT" "$*" "${_reset}"

  for role in app data models; do
    key=$(demo_host_for "$role")
    key=${key:-local}

    case " $seen " in
      *" $key "*) continue ;;
    esac
    seen="$seen $key"

    labels=""
    for other in app data models; do
      other_key=$(demo_host_for "$other")
      if [ "${other_key:-local}" = "$key" ]; then
        labels="${labels:+$labels, }$(demo_role_label "$other")"
      fi
    done

    printf '\n%s== %s%s\n' "${_bold}" "$labels" "${_reset}"
    DEMO_QUIET=1 "$demo_lib_dir/run.sh" "$role" "$@" < /dev/null
  done

  demo_done
}

demo_run_all() {
  demo_run_all_nopause "$@"

  demo_pause
}

demo_title() {
  local rule
  rule=$(printf '=%.0s' $(seq "$DEMO_RULE_WIDTH"))
  printf '\n%s%s\n=== %s ===\n%s%s\n' \
    "${_bold}" "$rule" "$*" "$rule" "${_reset}"
}

demo_note() {
  printf '\n%s===== %s =====%s\n' "${_bold}" "$*" "${_reset}"
}

demo_run_nopause() {
  local role=$1
  shift

  printf '%s%s%s%s\n' "${_cyan}" "$DEMO_PROMPT" "$*" "${_reset}"

  DEMO_QUIET=1 "$demo_lib_dir/run.sh" "$role" "$@" < /dev/null

  demo_done
}

demo_run() {
  demo_run_nopause "$@"

  demo_pause
}
