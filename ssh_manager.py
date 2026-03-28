import paramiko
import time
import json
import os
import secrets
import base64

KEY_PATH = '/root/tgbot/ssh_keys/id_ed25519'


def _client(ip: str, login: str) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(ip, username=login, key_filename=KEY_PATH, timeout=15)
    client.get_transport().set_keepalive(30)
    return client


def connect(ip: str, login: str) -> bool:
    try:
        c = _client(ip, login)
        c.close()
        return True
    except Exception:
        return False


def copy_bot_key(ip: str, login: str, password: str) -> bool:
    try:
        with open(KEY_PATH + '.pub') as f:
            pub_key = f.read().strip()
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(ip, username=login, password=password, timeout=15)
        cmd = (
            f'mkdir -p ~/.ssh && chmod 700 ~/.ssh && '
            f'echo "{pub_key}" >> ~/.ssh/authorized_keys && '
            f'chmod 600 ~/.ssh/authorized_keys'
        )
        stdin, stdout, stderr = client.exec_command(cmd)
        stdout.channel.recv_exit_status()
        client.close()
        return True
    except Exception as e:
        raise RuntimeError(f"copy_bot_key failed: {e}")


def execute(ip: str, login: str, command: str, timeout: int = 120) -> str:
    client = _client(ip, login)
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    client.close()
    return out + err


def _execute_checked(ip: str, login: str, command: str, timeout: int = 180):
    """Execute command and return (combined_output, exit_code)."""
    client = _client(ip, login)
    stdin, stdout, stderr = client.exec_command(command, timeout=timeout)
    out = stdout.read().decode()
    err = stderr.read().decode()
    exit_code = stdout.channel.recv_exit_status()
    client.close()
    return (out + err).strip(), exit_code


