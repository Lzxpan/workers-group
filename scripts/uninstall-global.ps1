[CmdletBinding()]
param(
    [string]$CodexHome = (Join-Path $env:USERPROFILE '.codex'),
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Assert-ContainedPath {
    param(
        [Parameter(Mandatory)][string]$Path,
        [Parameter(Mandatory)][string[]]$AllowedRoots,
        [Parameter(Mandatory)][string]$Label
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    foreach ($root in $AllowedRoots) {
        $fullRoot = [System.IO.Path]::GetFullPath($root).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
        if ($fullPath.StartsWith($fullRoot + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $fullPath
        }
    }
    throw "$Label 不在允許的 Workers Group 路徑內：$Path"
}

function Get-ReceiptRecord {
    param(
        [Parameter(Mandatory)]$Record,
        [Parameter(Mandatory)][string[]]$AllowedTargets,
        [Parameter(Mandatory)][string]$BackupRoot
    )

    if ($Record -isnot [System.Collections.IDictionary] -or -not $Record.Contains('target') -or -not $Record.Contains('installedSha256')) {
        throw '解除安裝收據格式不完整。'
    }
    $target = Assert-ContainedPath -Path $Record.target -AllowedRoots $AllowedTargets -Label '收據目標'
    $backup = $null
    if ($null -ne $Record.backup) {
        $backup = Assert-ContainedPath -Path $Record.backup -AllowedRoots @($BackupRoot) -Label '收據備份'
    }
    [pscustomobject]@{ Target = $target; Backup = $backup; InstalledSha256 = [string]$Record.installedSha256 }
}

$codexHomeFull = [System.IO.Path]::GetFullPath($CodexHome)
$userHome = Split-Path -Parent $codexHomeFull
$receiptPath = Join-Path $codexHomeFull 'workers-group-install-receipt.json'
if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
    throw "找不到解除安裝收據：$receiptPath。為避免刪除不明檔案，已停止。"
}

try {
    $receipt = Get-Content -LiteralPath $receiptPath -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
} catch {
    throw "解除安裝收據不是可解析的 JSON：$($_.Exception.Message)"
}
if ($receipt.schemaVersion -ne 1 -or $receipt.files -isnot [System.Collections.IEnumerable]) {
    throw '解除安裝收據版本或檔案清單無效。'
}

$allowedTargets = @($codexHomeFull, (Join-Path $userHome '.workers-group'))
$backupRoot = Join-Path $codexHomeFull 'backups/workers-group-install'
$records = @()
foreach ($record in @($receipt.files)) {
    $records += Get-ReceiptRecord -Record $record -AllowedTargets $allowedTargets -BackupRoot $backupRoot
}
$records += Get-ReceiptRecord -Record $receipt.config -AllowedTargets @($codexHomeFull) -BackupRoot $backupRoot
$records += Get-ReceiptRecord -Record $receipt.hooks -AllowedTargets @($codexHomeFull) -BackupRoot $backupRoot

$conflicts = @()
foreach ($record in $records) {
    if (-not (Test-Path -LiteralPath $record.Target -PathType Leaf)) {
        $conflicts += "遺失目標檔案：$($record.Target)"
        continue
    }
    if ((Get-FileHash -LiteralPath $record.Target -Algorithm SHA256).Hash -ne $record.InstalledSha256) {
        $conflicts += "內容衝突：$($record.Target)"
    }
    if ($null -ne $record.Backup -and -not (Test-Path -LiteralPath $record.Backup -PathType Leaf)) {
        $conflicts += "遺失備份檔案：$($record.Backup)"
    }
}
if ($conflicts.Count -gt 0) {
    throw ("解除安裝已停止，未變更任何檔案：`n" + ($conflicts -join "`n"))
}

foreach ($record in $records) {
    if ($null -ne $record.Backup) {
        if ($WhatIf) {
            Write-Host "WhatIf: restore $($record.Backup) -> $($record.Target)"
        } else {
            Copy-Item -LiteralPath $record.Backup -Destination $record.Target -Force
        }
    } elseif ($WhatIf) {
        Write-Host "WhatIf: remove $($record.Target)"
    } else {
        Remove-Item -LiteralPath $record.Target -Force
    }
}

if ($WhatIf) {
    Write-Host "WhatIf: remove receipt $receiptPath"
    Write-Host '預演完成，未寫入任何檔案。'
} else {
    Remove-Item -LiteralPath $receiptPath -Force
    Write-Host '解除安裝完成；未刪除任何未列在收據內的檔案或目錄。'
}
