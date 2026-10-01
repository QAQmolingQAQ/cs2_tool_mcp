# Usage: ui_find_click.ps1 -Needle "Hammer"
# Walks UI Automation controls across all top-level windows, prints matching
# buttons (Name/ControlType/BoundingRectangle) and optionally clicks the first.
param(
    [Parameter(Mandatory=$true)][string]$Needle,
    [string]$Wnd = "",
    [switch]$Click
)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$root = [System.Windows.Automation.AutomationElement]::RootElement
$cond = New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button)
$found = @()
foreach ($top in $root.FindAll([System.Windows.Automation.TreeScope]::Children, [System.Windows.Automation.Condition]::TrueCondition)) {
    $t = $top.Current.Name
    if ($Wnd -ne "" -and $t -notlike "*$Wnd*") { continue }
    if ($Wnd -eq "" -and $t -notlike "*Asset Browser*" -and $t -notlike "*Hammer*" -and $t -notlike "*Save*") { continue }
    foreach ($b in $top.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)) {
        $n = $b.Current.Name
        if ($n -like "*$Needle*") {
            $r = $b.Current.BoundingRectangle
            $found += [pscustomobject]@{ Name=$n; X=[int]($r.X+$r.Width/2); Y=[int]($r.Y+$r.Height/2); W=$r.Width; H=$r.Height; El=$b }
        }
    }
}
foreach ($f in $found) {
    Write-Output ("BUTTON name={0} center=({1},{2}) size={3}x{4}" -f $f.Name,$f.X,$f.Y,[int]$f.W,[int]$f.H)
}
if ($Click -and $found.Count -gt 0) {
    $tgt = $found[0]
    try {
        $inv = $tgt.El.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern)
        $inv.Invoke()
        Write-Output "INVOKED $($tgt.Name)"
    } catch {
        Add-Type @"
using System;
using System.Runtime.InteropServices;
public class UC2 {
  [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
  [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, IntPtr e);
}
"@
        [UC2]::SetCursorPos($tgt.X,$tgt.Y) | Out-Null
        Start-Sleep -Milliseconds 200
        [UC2]::mouse_event(0x0002,0,0,0,[IntPtr]::Zero); Start-Sleep -Milliseconds 40
        [UC2]::mouse_event(0x0004,0,0,0,[IntPtr]::Zero)
        Write-Output "CLICKED $($tgt.Name) at $($tgt.X),$($tgt.Y)"
    }
}
if (-not $found) { Write-Output "NO_BUTTON $Needle" }
