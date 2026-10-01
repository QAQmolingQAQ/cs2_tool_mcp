param(
    [int64]$Hwnd = 0,
    [double]$Fx = 0.33,
    [double]$Fy = 0.42
)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class PE {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
  [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool on);
  [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, uint f, UIntPtr e);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
"@
[PE]::SetProcessDPIAware() | Out-Null
$h = [IntPtr]$Hwnd
[PE]::ShowWindow($h, 9) | Out-Null
$fg = [PE]::GetForegroundWindow()
$p1 = 0; $t1 = [PE]::GetWindowThreadProcessId($fg, [ref]$p1)
$p2 = 0; $t2 = [PE]::GetWindowThreadProcessId($h, [ref]$p2)
$cur = [PE]::GetCurrentThreadId()
[PE]::AttachThreadInput($cur, $t1, $true) | Out-Null
[PE]::AttachThreadInput($cur, $t2, $true) | Out-Null
[PE]::BringWindowToTop($h) | Out-Null
[PE]::SetForegroundWindow($h) | Out-Null
[PE]::AttachThreadInput($cur, $t1, $false) | Out-Null
[PE]::AttachThreadInput($cur, $t2, $false) | Out-Null
Start-Sleep -Milliseconds 700

$r = New-Object PE+RECT
[PE]::GetWindowRect($h, [ref]$r) | Out-Null
$x = [int]($r.L + ($r.R - $r.L) * $Fx)
$y = [int]($r.T + ($r.B - $r.T) * $Fy)
Write-Output "rect $($r.L),$($r.T),$($r.R),$($r.B) target $x,$y"

# move mouse into the viewport first (so Qt sees hover + focus), then Shift+E
[PE]::SetCursorPos($x, $y) | Out-Null
Start-Sleep -Milliseconds 250
[PE]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 60
[PE]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 350

# Shift+E -> Entity tool
[PE]::keybd_event(0x10, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 60
[PE]::keybd_event(0x45, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 60
[PE]::keybd_event(0x45, 0, 2, [UIntPtr]::Zero)
[PE]::keybd_event(0x10, 0, 2, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 500

# click again to place
[PE]::SetCursorPos($x, $y) | Out-Null
Start-Sleep -Milliseconds 200
[PE]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 60
[PE]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
Write-Output "placed at $x,$y"
