FROM python:3.12-slim-bookworm

ARG OPENCODE_VERSION=1.18.8

ENV PYTHONDONTWRITEBYTECODE=1     PYTHONUNBUFFERED=1     PIP_NO_CACHE_DIR=1     HOME=/var/lib/homelab-console-remediation-worker     XDG_CACHE_HOME=/var/lib/homelab-console-remediation-worker/cache     XDG_CONFIG_HOME=/var/lib/homelab-console-remediation-worker/config     XDG_DATA_HOME=/var/lib/homelab-console-remediation-worker/data     XDG_STATE_HOME=/var/lib/homelab-console-remediation-worker/state

RUN apt-get update     && apt-get install --yes --no-install-recommends ca-certificates nodejs npm tini     && npm install --global "opencode-ai@${OPENCODE_VERSION}"     && test "$(opencode --version)" = "${OPENCODE_VERSION}"     && rm -rf /var/lib/apt/lists/* /root/.npm

# Additional engines — opt-in via build args:
ARG INCLUDE_CODEX=false
ARG INCLUDE_CLAUDE=false
ARG INCLUDE_CLINE=false
RUN if [ "${INCLUDE_CODEX}" = "true" ]; then npm install --global "@openai/codex"; fi     && if [ "${INCLUDE_CLAUDE}" = "true" ]; then npm install --global "@anthropic-ai/claude-code"; fi     && if [ "${INCLUDE_CLINE}" = "true" ]; then npm install --global "cline"; fi

WORKDIR /opt/homelab-console-remediation-worker

COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install .

RUN useradd --uid 10001 --create-home --home-dir /var/lib/homelab-console-remediation-worker         --shell /usr/sbin/nologin worker     && install -d -o worker -g worker -m 0700         /run/homelab-console-remediation-worker         /var/lib/homelab-console-remediation-worker/cache         /var/lib/homelab-console-remediation-worker/config         /var/lib/homelab-console-remediation-worker/data/opencode         /var/lib/homelab-console-remediation-worker/state         /workspace     && install -d -o root -g root -m 0755 /etc/homelab-console-remediation-worker

COPY --chown=root:root profiles/ /etc/homelab-console-remediation-worker/profiles/
COPY --chown=root:root AGENTS.md /workspace/AGENTS.md
RUN chmod 0444 /etc/homelab-console-remediation-worker/profiles/*.json /workspace/AGENTS.md

USER 10001:10001

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3     CMD ["python", "-m", "remediation_worker", "health", "--config", "/etc/homelab-console-remediation-worker/config.toml"]

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "remediation_worker", "run", "--config", "/etc/homelab-console-remediation-worker/config.toml"]
