// ipc_pipe.h - Named pipe IPC server
#pragma once
#include "protocol.h"
#include <windows.h>
#include <string>
#include <thread>
#include <atomic>

namespace cs2tool {

class IpcPipeServer {
public:
    static IpcPipeServer& Instance();

    bool Start();
    void Stop();
    bool IsRunning() const { return running_.load(); }

private:
    IpcPipeServer() = default;
    ~IpcPipeServer() = default;
    IpcPipeServer(const IpcPipeServer&) = delete;
    IpcPipeServer& operator=(const IpcPipeServer&) = delete;

    void ServerThread();
    void ClientThread(HANDLE hPipe);
    bool SendResponse(HANDLE hPipe, const std::string& json_response);
    bool ReadRequest(HANDLE hPipe, std::string& out_json);
    std::string HandleRequest(const std::string& json_request);

    std::atomic<bool> running_{false};
    std::thread server_thread_;
    HANDLE server_thread_handle_{nullptr};
};

} // namespace cs2tool
