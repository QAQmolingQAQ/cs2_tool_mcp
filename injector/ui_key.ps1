# Usage: ui_key.ps1 -Vk 0x45 [-Shift] [-Ctrl] [-Title "Hammer*"]
# Forces target window foreground (AttachThreadInput trick) then sends one key.
param(
    [Parameter(Mandatory=$true)][string]$Vk,
    [switch]$Shift,
    [switch]$Ctrl,
    [string]$Title = "Hammer*"
)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class KK2 {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, uint f, UIntPtr e);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool on);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
}
"@
[KK2]::SetProcessDPIAware() | Out-Null
$code = [Convert]::ToInt32($Vk, 16)
$pr = Get-Process cs2 | Where-Object { $_.MainWindowTitle -like $Title } | Select-Object -First 1
$h = $pr.MainWindowHandle
[KK2]::ShowWindow($h, 9) | Out-Null
$fg = [KK2]::GetForegroundWindow()
$pid2 = 0; $fgThread = [KK2]::GetWindowThreadProcessId($fg, [ref]$pid2)
$pid3 = 0; $myThread_w = [KK2]::GetWindowThreadProcessId($h, [ref]$pid3)
$cur = [KK2]::GetCurrentThreadId()
[KK2]::AttachThreadInput($cur, $fgThread, $true) | Out-Null
[KK2]::AttachThreadInput($cur, $myThread_w, $true) | Out-Null
[KK2]::BringWindowToTop($h) | Out-Null
[KK2]::SetForegroundWindow($h) | Out-Null
[KK2]::AttachThreadInput($cur, $fgThread, $false) | Out-Null
[KK2]::AttachThreadInput($cur, $myThread_w, $false) | Out-Null
Start-Sleep -Milliseconds 500
if ($Ctrl) { [KK2]::keybd_event(0x11, 0, 0, [UIntPtr]::Zero); Start-Sleep -Milliseconds 60 }
if ($Shift) { [KK2]::keybd_event(0x10, 0, 0, [UIntPtr]::Zero); Start-Sleep -Milliseconds 60 }
[KK2]::keybd_event([byte]$code, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 80
[KK2]::keybd_event([byte]$code, 0, 2, [UIntPtr]::Zero)
if ($Shift) { [KK2]::keybd_event(0x10, 0, 2, [UIntPtr]::Zero) }
if ($Ctrl) { [KK2]::keybd_event(0x11, 0, 2, [UIntPtr]::Zero) }
Write-Output ("sent vk=0x{0:x2} fg_now=0x{1:x}" -f $code, [KK2]::GetForegroundWindow().ToInt64())
