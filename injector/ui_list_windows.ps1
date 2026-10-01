# Lists visible top-level windows (pid, hwnd, title, class) for cs2 processes.
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class WL {
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  public static List<string> Go(uint want) {
    var outp = new List<string>();
    EnumWindows((h, p) => {
      uint pid; GetWindowThreadProcessId(h, out pid);
      if (pid == want && IsWindowVisible(h)) {
        var t = new StringBuilder(256); GetWindowText(h, t, 256);
        var c = new StringBuilder(256); GetClassName(h, c, 256);
        outp.Add(h.ToInt64().ToString() + " | " + t + " | " + c);
      }
      return true;
    }, IntPtr.Zero);
    return outp;
  }
}
"@
foreach ($pr in Get-Process cs2) {
  Write-Output "--- PID $($pr.Id) ---"
  foreach ($line in [WL]::Go([uint32]$pr.Id)) { Write-Output $line }
}
