# 在 **Session 1（交互桌面）** 里截屏到 C:\cs2_tool_mcp\screen.png
# 必须由计划任务以 /IT 运行，否则 Session 0 的 SSH 进程截不到交互桌面。
# 出错时把原因写到 C:\cs2_tool_mcp\screen.err
$ErrorActionPreference = "Stop"
$out = "C:\cs2_tool_mcp\screen.png"
$errFile = "C:\cs2_tool_mcp\screen.err"
try {
  Remove-Item $errFile -ErrorAction SilentlyContinue
  Add-Type -AssemblyName System.Windows.Forms
  Add-Type -AssemblyName System.Drawing

  $vs = [System.Windows.Forms.SystemInformation]::VirtualScreen
  $bmp = New-Object System.Drawing.Bitmap $vs.Width, $vs.Height
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.CopyFromScreen($vs.Left, $vs.Top, 0, 0, $bmp.Size)
  $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
  $g.Dispose()
  $bmp.Dispose()

  # 记录会话/桌面信息，便于判断是否落在交互会话
  $info = "session=$((Get-Process -Id $PID).SessionId) size=$($vs.Width)x$($vs.Height)"
  $info | Set-Content "C:\cs2_tool_mcp\screen.txt" -Encoding UTF8
}
catch {
  $m = $_.Exception.GetType().FullName + " :: " + $_.Exception.Message
  $m | Set-Content $errFile -Encoding UTF8
}
