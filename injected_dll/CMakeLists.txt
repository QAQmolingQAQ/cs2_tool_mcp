cmake_minimum_required(VERSION 3.20)
project(cs2_tool_injector_dll LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# x64, MSVC CRT dynamic linking (matches hammer.dll)
set(CMAKE_WINDOWS_EXPORT_ALL_SYMBOLS ON)

add_library(cs2_tool_injector SHARED
    dllmain.cpp
    ipc_pipe.cpp
    hammer_bridge.cpp
    protocol.cpp
)

target_include_directories(cs2_tool_injector PRIVATE .)

# 源码是 UTF-8（含中文注释）；MSVC 默认按本地代码页(936)解码会导致语法错乱与 C4819
if(MSVC)
    target_compile_options(cs2_tool_injector PRIVATE /utf-8)
endif()

target_compile_definitions(cs2_tool_injector PRIVATE
    UNICODE
    _UNICODE
    WIN64
    _WIN64
    NOMINMAX
    WIN32_LEAN_AND_MEAN
)

target_link_libraries(cs2_tool_injector PRIVATE
    kernel32
    user32
    advapi32
)

# Ensure x64
if(NOT CMAKE_SIZEOF_VOID_P EQUAL 8)
    message(FATAL_ERROR "This project must be built for x64")
endif()

# Output DLL name
set_target_properties(cs2_tool_injector PROPERTIES
    OUTPUT_NAME "cs2_tool"
    PREFIX ""
)