def _run_with_llm_fix(ip: str, login: str, command: str, step_desc: str, log: list, max_retries: int = 3) -> str:
    """Run command; on failure ask Claude for a fix command and retry."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')

    for attempt in range(max_retries):
        output, exit_code = _execute_checked(ip, login, command)

        if exit_code == 0:
            return output

        if attempt == max_retries - 1:
            raise RuntimeError(
                f"Шаг '{step_desc}' провалился после {max_retries} попыток.\n"
                f"Вывод:\n{output[-600:]}"
            )

        if not api_key:
            time.sleep(3)
            continue

        try:
            import anthropic
            ai = anthropic.Anthropic(api_key=api_key)
            response = ai.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=300,
                system=(
                    "You are a Linux/Docker DevOps expert. A command failed during OpenClaw AI agent "
                    "installation inside an Ubuntu Docker container. "
                    "Return ONLY one shell command to fix the issue. No explanation, no markdown, just the raw command."
                ),
                messages=[{
                    "role": "user",
                    "content": (
                        f"Step: {step_desc}\n"
                        f"Failed command: {command}\n"
                        f"Output:\n{output[-800:]}\n\n"
                        "Single fix command:"
                    )
                }]
            )
            fix_cmd = response.content[0].text.strip().strip('`').strip()
            if fix_cmd:
                log.append(f"🔧 LLM fix ({step_desc}): `{fix_cmd[:100]}`")
                _execute_checked(ip, login, fix_cmd, timeout=120)
        except Exception as e:
            log.append(f"⚠️ LLM недоступен: {e}")
            time.sleep(3)

    raise RuntimeError(f"Шаг '{step_desc}' не удалось выполнить")


def get_next_port(ip: str, login: str) -> int:
    out = execute(ip, login, "docker ps --format '{{.Ports}}' | grep -oP '0\\.0\\.0\\.0:\\K[0-9]+' | sort -n | tail -1")
    try:
        last = int(out.strip())
        return last + 1
    except Exception:
        return 3010


def create_empty_container(ip: str, login: str, name: str) -> int:
    port = get_next_port(ip, login)
    cmds = [
        f"docker run -d --name {name} --restart always -p {port}:22 ubuntu:latest sleep infinity",
        f"docker exec {name} bash -c 'apt-get update -qq && apt-get install -y -qq openssh-server sudo && mkdir -p /run/sshd'",
        f"docker exec {name} bash -c 'useradd -m -s /bin/bash {name} && echo \"{name} ALL=(ALL) NOPASSWD:ALL\" >> /etc/sudoers'",
        f"docker exec {name} bash -c 'mkdir -p /home/{name}/.ssh && chmod 700 /home/{name}/.ssh && chown {name}:{name} /home/{name}/.ssh'",
        f"docker exec {name} bash -c '/usr/sbin/sshd -D &'",
    ]
    for cmd in cmds:
        execute(ip, login, cmd)
    return port


def create_openclaw_container(ip: str, login: str, name: str,
                               anthropic_key: str, openai_key: str,
                               telegram_token: str, openclaw_profile: str = '',
                               log: list = None) -> int:
    if log is None:
        log = []

    port = get_next_port(ip, login)
    profile_flag = f"--profile {openclaw_profile}" if openclaw_profile else ""
    profile_dir = f".openclaw-{openclaw_profile}" if openclaw_profile else ".openclaw"
    gateway_token = secrets.token_hex(24)

    # Step 1: Remove leftover container with same name (if any) and create new one
    log.append("📦 Создаю контейнер...")
    execute(ip, login, f"docker rm -f {name} 2>/dev/null")
    startup = f'bash -c "while [ ! -f /ready ]; do sleep 2; done; exec bash /entrypoint.sh"'
    _run_with_llm_fix(ip, login,
        f'docker run -d --name {name} --restart always -p {port}:3000 ubuntu:latest {startup}',
        "Create Docker container", log)

    # Step 2: Update packages
    log.append("📦 Обновляю пакеты...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'apt-get update -qq 2>&1'",
        "apt-get update", log)

    log.append("📦 Устанавливаю зависимости (curl, git, ffmpeg)...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl git ffmpeg 2>&1'",
        "Install base packages", log)

    # Step 3: Install Node.js 22
    log.append("📦 Устанавливаю Node.js 22...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'curl -fsSL https://deb.nodesource.com/setup_22.x | bash - 2>&1'",
        "NodeSource setup", log)
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs 2>&1'",
        "Install Node.js", log)

    # Step 4: Install OpenClaw
    log.append("🦞 Устанавливаю OpenClaw...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'npm install -g openclaw@latest 2>&1'",
        "Install OpenClaw via npm", log)

    # Step 5: Ensure openclaw binary exists
    out, code = _execute_checked(ip, login, f"docker exec {name} bash -c 'which openclaw 2>/dev/null'")
    if code != 0 or not out.strip():
        log.append("🔧 Создаю symlink для openclaw binary...")
        _execute_checked(ip, login,
            f"docker exec {name} bash -c '"
            f"find /usr/lib/node_modules /usr/local/lib/node_modules -name \"openclaw.mjs\" 2>/dev/null | head -1 | "
            f"xargs -I{{}} sh -c \"ln -sf {{}} /usr/local/bin/openclaw && chmod +x {{}}\"'"
        )

    # Step 6: Create config directories
    log.append("⚙️ Создаю структуру конфигурации...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'mkdir -p /root/{profile_dir}/agents/main/agent /root/{profile_dir}/workspace 2>&1'",
        "Create config directories", log)

    # Step 7: Write openclaw.json
    openclaw_json = json.dumps({
        "meta": {"lastTouchedVersion": "2026.3.2"},
        "agents": {
            "defaults": {
                "model": {"primary": "anthropic/claude-sonnet-4-6"},
                "models": {
                    "anthropic/claude-sonnet-4-6": {},
                    "openai/gpt-4o-mini": {},
                    "openai/gpt-4o": {"alias": "gpt"}
                },
                "workspace": f"/root/{profile_dir}/workspace",
                "compaction": {"mode": "safeguard"}
            }
        },
        "commands": {"native": "auto", "nativeSkills": "auto", "restart": True, "ownerDisplay": "raw"},
        "channels": {
            "telegram": {
                "enabled": True,
                "dmPolicy": "pairing",
                "groupPolicy": "open",
                "botToken": telegram_token,
                "streaming": True
            }
        },
        "gateway": {
            "port": 3000,
            "mode": "local",
            "bind": "loopback",
            "auth": {"mode": "token", "token": gateway_token}
        },
        "plugins": {"entries": {"telegram": {"enabled": True}}},
        "env": {"OPENAI_API_KEY": openai_key},
        "skills": {"entries": {"openai-whisper-api": {"apiKey": openai_key}}}
    })

    auth_json = json.dumps({
        "version": 1,
        "profiles": {
            "anthropic:default": {"type": "api_key", "provider": "anthropic", "key": anthropic_key},
            "openai:default": {"type": "api_key", "provider": "openai", "key": openai_key}
        }
    })

    config_b64 = base64.b64encode(openclaw_json.encode()).decode()
    auth_b64 = base64.b64encode(auth_json.encode()).decode()

    log.append("⚙️ Записываю openclaw.json...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'echo {config_b64} | base64 -d > /root/{profile_dir}/openclaw.json 2>&1'",
        "Write openclaw.json", log)

    log.append("⚙️ Записываю auth-profiles.json...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'echo {auth_b64} | base64 -d > /root/{profile_dir}/agents/main/agent/auth-profiles.json 2>&1'",
        "Write auth-profiles.json", log)

    # Step 8: Write entrypoint.sh and signal /ready — openclaw starts immediately
    log.append("🚀 Запускаю OpenClaw...")
    entrypoint = f"#!/bin/bash\nexec openclaw {profile_flag} gateway run\n".strip()
    entry_b64 = base64.b64encode(entrypoint.encode()).decode()
    _execute_checked(ip, login,
        f"docker exec {name} bash -c 'echo {entry_b64} | base64 -d > /entrypoint.sh && chmod +x /entrypoint.sh && touch /ready'")

    log.append(f"✅ Готово! Контейнер {name} запущен на порту {port}")
    return port


def get_paired_users(ip: str, login: str, container_name: str, openclaw_profile: str = '') -> list:
    """Get list of paired Telegram user IDs from a container."""
    profile_dir = f".openclaw-{openclaw_profile}" if openclaw_profile else ".openclaw"
    cmd = f"docker exec {container_name} bash -c 'cat /root/{profile_dir}/credentials/telegram-default-allowFrom.json 2>/dev/null'"
    try:
        out = execute(ip, login, cmd, timeout=10)
        if out.strip():
            import json
            data = json.loads(out.strip())
            return data.get("allowFrom", [])
    except Exception:
        pass
    return []


def approve_pairing(ip: str, login: str, container_name: str, openclaw_profile: str, code: str) -> str:
    """Approve OpenClaw Telegram pairing for a container."""
    profile_flag = f"--profile {openclaw_profile}" if openclaw_profile else ""
    cmd = f"docker exec {container_name} bash -c 'openclaw {profile_flag} pairing approve telegram {code} 2>&1'"
    out, exit_code = _execute_checked(ip, login, cmd, timeout=30)
    if exit_code != 0 and out:
        raise RuntimeError(out.strip())
    return out.strip()


def add_employee_key(ip: str, login: str, container_name: str, ssh_key: str):
    cmd = (
        f"useradd -m -s /bin/bash {container_name} 2>/dev/null || true && "
        f"usermod -aG docker {container_name} && "
        f"mkdir -p /home/{container_name}/.ssh && "
        f"echo \"{ssh_key}\" >> /home/{container_name}/.ssh/authorized_keys && "
        f"chmod 700 /home/{container_name}/.ssh && "
        f"chmod 600 /home/{container_name}/.ssh/authorized_keys && "
        f"chown -R {container_name}:{container_name} /home/{container_name}/.ssh && "
        f"if ! grep -q 'docker exec -it {container_name} bash' /home/{container_name}/.bashrc 2>/dev/null; then "
        f"echo 'docker exec -it {container_name} bash' >> /home/{container_name}/.bashrc && "
        f"echo 'exit' >> /home/{container_name}/.bashrc; fi"
    )
    execute(ip, login, cmd)

# ── API KEY MANAGEMENT ──────────────────────────────────────────────────────

def _check_container_running(ip: str, login: str, container_name: str):
    """Raise error if container is not running."""
    out, code = _execute_checked(ip, login,
        f"docker inspect -f '{{{{.State.Running}}}}' {container_name} 2>&1", timeout=10)
    if 'true' not in out.lower():
        raise RuntimeError(f"Container {container_name} is not running")

def _read_json_from_container(ip: str, login: str, container_name: str, path: str) -> dict:
    """Read and parse JSON file from inside container."""
    out = execute(ip, login, f"docker exec {container_name} cat {path} 2>/dev/null", timeout=10)
    if not out.strip():
        return {}
    return json.loads(out.strip())

def _write_json_to_container(ip: str, login: str, container_name: str, path: str, data: dict):
    """Write JSON data to file inside container via base64."""
    b64 = base64.b64encode(json.dumps(data, ensure_ascii=False).encode()).decode()
    execute(ip, login,
        f"docker exec {container_name} bash -c 'echo {b64} | base64 -d > {path}'", timeout=10)

def update_anthropic_key(ip, login, container_name, openclaw_profile, new_key):
    """Update Anthropic API key in container's auth-profiles.json."""
    _check_container_running(ip, login, container_name)
    profile_dir = f".openclaw-{openclaw_profile}" if openclaw_profile else ".openclaw"
    auth_path = f"/root/{profile_dir}/agents/main/agent/auth-profiles.json"
    try:
        auth_data = _read_json_from_container(ip, login, container_name, auth_path)
    except Exception:
        auth_data = {}
    if not auth_data:
        auth_data = {"version": 1, "profiles": {}}
    auth_data.setdefault("profiles", {})
    auth_data["profiles"]["anthropic:default"] = {
        "type": "api_key", "provider": "anthropic", "key": new_key
    }
    _write_json_to_container(ip, login, container_name, auth_path, auth_data)

