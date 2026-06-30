import subprocess


def ssh_cmd(host: str, user: str, key_path: str, command: str, timeout: int = 10) -> str:
    cmd = [
        "ssh",
        "-o", "BatchMode=yes",
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=3",
        "-o", "LogLevel=ERROR",
    ]
    if key_path:
        cmd += ["-i", key_path]
    cmd += [f"{user}@{host}", command]
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.DEVNULL, timeout=timeout)
    except Exception:
        return ""
