param([ValidateSet("Debug", "Release")][string]$Configuration = "Release")
$ErrorActionPreference = "Stop"
$repo = $PSScriptRoot
$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (!(Test-Path -LiteralPath $vswhere)) { throw "Visual Studio Build Tools with C++ tools is required." }
$vs = (& $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -format json | ConvertFrom-Json) | Select-Object -First 1
if (!$vs) { throw "No Visual Studio C++ toolchain found." }
$cmakeCommand = Get-Command cmake -ErrorAction SilentlyContinue
if ($cmakeCommand) { $cmake = $cmakeCommand.Source } else {
    $cmake = Join-Path $vs.installationPath "Common7\IDE\CommonExtensions\Microsoft\CMake\CMake\bin\cmake.exe"
}
if (!(Test-Path -LiteralPath $cmake)) { throw "CMake not found. Install the Visual Studio CMake component." }
$major = ([version]$vs.installationVersion).Major
$generators = @{17="Visual Studio 17 2022"; 18="Visual Studio 18 2026"}
if (!$generators.ContainsKey($major)) { throw "Unsupported Visual Studio version: $major" }
$build = Join-Path $repo "injected_dll\build_vs$major"
& $cmake -S (Join-Path $repo "injected_dll") -B $build -G $generators[$major] -A x64 "-DCMAKE_GENERATOR_INSTANCE=$($vs.installationPath)"
if ($LASTEXITCODE -ne 0) { throw "CMake configure failed." }
& $cmake --build $build --config $Configuration --parallel
if ($LASTEXITCODE -ne 0) { throw "C++ build failed." }
$dll = Join-Path $build "$Configuration\cs2_tool.dll"
Copy-Item -LiteralPath $dll -Destination (Join-Path $repo "cs2_tool.dll") -Force
Write-Host "Built: $dll"
