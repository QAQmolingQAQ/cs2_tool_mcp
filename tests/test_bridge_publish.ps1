$ErrorActionPreference='Stop'
. "$PSScriptRoot/../scripts/publish_bridge_artifact.ps1"
$root=Join-Path ([IO.Path]::GetTempPath()) ('cs2_publish_test_'+[guid]::NewGuid().ToString('N'))
[IO.Directory]::CreateDirectory($root) | Out-Null
try {
    $src=Join-Path $root 'source.dll'; $dst=Join-Path $root 'active.dll'
    [IO.File]::WriteAllText($src,'new-content')
    [IO.File]::WriteAllText($dst,'old-content')
    $old=(Get-FileHash -LiteralPath $dst).Hash
    $lock=[IO.File]::Open($dst,[IO.FileMode]::Open,[IO.FileAccess]::Read,[IO.FileShare]::Read)
    try {
        $r=Publish-BridgeArtifact -Source $src -Destination $dst -ArtifactRoot (Join-Path $root 'artifacts')
        if ($r.status -ne 'deployment_pending' -or (Get-FileHash -LiteralPath $dst).Hash -ne $old) { throw 'Locked destination was not preserved.' }
        if ((Get-FileHash -LiteralPath $r.artifact).Hash.ToLowerInvariant() -ne $r.sha256) { throw 'Staged artifact mismatch.' }
    } finally { $lock.Dispose() }
    $r=Publish-BridgeArtifact -Source $src -Destination $dst -ArtifactRoot (Join-Path $root 'artifacts')
    if ($r.status -ne 'deployed' -or [IO.File]::ReadAllText($dst) -ne 'new-content') { throw 'Unlocked replacement failed.' }
    $fresh=Join-Path $root 'fresh.dll'
    $r=Publish-BridgeArtifact -Source $src -Destination $fresh -ArtifactRoot (Join-Path $root 'artifacts')
    if ($r.status -ne 'deployed') { throw 'Fresh install failed.' }
    [IO.File]::WriteAllText($r.artifact,'tampered')
    $rejected=$false
    try { Publish-BridgeArtifact -Source $src -Destination $dst -ArtifactRoot (Join-Path $root 'artifacts') | Out-Null }
    catch { $rejected=$true }
    if (!$rejected -or [IO.File]::ReadAllText($dst) -ne 'new-content') { throw 'Tampered artifact was accepted.' }
    if (Get-ChildItem -LiteralPath $root -Filter '*.pending' -Force) { throw 'Candidate leaked.' }
    'PASS: locked preservation, verified staging, unlocked atomic replacement, fresh install, tamper rejection'
} finally {
    # Only delete the exact newly created test directory, under the resolved temp root.
    $resolved=[IO.Path]::GetFullPath($root)
    $temp=[IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\')+'\'
    if (!$resolved.StartsWith($temp,[StringComparison]::OrdinalIgnoreCase) -or !(Split-Path $resolved -Leaf).StartsWith('cs2_publish_test_')) { throw 'Unsafe cleanup path.' }
    Remove-Item -LiteralPath $resolved -Recurse -Force
}
