# Usage: ui_win.ps1 -Action minimize|restore|foreground -Title "IDA*"
param(
    [Parameter(Mandatory=$true)][string]$Action,
    [Parameter(Mandatory=$true)][string]$Title
)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class UW {
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr h, IntPtr a, int x, int y, int cx, int cy, uint f);
}
"@
$procs = Get-Process | Where-Object { $_.MainWindowTitle -like "*$Title*" -and $_.MainWindowHandle -ne 0 }
foreach ($pr in $procs) {
    switch ($Action) {
        "minimize"   { [UW]::ShowWindow($pr.MainWindowHandle, 6) | Out-Null }
        "restore"    { [UW]::ShowWindow($pr.MainWindowHandle, 9) | Out-Null }
        "foreground" { [UW]::SetForegroundWindow($pr.MainWindowHandle) | Out-Null }
        "moveoff"    { [UW]::SetWindowPos($pr.MainWindowHandle, [IntPtr]::Zero, 4000, 0, 800, 600, 0x0040) | Out-Null }
    }
    Write-Output "$Action -> $($pr.MainWindowTitle)"
}
