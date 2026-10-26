// Exercise real pipe startup with a loaded editor factory that must not be called.
#include "../ipc_pipe.h"
#include "../hammer_bridge.h"
#include <iostream>

bool Transfer(HANDLE pipe,void* data,DWORD size,bool write) {
    DWORD total=0;
    while(total<size) {
        DWORD got=0;
        BOOL ok=write?WriteFile(pipe,static_cast<char*>(data)+total,size-total,&got,nullptr):
            ReadFile(pipe,static_cast<char*>(data)+total,size-total,&got,nullptr);
        if(!ok || !got)return false;total+=got;
    }
    return true;
}
std::string Call(HANDLE pipe,const std::string& method) {
    std::string request="{\"id\":1,\"method\":\""+method+"\",\"params\":{}}";
    cs2tool::MsgHeader header{cs2tool::kMsgMagic,cs2tool::kMsgVersion,static_cast<uint32_t>(request.size()),0};
    if(!Transfer(pipe,&header,sizeof(header),true) || !Transfer(pipe,request.data(),header.length,true))return "";
    if(!Transfer(pipe,&header,sizeof(header),false) || header.magic!=cs2tool::kMsgMagic || header.length>cs2tool::kMaxMsgSize)return "";
    std::string response(header.length,'\0');
    if(!Transfer(pipe,response.data(),header.length,false))return "";
    return response;
}
int main(int argc,char** argv) {
    if(argc!=2)return 10;
    auto fake=LoadLibraryA(argv[1]);if(!fake)return 11;
    auto count=reinterpret_cast<int(*)()>(GetProcAddress(fake,"GetFactoryCallCount"));if(!count)return 12;
    auto& server=cs2tool::IpcPipeServer::Instance();server.Start();
    bool ready=false;
    for(int i=0;i<100;++i) {if(WaitNamedPipeW(cs2tool::kPipeName,20)){ready=true;break;}Sleep(10);}
    if(!ready)return 13;
    HANDLE pipe=CreateFileW(cs2tool::kPipeName,GENERIC_READ|GENERIC_WRITE,0,nullptr,OPEN_EXISTING,0,nullptr);
    if(pipe==INVALID_HANDLE_VALUE)return 14;
    auto ping=Call(pipe,"ping");
    if(ping.find("\"pid\":"+std::to_string(GetCurrentProcessId()))==std::string::npos)return 15;
    if(count()!=0 || cs2tool::HammerBridge::Instance().IsInitialized())return 16;
    auto denied=Call(pipe,"initialize");
    if(denied.find("attestation required")==std::string::npos || count()!=0)return 17;
    auto again=Call(pipe,"ping");
    if(again.empty() || count()!=0)return 18;
    CloseHandle(pipe);server.Stop();
    std::cout<<"PASS real pipe startup + ping + rejected initialize; factory calls="<<count()<<'\n';
    // Process exit, not a DLL hot-unload: Stop's detached-thread semantics are not approved here.
    return 0;
}