def update_openai_key(ip, login, container_name, openclaw_profile, new_key):
    """Update OpenAI API key in auth-profiles.json and openclaw.json."""
    _check_container_running(ip, login, container_name)
    profile_dir = f".openclaw-{openclaw_profile}" if openclaw_profile else ".openclaw"
    auth_path = f"/root/{profile_dir}/agents/main/agent/auth-profiles.json"
    config_path = f"/root/{profile_dir}/openclaw.json"
    # 1. auth-profiles.json
    try:
        auth_data = _read_json_from_container(ip, login, container_name, auth_path)
    except Exception:
        auth_data = {}
    if not auth_data:
        auth_data = {"version": 1, "profiles": {}}
    auth_data.setdefault("profiles", {})
    auth_data["profiles"]["openai:default"] = {
        "type": "api_key", "provider": "openai", "key": new_key
    }
    _write_json_to_container(ip, login, container_name, auth_path, auth_data)
    # 2. openclaw.json (env.OPENAI_API_KEY + skills whisper)
    try:
        config = _read_json_from_container(ip, login, container_name, config_path)
        if config:
            config.setdefault("env", {})["OPENAI_API_KEY"] = new_key
            config.setdefault("skills", {}).setdefault("entries", {}).setdefault(
                "openai-whisper-api", {})["apiKey"] = new_key
            _write_json_to_container(ip, login, container_name, config_path, config)
    except Exception:
        pass

