# Usage: ui_dialog_enter.ps1 -Dialog "Save Session" [-Keys "~"]
# Finds a top-level window by exact title, foregrounds it, sends keys.
param(
    [Parameter(Mandatory=$true)][string]$Dialog,
    [string]$Keys = "~"
)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class FWD {
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern IntPtr FindWindow(string c, string n);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
}
"@
Add-Type -AssemblyName System.Windows.Forms
$h = [FWD]::FindWindow($null, $Dialog)
Write-Output "hwnd=$h for '$Dialog'"
if ($h -ne [IntPtr]::Zero) {
    [FWD]::BringWindowToTop($h) | Out-Null
    [FWD]::SetForegroundWindow($h) | Out-Null
    Start-Sleep -Milliseconds 600
    [System.Windows.Forms.SendKeys]::SendWait($Keys)
    Write-Output "sent '$Keys'"
}
