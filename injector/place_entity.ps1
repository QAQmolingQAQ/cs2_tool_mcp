Add-Type @"
using System;
using System.Runtime.InteropServices;
public class K {
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int n);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint x, uint y, uint d, UIntPtr e);
  [DllImport("user32.dll")] public static extern void keybd_event(byte k, byte s, uint f, UIntPtr e);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
}
"@

$proc = Get-Process cs2 | Where-Object { $_.MainWindowTitle -like "Hammer*" } | Select-Object -First 1
$hwnd = $proc.MainWindowHandle
[K]::ShowWindow($hwnd, 9) | Out-Null
[K]::SetForegroundWindow($hwnd) | Out-Null
Start-Sleep -Milliseconds 700

$r = New-Object K+RECT
[K]::GetWindowRect($hwnd, [ref]$r) | Out-Null
Write-Host "rect $($r.L),$($r.T),$($r.R),$($r.B)"

# Shift+E -> Entity tool
[K]::keybd_event(0x10, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 80
[K]::keybd_event(0x45, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 80
[K]::keybd_event(0x45, 0, 2, [UIntPtr]::Zero)
[K]::keybd_event(0x10, 0, 2, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 600

# click in the upper-left viewport
$x = [int]($r.L + ($r.R - $r.L) * 0.33)
$y = [int]($r.T + ($r.B - $r.T) * 0.42)
[K]::SetCursorPos($x, $y)
Start-Sleep -Milliseconds 300
[K]::mouse_event(0x0002, 0, 0, 0, [UIntPtr]::Zero)
Start-Sleep -Milliseconds 100
[K]::mouse_event(0x0004, 0, 0, 0, [UIntPtr]::Zero)
Write-Host "clicked $x,$y"
