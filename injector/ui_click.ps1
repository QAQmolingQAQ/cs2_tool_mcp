# Usage: ui_click.ps1 -X 800 -Y 400 [-Title "partial window title"]
# Foregrounds an optional window by title fragment, then left-clicks at screen (X,Y).
param(
    [int]$X = -1,
    [int]$Y = -1,
    [double]$Fx = -1.0,
    [double]$Fy = -1.0,
    [string]$Title = "",
    [int64]$Hwnd = 0
)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class UClick {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool on);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
"@
[UClick]::SetProcessDPIAware() | Out-Null
$clickX = $X; $clickY = $Y
$targets = @()
if ($Hwnd -ne 0) { $targets += [pscustomobject]@{ MainWindowHandle = [IntPtr]$Hwnd; MainWindowTitle = "hwnd" } }
elseif ($Title -ne "") {
    $targets = Get-Process | Where-Object { $_.MainWindowTitle -like "*$Title*" -and $_.MainWindowHandle -ne 0 }
}
if ($targets.Count -gt 0) {
    foreach ($pr in $targets) {
        $h = $pr.MainWindowHandle
        [UClick]::ShowWindow($h, 9) | Out-Null
        $fg = [UClick]::GetForegroundWindow()
        $p1=0; $t1=[UClick]::GetWindowThreadProcessId($fg,[ref]$p1)
        $p2=0; $t2=[UClick]::GetWindowThreadProcessId($h,[ref]$p2)
        $cur=[UClick]::GetCurrentThreadId()
        [UClick]::AttachThreadInput($cur,$t1,$true)|Out-Null
        [UClick]::AttachThreadInput($cur,$t2,$true)|Out-Null
        [UClick]::BringWindowToTop($h)|Out-Null
        [UClick]::SetForegroundWindow($h)|Out-Null
        [UClick]::AttachThreadInput($cur,$t1,$false)|Out-Null
        [UClick]::AttachThreadInput($cur,$t2,$false)|Out-Null
        Start-Sleep -Milliseconds 400
        if ($Fx -ge 0) {
            $rect = New-Object UClick+RECT
            [UClick]::GetWindowRect($h, [ref]$rect) | Out-Null
            $clickX = [int]($rect.L + ($rect.R - $rect.L) * $Fx)
            $clickY = [int]($rect.T + ($rect.B - $rect.T) * $Fy)
        }
    }
}
[UClick]::SetCursorPos($clickX, $clickY) | Out-Null
Start-Sleep -Milliseconds 150
[UClick]::mouse_event(0x0002, 0, 0, 0, [IntPtr]::Zero)
Start-Sleep -Milliseconds 40
[UClick]::mouse_event(0x0004, 0, 0, 0, [IntPtr]::Zero)
Write-Output "clicked $X,$Y"
