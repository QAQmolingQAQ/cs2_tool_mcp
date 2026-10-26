# Stage verified bytes and atomically install without truncating an existing DLL.
function Publish-BridgeArtifact {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$ArtifactRoot
    )
    $Source = [IO.Path]::GetFullPath($Source)
    $Destination = [IO.Path]::GetFullPath($Destination)
    if ($Source -eq $Destination) { throw 'Source and destination must differ.' }
    $hash = (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash.ToLowerInvariant()
    $folder = Join-Path $ArtifactRoot $hash
    [IO.Directory]::CreateDirectory($folder) | Out-Null
    $artifact = Join-Path $folder 'cs2_tool.dll'
    if (!(Test-Path -LiteralPath $artifact)) {
        $staging = Join-Path $folder ([guid]::NewGuid().ToString('N')+'.tmp')
        try {
            [IO.File]::Copy($Source, $staging, $false)
            if ((Get-FileHash -LiteralPath $staging).Hash.ToLowerInvariant() -ne $hash) {
                throw 'Build output changed during staging.'
            }
            try { [IO.File]::Move($staging, $artifact) }
            catch { if (!(Test-Path -LiteralPath $artifact)) { throw } }
        } finally { if (Test-Path -LiteralPath $staging) { [IO.File]::Delete($staging) } }
    }
    if ((Get-FileHash -LiteralPath $artifact).Hash.ToLowerInvariant() -ne $hash) {
        throw 'Content-addressed artifact hash mismatch.'
    }
    $candidate = Join-Path ([IO.Path]::GetDirectoryName($Destination)) (
        '.cs2_tool.'+[guid]::NewGuid().ToString('N')+'.pending')
    $status = 'deployed'
    $reason = $null
    try {
        [IO.File]::Copy($artifact, $candidate, $false)
        if ((Get-FileHash -LiteralPath $candidate).Hash.ToLowerInvariant() -ne $hash) {
            throw 'Deployment candidate hash mismatch.'
        }
        try {
            if (Test-Path -LiteralPath $Destination) {
                [IO.File]::Replace($candidate, $Destination, [System.Management.Automation.Language.NullString]::Value)
            } else {
                [IO.File]::Move($candidate, $Destination)
            }
        } catch [IO.IOException] {
            # Only sharing/lock violations are a deferred deployment. Other failures remain errors.
            $win32 = $_.Exception.HResult -band 0xffff
            if ($win32 -notin @(32,33)) { throw }
            $status = 'deployment_pending'
            $reason = 'destination_locked'
        }
    } finally {
        if (Test-Path -LiteralPath $candidate) { [IO.File]::Delete($candidate) }
    }
    [pscustomobject]@{
        status=$status; reason=$reason; sha256=$hash
        artifact=$artifact; destination=$Destination
        running_process_updated=$false
    }
}