def update_telegram_token(ip, login, container_name, openclaw_profile, new_token):
    """Update Telegram bot token in openclaw.json."""
    _check_container_running(ip, login, container_name)
    profile_dir = f".openclaw-{openclaw_profile}" if openclaw_profile else ".openclaw"
    config_path = f"/root/{profile_dir}/openclaw.json"
    config = _read_json_from_container(ip, login, container_name, config_path)
    if not config:
        raise RuntimeError(f"Cannot read openclaw.json from {container_name}")
    config.setdefault("channels", {}).setdefault("telegram", {})["botToken"] = new_token
    _write_json_to_container(ip, login, container_name, config_path, config)

def _container_cmd(ip: str, login: str, container_name: str):
    out, code = _execute_checked(
        ip, login,
        f"docker inspect {container_name} --format '{{{{json .Config.Cmd}}}}'",
        timeout=15,
    )
    if code != 0 or not out.strip():
        return []
    try:
        return json.loads(out.strip())
    except Exception:
        return []

def _wait_for_gateway(ip: str, login: str, container_name: str, timeout: int = 25) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        out, code = _execute_checked(
            ip, login,
            f"docker exec {container_name} pgrep -af openclaw-gateway 2>/dev/null",
            timeout=10,
        )
        if code == 0 and out.strip():
            return True
        time.sleep(1)
    return False

