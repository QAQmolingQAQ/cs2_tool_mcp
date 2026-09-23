# 在 **Session 1（交互桌面）** 里模拟鼠标/键盘。
# 由计划任务以 /IT 运行；命令行参数形式不适合 schtasks，故从文件读指令。
#
# 指令文件 C:\cs2_tool_mcp\input.txt（只执行第一行非空内容）:
#   move   X Y
#   click  X Y [left|right|middle]
#   dblclick X Y [left]
#   drag   X1 Y1 X2 Y2 [left]
#   wheel  X Y DELTA
#   key    ctrl+z            （修饰键用 + 连接，键名见下方 $vkNames）
#   type   字面文本          （走 SendKeys，支持中文以外的基本字符）
#
# 结果写到 C:\cs2_tool_mcp\input.out
$ErrorActionPreference = "Stop"
$out = "C:\cs2_tool_mcp\input.out"

Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class U {
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] public static extern void mouse_event(uint f, uint dx, uint dy, uint d, UIntPtr e);
    [DllImport("user32.dll")] public static extern void keybd_event(byte vk, byte scan, uint f, UIntPtr e);
    public const uint LEFTDOWN=0x0002, LEFTUP=0x0004, RIGHTDOWN=0x0008, RIGHTUP=0x0010;
    public const uint MIDDLEDOWN=0x0020, MIDDLEUP=0x0040, WHEEL=0x0800;
    public const uint KEYUP=0x0002;

    // --- 窗口置前（AppActivate 不保证抢到前台，尤其 SSH/后台任务场景） ---
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h, int cmd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr h);
    [DllImport("user32.dll")] public static extern IntPtr SetFocus(IntPtr h);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, IntPtr pid);
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint a, uint b, bool attach);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] public static extern int GetWindowTextW(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumProc cb, IntPtr p);
    public delegate bool EnumProc(IntPtr h, IntPtr p);

    static IntPtr _found = IntPtr.Zero;
    static bool OnEnum(IntPtr h, IntPtr p) {
        if (!IsWindowVisible(h)) return true;
        string t = TitleOf(h);
        if (t.Length > 0 && t.IndexOf(_want, StringComparison.OrdinalIgnoreCase) >= 0) {
            _found = h; return false;
        }
        return true;
    }
    static string _want = "";
    // 返回句柄数值：用 long 而不是 IntPtr，避免 PowerShell 把 IntPtr.Zero 变成空串
    public static long FindLike(string part) {
        _want = part; _found = IntPtr.Zero;
        EnumProc cb = new EnumProc(OnEnum);
        EnumWindows(cb, IntPtr.Zero);
        GC.KeepAlive(cb);
        return _found.ToInt64();
    }
    public static string TitleOf(IntPtr h) {
        var sb = new StringBuilder(512);
        GetWindowTextW(h, sb, 512);
        return sb.ToString();
    }
    public static string ForegroundTitle() { return TitleOf(GetForegroundWindow()); }
    // 列出所有可见顶层窗口标题（排查"目标窗口到底叫什么"用）
    public static string[] ListTitles() {
        var res = new System.Collections.Generic.List<string>();
        EnumWindows(delegate(IntPtr h, IntPtr p) {
            if (IsWindowVisible(h)) {
                string t = TitleOf(h);
                if (t.Length > 0) res.Add(t);
            }
            return true;
        }, IntPtr.Zero);
        return res.ToArray();
    }
}
"@

$vkNames = @{
  "ctrl"=0x11; "shift"=0x10; "alt"=0x12; "win"=0x5B
  "enter"=0x0D; "return"=0x0D; "esc"=0x1B; "escape"=0x1B; "tab"=0x09; "space"=0x20
  "backspace"=0x08; "delete"=0x2E; "del"=0x2E; "insert"=0x2D; "home"=0x24; "end"=0x23
  "pageup"=0x21; "pagedown"=0x22; "up"=0x26; "down"=0x28; "left"=0x25; "right"=0x27
  "f1"=0x70; "f2"=0x71; "f3"=0x72; "f4"=0x73; "f5"=0x74; "f6"=0x75
  "f7"=0x76; "f8"=0x77; "f9"=0x78; "f10"=0x79; "f11"=0x7A; "f12"=0x7B
}

