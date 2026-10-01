@echo off
rem 试验：把 .vmap 路径作为命令行参数传给 cs2 -tools，看能否直接进 Hammer（绕过点图标）。
rem 用法（VM 内）:
rem   schtasks /create /tn HammerMap /tr "C:\cs2_tool_mcp\injector\launch_hammer_map.cmd" /sc once /st 23:59 /IT /F
rem   schtasks /run /tn HammerMap
cd /d "C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\game\bin\win64"
start "" cs2.exe -insecure -worldwide -condebug -high -tools -addon test "C:\Program Files (x86)\Steam\steamapps\common\Counter-Strike Global Offensive\content\csgo_addons\test\maps\untitled_2.vmap"
