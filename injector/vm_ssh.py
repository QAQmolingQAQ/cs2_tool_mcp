#!/usr/bin/env python3
"""在 VM 上执行命令的 SSH 助手。

Windows 的 ssh 客户端不支持非交互传密码，这里用 paramiko，便于脚本化。

用法:
    python vm_ssh.py "whoami"
    python vm_ssh.py --ps "Get-Process cs2 | Select-Object Id,Path"
    python vm_ssh.py "dir C:\\" "ver"            # 多条顺序执行
    python vm_ssh.py --upload 本地文件 远程路径
    python vm_ssh.py --download 远程路径 本地文件

环境变量: VM_HOST / VM_USER / VM_PASS / VM_PORT
"""

from __future__ import annotations

import argparse
import os
import sys

import paramiko

# 连接信息一律走环境变量，仓库里不留内网地址与凭据
HOST = os.environ.get("VM_HOST", "")
USER = os.environ.get("VM_USER", "")
PASS = os.environ.get("VM_PASS", "")
PORT = int(os.environ.get("VM_PORT", "22"))


def connect(host: str = HOST, port: int = PORT,
            user: str = USER, password: str = PASS) -> paramiko.SSHClient:
    if not host or not user or not password:
        raise SystemExit("缺少连接信息，请设置环境变量 VM_HOST / VM_USER / VM_PASS（可选 VM_PORT）")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(host, port=port, username=user, password=password, timeout=20)
    return client


def run(client: paramiko.SSHClient, command: str, mode: str) -> int:
    if mode == "ps":
        full = f'powershell -NoProfile -Command "{command}"'
    elif mode == "ps64":
        # 用 -EncodedCommand 彻底避开多层引号转义问题
        import base64
        encoded = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        full = f"powershell -NoProfile -EncodedCommand {encoded}"
    else:
        full = command
    _stdin, stdout, stderr = client.exec_command(full)
    out = stdout.read().decode("utf-8", "replace").strip()
    err = stderr.read().decode("utf-8", "replace").strip()
    code = stdout.channel.recv_exit_status()
    if out:
        print(out)
    if err:
        print(f"[stderr] {err}", file=sys.stderr)
    return code


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("commands", nargs="*", help="要执行的命令")
    ap.add_argument("--ps", action="store_true", help="用 PowerShell 执行")
    ap.add_argument("--ps64", action="store_true",
                    help="用 PowerShell -EncodedCommand 执行（推荐，免引号转义）")
    ap.add_argument("--upload", nargs=2, metavar=("LOCAL", "REMOTE"))
    ap.add_argument("--download", nargs=2, metavar=("REMOTE", "LOCAL"))
    ap.add_argument("--host", default=HOST)
    args = ap.parse_args()

    client = connect(args.host)
    try:
        if args.upload:
            sftp = client.open_sftp()
            sftp.put(args.upload[0], args.upload[1])
            print(f"uploaded {args.upload[0]} -> {args.upload[1]}")
            sftp.close()
            return 0
        if args.download:
            sftp = client.open_sftp()
            sftp.get(args.download[0], args.download[1])
            print(f"downloaded {args.download[0]} -> {args.download[1]}")
            sftp.close()
            return 0
        if not args.commands:
            ap.error("需要提供命令，或使用 --upload/--download")
        code = 0
        mode = "ps64" if args.ps64 else ("ps" if args.ps else "cmd")
        for cmd in args.commands:
            print(f"> {cmd}")
            code = run(client, cmd, mode)
            print()
        return code
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
