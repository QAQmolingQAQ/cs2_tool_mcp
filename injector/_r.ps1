Add-Type @"
using System;using System.Runtime.InteropServices;
public class R1{[DllImport("user32.dll")]public static extern bool SetProcessDPIAware();[DllImport("user32.dll")]public static extern bool GetWindowRect(IntPtr h,out RECT r);[StructLayout(LayoutKind.Sequential)]public struct RECT{public int L,T,R,B;}}
"@
[R1]::SetProcessDPIAware()|Out-Null
$p=Get-Process cs2|?{$_.MainWindowTitle -like "Hammer*"}|select -First 1
$r=New-Object R1+RECT;[R1]::GetWindowRect($p.MainWindowHandle,[ref]$r)|Out-Null
"rect $($r.L),$($r.T),$($r.R),$($r.B)"