function Get-Vk([string]$name) {
  $n = $name.Trim().ToLower()
  if ($vkNames.ContainsKey($n)) { return [byte]$vkNames[$n] }
  if ($n.Length -eq 1) { return [byte][char]([char]::ToUpper($n[0])) }
  throw "unknown key: $name"
}

function Do-KeyCombo([string]$combo) {
  $parts = $combo -split '\+'
  $main = $parts[-1]
  $mods = @()
  if ($parts.Count -gt 1) { $mods = $parts[0..($parts.Count-2)] }
  foreach ($m in $mods) { [U]::keybd_event((Get-Vk $m), 0, 0, [UIntPtr]::Zero) }
  $vk = Get-Vk $main
  [U]::keybd_event($vk, 0, 0, [UIntPtr]::Zero)
  [U]::keybd_event($vk, 0, [U]::KEYUP, [UIntPtr]::Zero)
  for ($i = $mods.Count - 1; $i -ge 0; $i--) { [U]::keybd_event((Get-Vk $mods[$i]), 0, [U]::KEYUP, [UIntPtr]::Zero) }
}

function Focus-Window([string]$title) {
  # 用 AttachThreadInput 绕过 Windows 前台锁再置前。
  # 注意：AppActivate 不保证抢到前台；而 key/keyto 必须在此之后**同一个任务内**发出，
  # 否则下一个 schtasks 任务启动的 powershell 会把前台抢回去，按键就打空了。
  $h = [U]::FindLike($title)
  if ($h -eq 0) { throw "window not found: $title" }
  $hwnd = [IntPtr]$h
  if ([U]::IsIconic($hwnd)) { [void][U]::ShowWindow($hwnd, 9) }   # SW_RESTORE
  $fg = [U]::GetForegroundWindow()
  $fgTid = [U]::GetWindowThreadProcessId($fg, [IntPtr]::Zero)
  $tgTid = [U]::GetWindowThreadProcessId($hwnd, [IntPtr]::Zero)
  $my = [U]::GetCurrentThreadId()
  [void][U]::AttachThreadInput($my, $fgTid, $true)
  [void][U]::AttachThreadInput($my, $tgTid, $true)
  [void][U]::BringWindowToTop($hwnd)
  [void][U]::SetForegroundWindow($hwnd)
  [void][U]::SetFocus($hwnd)
  [void][U]::AttachThreadInput($my, $tgTid, $false)
  [void][U]::AttachThreadInput($my, $fgTid, $false)
  Start-Sleep -Milliseconds 350
}

