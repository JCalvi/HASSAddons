import socket
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from .models import is_ipv4, add_source


def ping_ip(ip: str, timeout: int) -> bool:
    if not is_ipv4(ip):
        return False
    try:
        return subprocess.run(
            ["ping", "-c", "1", "-W", str(timeout), ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout + 1,
            check=False,
        ).returncode == 0
    except Exception:
        return False


def tcp_probe_ip(ip: str, ports: list[int], timeout: float = 0.5) -> str:
    if not is_ipv4(ip):
        return ""
    for port in ports:
        try:
            with socket.create_connection((ip, int(port)), timeout=timeout):
                return str(port)
        except Exception:
            pass
    return ""


def apply_active_probes(devices: dict, cfg: dict):
    ip_to_devices = {}
    for d in devices.values():
        ip = d.get("ip")
        if is_ipv4(ip):
            ip_to_devices.setdefault(ip, []).append(d)

    workers = int(cfg.get("ping_workers", 20))
    timeout = int(cfg.get("ping_timeout", 1))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_map = {pool.submit(ping_ip, ip, timeout): ip for ip in ip_to_devices}
        for future in as_completed(future_map):
            ip = future_map[future]
            ok = False
            try:
                ok = future.result()
            except Exception:
                ok = False
            if ok:
                for d in ip_to_devices[ip]:
                    d["status"] = "online"
                    d["ping"] = "OK"
                    add_source(d, "Ping")

    if cfg.get("tcp_probe"):
        ports = cfg.get("tcp_ports", [22, 53, 80, 443])
        targets = [ip for ip, ds in ip_to_devices.items() if all(d.get("status") != "online" for d in ds)]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {pool.submit(tcp_probe_ip, ip, ports): ip for ip in targets}
            for future in as_completed(future_map):
                ip = future_map[future]
                port = ""
                try:
                    port = future.result()
                except Exception:
                    port = ""
                if port:
                    for d in ip_to_devices[ip]:
                        d["status"] = "online"
                        d["tcp"] = port
                        add_source(d, f"TCP:{port}")
