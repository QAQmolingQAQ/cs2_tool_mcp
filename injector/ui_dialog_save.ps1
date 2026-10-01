# Finds the visible "Save Session" #32770 dialog of cs2, lists its child
# controls, and clicks the save button (match text containing Save / save char).
param([switch]$List)
Add-Type @"
using System;
using System.Text;
using System.Collections.Generic;
using System.Runtime.InteropServices;
public class DLG {
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
  [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
  [DllImport("user32.dll", EntryPoint="GetWindowLongW")] public static extern int GetWindowLong(IntPtr h, int idx);
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L,T,R,B; }
  public static IntPtr Find(uint pid) {
    IntPtr found = IntPtr.Zero;
    EnumWindows((h, p) => {
      uint wp; GetWindowThreadProcessId(h, out wp);
      if (wp == pid && IsWindowVisible(h)) {
        var t = new StringBuilder(256); GetWindowText(h, t, 256);
        if (t.ToString() == "Save Session") { found = h; return false; }
      }
      return true;
    }, IntPtr.Zero);
    return found;
  }
}
"@
$pidv = (Get-Process cs2 | Where-Object { $_.MainWindowTitle -like "Hammer*" } | Select-Object -First 1).Id
$dlg = [DLG]::Find([uint32]$pidv)
Write-Output "dialog=$dlg"
if ($dlg -eq [IntPtr]::Zero) { exit 1 }
$children = New-Object System.Collections.ArrayList
$cb = [DLG+EnumProc]{ param($h,$p)
    if ([DLG]::IsWindowVisible($h)) {
        $t = New-Object System.Text.StringBuilder 256; [DLG]::GetWindowText($h,$t,256) | Out-Null
        $c = New-Object System.Text.StringBuilder 256; [DLG]::GetClassName($h,$c,256) | Out-Null
        [void]$children.Add([pscustomobject]@{ H=$h; Text=$t.ToString(); Class=$c.ToString() })
    }
    return $true
}
[DLG]::EnumChildWindows($dlg, $cb, [IntPtr]::Zero) | Out-Null
foreach ($ch in $children) { Write-Output ("child {0} | {1} | {2}" -f $ch.H.ToInt64(), $ch.Text, $ch.Class) }
if (-not $List) {
    # Pick the default push button by dialog control ID (IDOK = 1).
    $save = $null
    foreach ($ch in $children) {
        if ($ch.Class -ne "Button") { continue }
        $id = [DLG]::GetWindowLong($ch.H, -12)   # GWL_ID
        if ($id -eq 1) { $save = $ch; break }
    }
    if (-not $save) {
        $save = $children | Where-Object { $_.Class -eq "Button" } | Select-Object -First 1
    }
    if ($save) {
        Write-Output ("CLICK -> {0} id=1 text='{1}'" -f $save.H.ToInt64(), $save.Text)
        [DLG]::SendMessage($save.H, 0x00F5, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null  # BM_CLICK
    }
}