try {
  $line = (Get-Content "C:\cs2_tool_mcp\input.txt" | Where-Object { $_.Trim() -ne "" } | Select-Object -First 1)
  if (-not $line) { throw "input.txt 为空" }
  $t = $line.Trim() -split '\s+', 2
  $cmd = $t[0].ToLower()
  # rest = everything after the first token (window titles may contain spaces)
  $rest = if ($t.Count -gt 1) { ($t[1..($t.Count-1)] -join ' ') } else { "" }
  $a = $rest -split '\s+'

  $script:extra = ""
  switch ($cmd) {
    "move"  { [void][U]::SetCursorPos([int]$a[0], [int]$a[1]) }
    "click" {
      [void][U]::SetCursorPos([int]$a[0], [int]$a[1]); Start-Sleep -Milliseconds 60
      $btn = if ($a.Count -gt 2) { $a[2].ToLower() } else { "left" }
      switch ($btn) {
        "right"  { [U]::mouse_event([U]::RIGHTDOWN,0,0,0,[UIntPtr]::Zero); [U]::mouse_event([U]::RIGHTUP,0,0,0,[UIntPtr]::Zero) }
        "middle" { [U]::mouse_event([U]::MIDDLEDOWN,0,0,0,[UIntPtr]::Zero); [U]::mouse_event([U]::MIDDLEUP,0,0,0,[UIntPtr]::Zero) }
        default  { [U]::mouse_event([U]::LEFTDOWN,0,0,0,[UIntPtr]::Zero); [U]::mouse_event([U]::LEFTUP,0,0,0,[UIntPtr]::Zero) }
      }
    }
    "dblclick" {
      [void][U]::SetCursorPos([int]$a[0], [int]$a[1]); Start-Sleep -Milliseconds 60
      foreach ($i in 1..2) {
        [U]::mouse_event([U]::LEFTDOWN,0,0,0,[UIntPtr]::Zero); [U]::mouse_event([U]::LEFTUP,0,0,0,[UIntPtr]::Zero)
        Start-Sleep -Milliseconds 80
      }
    }
    "drag" {
      [void][U]::SetCursorPos([int]$a[0], [int]$a[1]); Start-Sleep -Milliseconds 80
      [U]::mouse_event([U]::LEFTDOWN,0,0,0,[UIntPtr]::Zero)
      $x0 = [int]$a[0]; $y0 = [int]$a[1]; $x1 = [int]$a[2]; $y1 = [int]$a[3]
      $steps = 12
      for ($i = 1; $i -le $steps; $i++) {
        [void][U]::SetCursorPos([int]($x0 + ($x1-$x0)*$i/$steps), [int]($y0 + ($y1-$y0)*$i/$steps))
        Start-Sleep -Milliseconds 25
      }
      [U]::mouse_event([U]::LEFTUP,0,0,0,[UIntPtr]::Zero)
    }
    "wheel" {
      [void][U]::SetCursorPos([int]$a[0], [int]$a[1]); Start-Sleep -Milliseconds 60
      $delta = if ($a.Count -gt 2) { [uint32]$a[2] } else { 120 }
      [U]::mouse_event([U]::WHEEL, 0, 0, $delta, [UIntPtr]::Zero)
    }
    "key"  {
      # 回读实际前台窗口：若不是目标窗口，按键会打空（这是 Ctrl+N 无效的真正原因）
      $script:extra = " -> fg='$([U]::ForegroundTitle())'"
      Do-KeyCombo $rest
    }
    "type" { [System.Windows.Forms.SendKeys]::SendWait($rest) }
    "windows" {
      $script:extra = " -> " + ([U]::ListTitles() -join " | ")
    }
    "activate" {
      Focus-Window $rest
      # 回读实际前台标题：只有它等于目标窗口，后续 key 才真的会送达
      $script:extra = " -> fg='$([U]::ForegroundTitle())'"
    }
    "keyto" {
      # keyto <window title> | <key combo>
      # 把"抢前台 + 发键"放进同一个任务里完成 —— 分两个任务跑的话，
      # 后一个任务的 powershell 窗口会把前台抢回去，按键就打到控制台上了。
      $sep = $rest.IndexOf('|')
      if ($sep -lt 0) { throw "usage: keyto <window> | <keycombo>" }
      $title = $rest.Substring(0, $sep).Trim()
      $combo = $rest.Substring($sep + 1).Trim()
      Focus-Window $title
      Do-KeyCombo $combo
      Start-Sleep -Milliseconds 200
      $script:extra = " -> fg='$([U]::ForegroundTitle())' combo='$combo'"
    }
    default { throw "unknown command: $cmd" }
  }
  "OK $line$script:extra" | Set-Content $out -Encoding UTF8
}
catch {
  "FAIL $($_.Exception.Message)$script:extra" | Set-Content $out -Encoding UTF8
}
