#include <windows.h>
#include <atomic>
static std::atomic<int> calls{0};
extern "C" __declspec(dllexport) void* CreateInterface(const char*,int* code) {
    ++calls;if(code)*code=1;return nullptr;
}
extern "C" __declspec(dllexport) int GetFactoryCallCount() {return calls;}
