@echo off
set PATH=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC\14.44.35207\bin\Hostx64\x64;C:\Program Files (x86)\Windows Kits\10\bin\10.0.26100.0\x64;%PATH%
set INCLUDE=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC\14.44.35207\include;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\um;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\shared;C:\Program Files (x86)\Windows Kits\10\Include\10.0.26100.0\ucrt
set LIB=C:\Program Files\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC\14.44.35207\lib\x64;C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\um\x64;C:\Program Files (x86)\Windows Kits\10\Lib\10.0.26100.0\ucrt\x64

cd /d d:\ai\agent\tool\mcp\cs2\cs2_tool_mcp\injector

echo === Compiling ===
cl /EHsc /std:c++20 /O2 test_pipe_client.cpp /Fe:test_pipe_client.exe /link kernel32.lib 2>&1

echo.
echo === Running ===
test_pipe_client.exe 2>&1

echo.
echo === Done ===
pause
