Add-Type @"
using System;
using System.Runtime.InteropServices;
public class M {
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
  [DllImport("user32.dll")] public static extern int GetSystemMetrics(int i);
}
"@
[M]::SetProcessDPIAware() | Out-Null
"physical=$([M]::GetSystemMetrics(78))x$([M]::GetSystemMetrics(79))"
