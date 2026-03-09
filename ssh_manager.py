import paramiko
import time
import json
import os
import secrets
import base64

KEY_PATH = os.path.join(os.path.dirname(__file__), 'ssh_keys', 'id_ed25519')


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
                f"Step '{step_desc}' failed after {max_retries} attempts.\n"
                f"Output:\n{output[-600:]}"
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
            log.append(f"⚠️ LLM unavailable: {e}")
            time.sleep(3)

    raise RuntimeError(f"Step '{step_desc}' failed")


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
    log.append("📦 Creating container...")
    execute(ip, login, f"docker rm -f {name} 2>/dev/null")
    startup = f'bash -c "while [ ! -f /ready ]; do sleep 2; done; exec bash /entrypoint.sh"'
    _run_with_llm_fix(ip, login,
        f'docker run -d --name {name} --restart always -p {port}:3000 ubuntu:latest {startup}',
        "Create Docker container", log)

    # Step 2: Update packages
    log.append("📦 Updating packages...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'apt-get update -qq 2>&1'",
        "apt-get update", log)

    log.append("📦 Installing dependencies (curl, git, ffmpeg)...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'DEBIAN_FRONTEND=noninteractive apt-get install -y -qq curl git ffmpeg 2>&1'",
        "Install base packages", log)

    # Step 3: Install Node.js 22
    log.append("📦 Installing Node.js 22...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'curl -fsSL https://deb.nodesource.com/setup_22.x | bash - 2>&1'",
        "NodeSource setup", log)
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs 2>&1'",
        "Install Node.js", log)

    # Step 4: Install OpenClaw
    log.append("🦞 Installing OpenClaw...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'npm install -g openclaw@latest 2>&1'",
        "Install OpenClaw via npm", log)

    # Step 5: Ensure openclaw binary exists
    out, code = _execute_checked(ip, login, f"docker exec {name} bash -c 'which openclaw 2>/dev/null'")
    if code != 0 or not out.strip():
        log.append("🔧 Creating symlink for openclaw binary...")
        _execute_checked(ip, login,
            f"docker exec {name} bash -c '"
            f"find /usr/lib/node_modules /usr/local/lib/node_modules -name \"openclaw.mjs\" 2>/dev/null | head -1 | "
            f"xargs -I{{}} sh -c \"ln -sf {{}} /usr/local/bin/openclaw && chmod +x {{}}\"'"
        )

    # Step 6: Create config directories
    log.append("⚙️ Creating config structure...")
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

    log.append("⚙️ Writing openclaw.json...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'echo {config_b64} | base64 -d > /root/{profile_dir}/openclaw.json 2>&1'",
        "Write openclaw.json", log)

    log.append("⚙️ Writing auth-profiles.json...")
    _run_with_llm_fix(ip, login,
        f"docker exec {name} bash -c 'echo {auth_b64} | base64 -d > /root/{profile_dir}/agents/main/agent/auth-profiles.json 2>&1'",
        "Write auth-profiles.json", log)

    # Step 8: Write entrypoint.sh and signal /ready
    log.append("🚀 Starting OpenClaw...")
    entrypoint = f"#!/bin/bash\nexec openclaw {profile_flag} gateway run\n".strip()
    entry_b64 = base64.b64encode(entrypoint.encode()).decode()
    _execute_checked(ip, login,
        f"docker exec {name} bash -c 'echo {entry_b64} | base64 -d > /entrypoint.sh && chmod +x /entrypoint.sh && touch /ready'")

    log.append(f"✅ Done! Container {name} is running on port {port}")
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
        f"docker exec {container_name} "
        f"bash -c 'mkdir -p /root/.ssh && "
        f"echo \"{ssh_key}\" >> /root/.ssh/authorized_keys && "
        f"chmod 600 /root/.ssh/authorized_keys'"
    )
    execute(ip, login, cmd)
