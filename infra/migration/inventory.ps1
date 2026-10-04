param(
    [Parameter(Mandatory = $true)][string]$Source,
    [Parameter(Mandatory = $true)][string]$Output,
    [switch]$MetadataOnly,
    [string]$Python = 'python'
)
$ErrorActionPreference = 'Stop'
$inventoryArgs = @((Join-Path $PSScriptRoot 'inventory.py'), 'scan', '--source', $Source, '--output', $Output)
if ($MetadataOnly) { $inventoryArgs += '--metadata-only' }
& $Python @inventoryArgs
exit $LASTEXITCODE
