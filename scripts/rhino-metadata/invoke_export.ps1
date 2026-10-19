[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [ValidateRange(5, 1800)]
    [int]$TimeoutSeconds = 300
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-ResultAndExit {
    param(
        [Parameter(Mandatory = $true)]
        [hashtable]$Result,

        [Parameter(Mandatory = $true)]
        [int]$ExitCode
    )

    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $Result | ConvertTo-Json -Depth 8 -Compress
    exit $ExitCode
}

function Write-AtomicJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,

        [Parameter(Mandatory = $true)]
        [object]$Value
    )

    $temporaryPath = "{0}.{1}.tmp" -f $Path, [Guid]::NewGuid().ToString("N")
    $utf8WithoutBom = New-Object System.Text.UTF8Encoding($false)
    $json = $Value | ConvertTo-Json -Depth 8
    [System.IO.File]::WriteAllText($temporaryPath, $json, $utf8WithoutBom)
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Force
    }
    Move-Item -LiteralPath $temporaryPath -Destination $Path
}

$rhinoProcesses = @(Get-Process -Name "Rhino" -ErrorAction SilentlyContinue)
if ($rhinoProcesses.Count -eq 0) {
    Write-ResultAndExit -ExitCode 10 -Result @{
        ok = $false
        error_code = "RHINO_NOT_RUNNING"
        message = "No Rhino instance is running. Open Rhino 7 and the intended document, then retry."
    }
}
if ($rhinoProcesses.Count -gt 1) {
    Write-ResultAndExit -ExitCode 11 -Result @{
        ok = $false
        error_code = "MULTIPLE_RHINO_INSTANCES"
        message = "Multiple Rhino instances are running. Leave only the intended Rhino 7 instance open, then retry."
        process_ids = @($rhinoProcesses | ForEach-Object { $_.Id })
    }
}

$resolvedOutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$outputDirectory = [System.IO.Path]::GetDirectoryName($resolvedOutputPath)
if ([string]::IsNullOrWhiteSpace($outputDirectory)) {
    Write-ResultAndExit -ExitCode 16 -Result @{
        ok = $false
        error_code = "INVALID_OUTPUT_PATH"
        message = "OutputPath must include an absolute or resolvable directory."
    }
}
[System.IO.Directory]::CreateDirectory($outputDirectory) | Out-Null

$bridgeDirectory = Join-Path $env:LOCALAPPDATA "Codex\RhinoBlenderPipeline"
[System.IO.Directory]::CreateDirectory($bridgeDirectory) | Out-Null
$requestPath = Join-Path $bridgeDirectory "request.json"
$responsePath = Join-Path $bridgeDirectory "response.json"
$exporterPath = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "export_rhino_metadata.py"))
$requestId = [Guid]::NewGuid().ToString("D")

if (Test-Path -LiteralPath $responsePath) {
    Remove-Item -LiteralPath $responsePath -Force
}

$request = [ordered]@{
    schema_version = 1
    request_id = $requestId
    output_path = $resolvedOutputPath
    response_path = $responsePath
    created_utc = [DateTime]::UtcNow.ToString("o")
}
Write-AtomicJson -Path $requestPath -Value $request

$rhino = $null
try {
    $rhino = New-Object -ComObject "Rhino.Interface.7"
    $escapedExporterPath = $exporterPath.Replace('"', '""')
    $command = '_-RunPythonScript ("{0}")' -f $escapedExporterPath
    $accepted = $rhino.RunScript($command, 0)
    if (-not $accepted) {
        Write-ResultAndExit -ExitCode 13 -Result @{
            ok = $false
            request_id = $requestId
            error_code = "RHINO_REJECTED_COMMAND"
            message = "Rhino did not accept the RunPythonScript command."
        }
    }

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    $response = $null
    while ([DateTime]::UtcNow -lt $deadline) {
        if (Test-Path -LiteralPath $responsePath) {
            try {
                $candidate = Get-Content -LiteralPath $responsePath -Raw -Encoding UTF8 | ConvertFrom-Json
                if ($candidate.request_id -eq $requestId) {
                    $response = $candidate
                    break
                }
            }
            catch {
                # The exporter may still be finishing the atomic response publication.
            }
        }
        Start-Sleep -Milliseconds 200
    }

    if ($null -eq $response) {
        Write-ResultAndExit -ExitCode 14 -Result @{
            ok = $false
            request_id = $requestId
            error_code = "EXPORT_TIMEOUT"
            message = "Timed out waiting for the matching Rhino export response. Inspect Rhino command history before retrying."
            output_path = $resolvedOutputPath
        }
    }
    if (-not $response.ok) {
        Write-ResultAndExit -ExitCode 15 -Result @{
            ok = $false
            request_id = $requestId
            error_code = "RHINO_EXPORT_FAILED"
            message = $response.message
            traceback = $response.traceback
            output_path = $resolvedOutputPath
        }
    }
    if (-not (Test-Path -LiteralPath $resolvedOutputPath -PathType Leaf)) {
        Write-ResultAndExit -ExitCode 17 -Result @{
            ok = $false
            request_id = $requestId
            error_code = "OUTPUT_NOT_FOUND"
            message = "Rhino reported success but the metadata file is missing."
            output_path = $resolvedOutputPath
        }
    }

    Write-ResultAndExit -ExitCode 0 -Result @{
        ok = $true
        request_id = $requestId
        rhino_process_id = $rhinoProcesses[0].Id
        output_path = $resolvedOutputPath
        output_bytes = (Get-Item -LiteralPath $resolvedOutputPath).Length
        document = $response.document
        counts = $response.counts
        exported_utc = $response.exported_utc
    }
}
catch {
    Write-ResultAndExit -ExitCode 12 -Result @{
        ok = $false
        request_id = $requestId
        error_code = "COM_AUTOMATION_FAILED"
        message = $_.Exception.Message
        output_path = $resolvedOutputPath
    }
}
finally {
    if ($null -ne $rhino -and [System.Runtime.InteropServices.Marshal]::IsComObject($rhino)) {
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($rhino)
    }
}
