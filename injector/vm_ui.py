#!/usr/bin/env python3
"""VM 交互桌面（Session 1）的截图与输入控制。

背景：SSH 落在 Session 0（无桌面），既截不到交互桌面、也不能往里面发输入。
所以用**计划任务 `/IT`** 把 vm_screen.ps1 / vm_input.ps1 投递到交互会话执行。

首次使用先跑一次 setup（创建计划任务并上传脚本）:
    python vm_ui.py setup
    python vm_ui.py shot --out screen.png
    python vm_ui.py click 400 300
    python vm_ui.py dblclick 400 300
    python vm_ui.py drag 300 300 500 450
    python vm_ui.py move 400 300
    python vm_ui.py wheel 400 300 -120
    python vm_ui.py key ctrl+z
    python vm_ui.py type "hello"
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vm_ssh  # noqa: E402

REMOTE_DIR = r"C:\cs2_tool_mcp"
TASK_SHOT = "Cs2Shot"
TASK_INPUT = "Cs2Input"
LOCAL_DIR = Path(__file__).resolve().parent


def _ps(client, command: str) -> str:
    """用 -EncodedCommand 跑 PowerShell，避开多层引号转义。"""
    import base64
    enc = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
    _in, out, err = client.exec_command(f"powershell -NoProfile -EncodedCommand {enc}")
    o = out.read().decode("utf-8", "replace").strip()
    e = err.read().decode("utf-8", "replace").strip()
    return o or e


def _create_task(client, name: str, script: str) -> str:
    # -WindowStyle Hidden：否则计划任务的 powershell 控制台会盖在桌面上，截屏全是它
    cmd = (
        f'schtasks /create /tn {name} '
        f'/tr "powershell -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass '
        f'-File {REMOTE_DIR}\\{script}" '
        f'/sc once /st 23:59 /IT /F'
    )
    return _ps(client, cmd)


def _run_task(client, name: str) -> str:
    return _ps(client, f"schtasks /run /tn {name}")


def _read_remote(client, path: str, retries: int = 40) -> str | None:
    """轮询读取远端结果文件。

    retries 给到 40（约 20s）：ps1 里的 Add-Type 首次编译 C# 类可能要好几秒，
    窗口太短会误报 "input.out 未生成"。
    """
    sftp = client.open_sftp()
    try:
        for _ in range(retries):
            try:
                with sftp.open(path, "r") as f:
                    return f.read().decode("utf-8", "replace").strip()
            except OSError:
                time.sleep(0.5)
        return None
    finally:
        sftp.close()


def cmd_setup(client) -> int:
    sftp = client.open_sftp()
    try:
        _ps(client, f"New-Item -ItemType Directory -Force -Path {REMOTE_DIR} | Out-Null")
        for name in ("vm_screen.ps1", "vm_input.ps1"):
            sftp.put(str(LOCAL_DIR / name), f"{REMOTE_DIR}/{name}")
            print(f"uploaded {name}")
    finally:
        sftp.close()
    print(_create_task(client, TASK_SHOT, "vm_screen.ps1"))
    print(_create_task(client, TASK_INPUT, "vm_input.ps1"))
    return 0


def cmd_shot(client, out_path: str) -> int:
    _run_task(client, TASK_SHOT)
    sftp = client.open_sftp()
    try:
        for _ in range(16):
            time.sleep(0.5)
            try:
                sftp.stat(f"{REMOTE_DIR}/screen.png")
                break
            except OSError:
                continue
        else:
            print("ERROR: screen.png 未生成", file=sys.stderr)
            return 1
        sftp.get(f"{REMOTE_DIR}/screen.png", out_path)
    finally:
        sftp.close()
    size = Path(out_path).stat().st_size
    print(f"screenshot -> {out_path} ({size} bytes)")
    return 0


def cmd_input(client, line: str) -> int:
    sftp = client.open_sftp()
    try:
        with sftp.open(f"{REMOTE_DIR}/input.txt", "w") as f:
            f.write(line)
        try:
            sftp.remove(f"{REMOTE_DIR}/input.out")
        except OSError:
            pass
    finally:
        sftp.close()
    _run_task(client, TASK_INPUT)
    result = _read_remote(client, f"{REMOTE_DIR}/input.out")
    print(result if result is not None else "ERROR: input.out 未生成")
    return 0 if (result or "").startswith("OK") else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", help="setup/shot/move/click/dblclick/drag/wheel/key/type")
    ap.add_argument("args", nargs="*")
    ap.add_argument("--out", default="screen.png")
    args = ap.parse_args()

    client = vm_ssh.connect()
    try:
        a = args.action
        if a == "setup":
            return cmd_setup(client)
        if a == "shot":
            return cmd_shot(client, args.out)
        if a == "type":
            return cmd_input(client, "type " + " ".join(args.args))
        if a in ("move", "click", "dblclick", "drag", "wheel", "key", "windows", "keyto"):
            return cmd_input(client, a + " " + " ".join(args.args))
        if a == "activate":
            return cmd_input(client, "activate " + " ".join(args.args))
        ap.error(f"未知动作: {a}")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