def restart_gateway(ip, login, container_name, openclaw_profile='', force_restart=False):
    """Restart only the OpenClaw gateway, without restarting the whole container."""
    _check_container_running(ip, login, container_name)
    profile_flag = f"--profile {openclaw_profile}" if openclaw_profile else ""
    legacy_cmd = _container_cmd(ip, login, container_name) == ["sleep", "infinity"]

    if legacy_cmd:
        # Older Server 2 containers keep PID 1 as `sleep infinity`, so a docker restart
        # leaves the container up but drops the gateway. Restart the gateway in-place.
        _execute_checked(
            ip, login,
            f"docker exec {container_name} bash -lc 'openclaw {profile_flag} gateway stop >/dev/null 2>&1 || true'",
            timeout=15,
        )
        _execute_checked(
            ip, login,
            f"docker exec {container_name} bash -lc 'pkill -f openclaw-gateway >/dev/null 2>&1 || true'",
            timeout=15,
        )
        _execute_checked(
            ip, login,
            f"docker exec -d {container_name} bash -lc 'cd /root && nohup openclaw {profile_flag} gateway > /tmp/openclaw-gateway.log 2>&1 &'",
            timeout=15,
        )
    elif force_restart:
        # API key changes require full restart so OpenClaw re-reads auth-profiles
        # from disk (SIGUSR1 reload keeps old key in memory and overwrites file).
        execute(ip, login, f"docker restart {container_name}", timeout=30)
    else:
        # Newer containers have OpenClaw as PID 1, so ask it to reload itself.
        out, code = _execute_checked(ip, login, f"docker kill --signal=USR1 {container_name}", timeout=15)
        if code != 0:
            raise RuntimeError(out or f"Failed to signal gateway in {container_name}")

    if _wait_for_gateway(ip, login, container_name):
        return

    # Fallback: if the graceful path didn't leave a running gateway, start one explicitly.
    _execute_checked(
        ip, login,
        f"docker exec -d {container_name} bash -lc 'cd /root && nohup openclaw {profile_flag} gateway > /tmp/openclaw-gateway.log 2>&1 &'",
        timeout=15,
    )
    if not _wait_for_gateway(ip, login, container_name):
        raise RuntimeError(f"Gateway did not start in {container_name}")



# ---------------------------------------------------------------------------
# Deep health checks & auto-healing (added 2026-03-12)
# ---------------------------------------------------------------------------

import logging as _logging
_heal_logger = _logging.getLogger('auto_heal')


