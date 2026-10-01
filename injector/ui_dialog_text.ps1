# Dumps text of every child control in a cs2 top-level dialog with given title,
# optionally clicks IDOK (1) / IDYES (6) / IDCANCEL (2) button.
param(
    [Parameter(Mandatory=$true)][string]$Dialog,
    [int]$ClickId = 0
)
Add-Type @"
using System;
using System.Text;
using System.Runtime.InteropServices;
public class DTX {
  public delegate bool EnumProc(IntPtr h, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr h, EnumProc cb, IntPtr p);
  [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h, uint m, IntPtr w, IntPtr l);
  [DllImport("user32.dll", EntryPoint="GetWindowLongW")] public static extern int GetWindowLong(IntPtr h, int idx);
}
"@
$pidv = (Get-Process cs2 | Select-Object -First 1).Id
$dlg = [IntPtr]::Zero
$fnd = [DTX+EnumProc]{ param($h,$p)
    $wp=0; [DTX]::GetWindowThreadProcessId($h,[ref]$wp) | Out-Null
    if ($wp -eq $script:pidv -and [DTX]::IsWindowVisible($h)) {
        $t=New-Object System.Text.StringBuilder 256; [DTX]::GetWindowText($h,$t,256)|Out-Null
        if ($t.ToString() -eq $script:Dialog) { $script:dlg=$h; return $false }
    }
    return $true
}
[DTX]::EnumWindows($fnd,[IntPtr]::Zero) | Out-Null
Write-Output "dialog=$($dlg.ToInt64())"
if ($dlg -eq [IntPtr]::Zero) { exit 1 }
$kids = New-Object System.Collections.ArrayList
$cb = [DTX+EnumProc]{ param($h,$p)
    $t=New-Object System.Text.StringBuilder 1024; [DTX]::GetWindowText($h,$t,1024)|Out-Null
    $c=New-Object System.Text.StringBuilder 256; [DTX]::GetClassName($h,$c,256)|Out-Null
    $id=[DTX]::GetWindowLong($h,-12)
    [void]$kids.Add([pscustomobject]@{ H=$h; Text=$t.ToString(); Class=$c.ToString(); Id=$id })
    return $true
}
[DTX]::EnumChildWindows($dlg,$cb,[IntPtr]::Zero) | Out-Null
foreach($k in $kids){ Write-Output ("id={0} class={1} text={2}" -f $k.Id,$k.Class,$k.Text) }
if ($ClickId -ne 0) {
    $b = $kids | Where-Object { $_.Class -eq "Button" -and $_.Id -eq $ClickId } | Select-Object -First 1
    if ($b) { [DTX]::SendMessage($b.H,0x00F5,[IntPtr]::Zero,[IntPtr]::Zero)|Out-Null; Write-Output "clicked id=$ClickId" }
}
