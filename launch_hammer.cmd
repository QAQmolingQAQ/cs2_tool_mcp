@echo off
rem 在 **交互会话(Session 1)** 里启动 Hammer。
rem 直接经 SSH(会话 0) 启动会拿不到显卡 -> DX11 初始化失败 -> cs2 立刻退出。
rem 用法（在 VM 内）:
rem   schtasks /create /tn HammerLaunch /tr "C:\cs2_tool_mcp\launch_hammer.cmd" /sc once /st 23:59 /IT /F
rem   schtasks /run /tn HammerLaunch
cd /d "C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\bin\win64"
start "" cs2.exe -insecure -worldwide -condebug -high -tools -addon test
