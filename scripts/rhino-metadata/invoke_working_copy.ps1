[CmdletBinding()]
param(
    [Parameter(Mandatory=$true)][string]$MetadataPath,
    [Parameter(Mandatory=$true)][string]$OutputPath,
    [Parameter(Mandatory=$true)][string]$OccurrencesPath
)
$ErrorActionPreference = 'Stop'
$processes = @(Get-Process -Name Rhino -ErrorAction SilentlyContinue)
if ($processes.Count -ne 1) { throw 'Require exactly one running Rhino process' }
$metadata = Get-Content -LiteralPath $MetadataPath -Raw -Encoding utf8 | ConvertFrom-Json
$bridge = Join-Path $env:LOCALAPPDATA 'Codex\RhinoBlenderPipeline'
[System.IO.Directory]::CreateDirectory($bridge) | Out-Null
$requestId = [guid]::NewGuid().ToString('D')
$responsePath = Join-Path $bridge ($requestId + '.copy_response.json')
$request = @{
    request_id = $requestId
    metadata_request_id = $metadata.automation.request_id
    metadata_path = [System.IO.Path]::GetFullPath($MetadataPath)
    output_path = [System.IO.Path]::GetFullPath($OutputPath)
    occurrences_path = [System.IO.Path]::GetFullPath($OccurrencesPath)
    response_path = $responsePath
}
$requestPath = Join-Path $bridge 'copy_request.json'
$request | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $requestPath -Encoding utf8
$scriptPath = Join-Path $PSScriptRoot 'prepare_working_copy.py'
$rhino = $null
try {
    $rhino = New-Object -ComObject 'Rhino.Interface.7'
    $accepted = $rhino.RunScript(('_-RunPythonScript ("{0}")' -f $scriptPath.Replace('"','""')), 0)
    if (-not $accepted) { throw 'Rhino rejected script; inspect before retry' }
    if (-not (Test-Path -LiteralPath $responsePath)) { throw 'Missing response; completion unknown, inspect outputs before retry' }
    $response = Get-Content -LiteralPath $responsePath -Raw -Encoding utf8 | ConvertFrom-Json
    if ($response.request_id -ne $requestId -or -not $response.ok) {
        $response | ConvertTo-Json -Depth 5
        throw 'Rhino working-copy export failed; inspect files and source state before retry'
    }
    $response | ConvertTo-Json -Depth 5 -Compress
}
finally {
    if ($null -ne $rhino) { [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($rhino) }
}
