#!/bin/bash
# Entrypoint of the agent container (plan 7.3, 7.4, 7.7). Runs as container root
# (--user 0): firewall, harness-home clean-up, preflight, then drops to `agent` with every
# capability removed and execs the harness argv with a clean environment.
# Exit codes: 210 preflight security failure, 211 model API unreachable, 212 firewall load
# failure (high values, so a harness's own exit code cannot pass for them); anything else
# is the harness's own exit code.
set -u

if [ "$(id -u)" != 0 ]; then
    echo "sn-entrypoint: must start as container root (--user 0)" >&2
    exit 212
fi
if [ "${SN_NO_NETWORK:-0}" != 1 ]; then
    /usr/local/sbin/sn-init-firewall || exit $?
fi
/usr/local/sbin/sn-clean-home || exit 210
/usr/local/sbin/sn-preflight || exit $?

keep=(PATH="/opt/visuals/.venv/bin:/usr/local/bin:/usr/bin:/bin" HOME=/home/agent
      TERM="${TERM:-dumb}" SN_RUN_ID="${SN_RUN_ID:-}")
for key in CLAUDE_CODE_VERSION DISABLE_AUTOUPDATER DISABLE_TELEMETRY DISABLE_ERROR_REPORTING \
           CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC UV_OFFLINE UV_NO_SYNC UV_FROZEN \
           UV_PROJECT_ENVIRONMENT UV_PYTHON_DOWNLOADS; do
    keep+=("$key=${!key:-}")
done

cd /work 2>/dev/null || cd /home/agent
exec setpriv --reuid="$SN_AGENT_UID" --regid="$SN_AGENT_GID" --clear-groups \
    --inh-caps=-all --bounding-set=-all -- env -i "${keep[@]}" "$@"
