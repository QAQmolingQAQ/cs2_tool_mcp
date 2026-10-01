# Usage: ui_keys.ps1 -Keys "^n"   (WScript.Shell SendKeys syntax; ^=Ctrl, + =Shift)
# Optionally foregrounds a window by title fragment first.
param(
    [Parameter(Mandatory=$true)][string]$Keys,
    [string]$Title = "Hammer"
)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class UK {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
}
"@
if ($Title -ne "") {
    $pr = Get-Process | Where-Object { $_.MainWindowTitle -like "*$Title*" -and $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if ($pr) {
        [UK]::ShowWindow($pr.MainWindowHandle, 9) | Out-Null
        [UK]::SetForegroundWindow($pr.MainWindowHandle) | Out-Null
        Start-Sleep -Milliseconds 500
    } else {
        Write-Output "no window with title like '$Title'"
    }
}
Add-Type -AssemblyName System.Windows.Forms
[System.Windows.Forms.SendKeys]::SendWait($Keys)
Write-Output "sent $Keys"