def deep_health_check(ip: str, login: str, container_name: str,
                      openclaw_profile: str = '') -> list:
    """Run deep checks inside a running OpenClaw container.

    Returns a list of issue dicts:
        {"type": str, "details": str, "context": str}
    Empty list = healthy.
    """
    profile_dir = f".openclaw-{openclaw_profile}" if openclaw_profile else ".openclaw"
    profile_flag = f"--profile {openclaw_profile}" if openclaw_profile else ""
    issues = []

    def _exec(cmd, timeout=10):
        return _execute_checked(ip, login,
            f"docker exec {container_name} bash -c '{cmd}'", timeout=timeout)

    # 0. Gateway configured? Only monitor if botToken is set in openclaw.json
    cfg_out, cfg_code = _exec(f"cat /root/{profile_dir}/openclaw.json 2>/dev/null")
    if cfg_code != 0 or not cfg_out.strip():
        return []  # no config file — not configured
    try:
        import json as _json
        cfg = _json.loads(cfg_out.strip())
        bot_token = (cfg.get("channels", {}).get("telegram", {}).get("botToken") or "").strip()
        if not bot_token:
            return []  # no Telegram bot token — gateway not set up yet
    except Exception:
        return []  # can't parse config — skip

    # 1. Gateway process running?
    out, code = _exec("pgrep -f openclaw-gateway || echo __NONE__")
    if "__NONE__" in out or code != 0:
        # Collect context: what IS running?
        ps_out, _ = _exec("ps aux --no-headers 2>/dev/null | head -10")
        issues.append({
            "type": "gateway_down",
            "details": "openclaw-gateway process not found",
            "context": ps_out.strip()[:500],
            "profile_flag": profile_flag,
        })
        # If gateway is down, skip telegram check (it will obviously fail)
        return issues

    # 2. Config validity
    out, code = _exec(
        f'python3 -c "import json; json.load(open(\\"/root/{profile_dir}/openclaw.json\\"))" 2>&1'
    )
    if code != 0:
        cfg_out, _ = _exec(f"cat /root/{profile_dir}/openclaw.json 2>&1")
        issues.append({
            "type": "config_invalid",
            "details": out.strip()[:300],
            "context": cfg_out.strip()[:1500],
            "profile_dir": profile_dir,
        })

    # 3. Auth profiles exist?
    _, code = _exec(f"test -f /root/{profile_dir}/agents/main/agent/auth-profiles.json")
    if code != 0:
        issues.append({
            "type": "auth_missing",
            "details": f"No auth-profiles.json in /root/{profile_dir}/agents/main/agent/",
            "context": "",
            "profile_dir": profile_dir,
        })

    # 4. Entrypoint exists?
    _, code = _exec("test -f /entrypoint.sh")
    if code != 0:
        issues.append({
            "type": "entrypoint_missing",
            "details": "No /entrypoint.sh",
            "context": "",
            "profile_flag": profile_flag,
        })

    # 5. Telegram connected? (only if gateway is up for > 2 min)
    uptime_out, _ = _exec(
        "ps -p $(pgrep -f openclaw-gateway -o) -o etimes= 2>/dev/null || echo 0"
    )
    try:
        uptime_sec = int(uptime_out.strip().split()[-1])
    except (ValueError, IndexError):
        uptime_sec = 0

    if uptime_sec > 120:
        tg_out, _ = _exec(
            "docker logs " + container_name + " --tail 100 2>&1 | grep -c '\\[telegram\\]' || echo 0",
        )
        # This runs on the host, not inside the container
        tg_out2, _ = _execute_checked(ip, login,
            f"docker logs {container_name} --tail 100 2>&1 | grep -c '\\[telegram\\]' || echo 0",
            timeout=10)
        try:
            tg_count = int(tg_out2.strip().split('\n')[-1])
        except (ValueError, IndexError):
            tg_count = 0
        if tg_count == 0:
            log_tail, _ = _execute_checked(ip, login,
                f"docker logs {container_name} --tail 30 2>&1", timeout=10)
            issues.append({
                "type": "telegram_disconnected",
                "details": "No [telegram] activity in last 100 log lines (gateway up > 2 min)",
                "context": log_tail.strip()[:1000],
            })

    return issues


def auto_fix_issue(ip: str, login: str, container_name: str,
                   openclaw_profile: str, issue: dict) -> tuple:
    """Attempt to auto-fix a detected issue.

    Returns (success: bool, description: str).
    """
    itype = issue["type"]
    profile_dir = f".openclaw-{openclaw_profile}" if openclaw_profile else ".openclaw"
    profile_flag = issue.get("profile_flag", "")
    if not profile_flag and openclaw_profile:
        profile_flag = f"--profile {openclaw_profile}"

    try:
        # --- Deterministic fixes ---

        if itype == "gateway_down":
            _heal_logger.info(f"[{container_name}] Starting gateway...")
            # Use execute() not _execute_checked() — gateway is long-running,
            # docker exec -d returns immediately
            execute(ip, login,
                f"docker exec -d {container_name} bash -c "
                f"'openclaw {profile_flag} gateway run >> /root/.openclaw/gateway.log 2>&1'",
                timeout=15)
            # Verify after short wait
            time.sleep(5)
            out, code = _execute_checked(ip, login,
                f"docker exec {container_name} bash -c 'pgrep -f openclaw-gateway || echo __NONE__'",
                timeout=10)
            if "__NONE__" not in out and code == 0:
                return True, "gateway was down → restarted"
            return False, "gateway restart failed"

        if itype == "entrypoint_missing":
            _heal_logger.info(f"[{container_name}] Creating entrypoint...")
            entry = f"#!/bin/bash\\nexec openclaw {profile_flag} gateway run".strip()
            _execute_checked(ip, login,
                f"docker exec {container_name} bash -c "
                f"\"echo -e '{entry}' > /entrypoint.sh && chmod +x /entrypoint.sh\"",
                timeout=10)
            _, code = _execute_checked(ip, login,
                f"docker exec {container_name} bash -c 'test -f /entrypoint.sh'", timeout=5)
            if code == 0:
                return True, "missing /entrypoint.sh → created"
            return False, "failed to create /entrypoint.sh"

        if itype == "auth_missing":
            _heal_logger.info(f"[{container_name}] Looking for auth-profiles.json donor...")
            # Find another container on this server that has auth-profiles.json
            ps_out = execute(ip, login,
                "docker ps --format '{{.Names}}' 2>/dev/null", timeout=10)
            donor = None
            for other in ps_out.strip().split('\n'):
                other = other.strip()
                if not other or other == container_name:
                    continue
                # Check if this container has auth-profiles
                _, c = _execute_checked(ip, login,
                    f"docker exec {other} bash -c "
                    f"'test -f /root/.openclaw/agents/main/agent/auth-profiles.json'",
                    timeout=5)
                if c == 0:
                    donor = other
                    break
                # Also check with profile dirs
                _, c = _execute_checked(ip, login,
                    f"docker exec {other} bash -c "
                    f"'ls /root/.openclaw-*/agents/main/agent/auth-profiles.json 2>/dev/null | head -1'",
                    timeout=5)
                if c == 0:
                    donor = other
                    break

            if not donor:
                return False, "no donor container with auth-profiles.json found"

            # Read from donor, write to target
            auth_data, code = _execute_checked(ip, login,
                f"docker exec {donor} bash -c "
                f"'cat /root/.openclaw*/agents/main/agent/auth-profiles.json 2>/dev/null | head -1'",
                timeout=10)
            if code != 0 or not auth_data.strip():
                return False, f"failed to read auth from {donor}"

            auth_b64 = base64.b64encode(auth_data.strip().encode()).decode()
            _execute_checked(ip, login,
                f"docker exec {container_name} bash -c "
                f"'mkdir -p /root/{profile_dir}/agents/main/agent && "
                f"echo {auth_b64} | base64 -d > /root/{profile_dir}/agents/main/agent/auth-profiles.json'",
                timeout=10)
            _, c2 = _execute_checked(ip, login,
                f"docker exec {container_name} bash -c "
                f"'test -f /root/{profile_dir}/agents/main/agent/auth-profiles.json'",
                timeout=5)
            if c2 == 0:
                return True, f"missing auth-profiles.json → copied from {donor}"
            return False, "auth-profiles.json copy failed"

        # --- LLM-assisted fixes ---

        if itype == "config_invalid":
            return _llm_fix_config(ip, login, container_name, profile_dir, issue)

        if itype == "telegram_disconnected":
            return _llm_fix_generic(ip, login, container_name, openclaw_profile, issue)

    except Exception as e:
        _heal_logger.error(f"[{container_name}] auto_fix {itype} failed: {e}")
        return False, f"exception: {e}"

    return False, f"unknown issue type: {itype}"


def _llm_fix_config(ip, login, container_name, profile_dir, issue):
    """Use Claude to fix an invalid openclaw.json."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return False, "LLM unavailable (no ANTHROPIC_API_KEY)"

    try:
        import anthropic
        ai = anthropic.Anthropic(api_key=api_key)
        response = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2000,
            system=(
                "You are a JSON repair expert. You will receive an invalid JSON config file "
                "and the error message. Return ONLY the corrected JSON — no explanation, "
                "no markdown fences, just the raw valid JSON."
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Error: {issue['details']}\n\n"
                    f"Invalid JSON content:\n{issue['context']}\n\n"
                    "Return the corrected JSON:"
                )
            }]
        )
        fixed_json = response.content[0].text.strip()
        # Validate it's actually valid JSON
        json.loads(fixed_json)

        fixed_b64 = base64.b64encode(fixed_json.encode()).decode()
        # Backup old config
        _execute_checked(ip, login,
            f"docker exec {container_name} bash -c "
            f"'cp /root/{profile_dir}/openclaw.json /root/{profile_dir}/openclaw.json.bak'",
            timeout=5)
        # Write fixed config
        _execute_checked(ip, login,
            f"docker exec {container_name} bash -c "
            f"'echo {fixed_b64} | base64 -d > /root/{profile_dir}/openclaw.json'",
            timeout=10)
        return True, "invalid openclaw.json → repaired by LLM (backup saved as .bak)"

    except json.JSONDecodeError:
        return False, "LLM returned invalid JSON"
    except Exception as e:
        return False, f"LLM config fix failed: {e}"


def _llm_fix_generic(ip, login, container_name, openclaw_profile, issue):
    """Use Claude to diagnose and fix a generic issue."""
    api_key = os.environ.get('ANTHROPIC_API_KEY', '')
    if not api_key:
        return False, "LLM unavailable (no ANTHROPIC_API_KEY)"

    profile_flag = f"--profile {openclaw_profile}" if openclaw_profile else ""

    try:
        import anthropic
        ai = anthropic.Anthropic(api_key=api_key)
        response = ai.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=300,
            system=(
                "You are a Linux/Docker DevOps expert. An OpenClaw AI agent container "
                "has a runtime issue. Analyze the logs and return ONLY one shell command "
                "to fix it. The command will be run INSIDE the container via "
                "'docker exec CONTAINER bash -c \"COMMAND\"'. "
                "No explanation, no markdown, just the raw command. "
                "If the best fix is to restart the gateway, return: "
                f"pkill -f openclaw-gateway; sleep 2; nohup openclaw {profile_flag} gateway run > /root/openclaw.log 2>&1 &"
            ),
            messages=[{
                "role": "user",
                "content": (
                    f"Issue: {issue['type']} — {issue['details']}\n\n"
                    f"Recent logs:\n{issue['context']}\n\n"
                    "Single fix command:"
                )
            }]
        )
        fix_cmd = response.content[0].text.strip().strip('`').strip()
        if not fix_cmd:
            return False, "LLM returned empty fix"

        _heal_logger.info(f"[{container_name}] LLM fix: {fix_cmd[:100]}")
        _execute_checked(ip, login,
            f"docker exec {container_name} bash -c '{fix_cmd}'",
            timeout=60)
        return True, f"{issue['type']} → LLM fix applied: `{fix_cmd[:80]}`"

    except Exception as e:
        return False, f"LLM fix failed: {e}"
