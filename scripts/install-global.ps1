[CmdletBinding()]
param(
    [string]$CodexHome = (Join-Path $env:USERPROFILE '.codex'),
    [switch]$WhatIf
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-CanonicalJson {
    param([Parameter(Mandatory)]$Value)

    if ($null -eq $Value) {
        return 'null'
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $ordered = [ordered]@{}
        foreach ($key in @($Value.Keys | Sort-Object)) {
            $ordered[$key] = ConvertTo-CanonicalValue -Value $Value[$key]
        }
        return $ordered | ConvertTo-Json -Depth 100 -Compress
    }
    return (ConvertTo-CanonicalValue -Value $Value) | ConvertTo-Json -Depth 100 -Compress
}

function ConvertTo-CanonicalValue {
    param([Parameter(Mandatory)]$Value)

    if ($null -eq $Value) {
        return $null
    }
    if ($Value -is [System.Collections.IDictionary]) {
        $ordered = [ordered]@{}
        foreach ($key in @($Value.Keys | Sort-Object)) {
            $ordered[$key] = ConvertTo-CanonicalValue -Value $Value[$key]
        }
        return $ordered
    }
    if ($Value -is [System.Collections.IEnumerable] -and $Value -isnot [string]) {
        return @($Value | ForEach-Object { ConvertTo-CanonicalValue -Value $_ })
    }
    return $Value
}

function Get-WgHookId {
    param([Parameter(Mandatory)]$Hook)

    foreach ($property in 'command', 'commandWindows') {
        if ($Hook.ContainsKey($property) -and $Hook[$property] -match '--hook-id\s+(WG-HOOK-\d{3})') {
            return $Matches[1]
        }
    }
    return $null
}

function Get-WgHookIdsFromEntry {
    param([Parameter(Mandatory)]$Entry)

    if (-not $Entry.ContainsKey('hooks') -or $Entry.hooks -isnot [System.Collections.IEnumerable]) {
        throw 'hooks.json entry 缺少 hooks 陣列。'
    }
    return @($Entry.hooks | ForEach-Object { Get-WgHookId -Hook $_ } | Where-Object { $null -ne $_ })
}

function Test-PublicPayloadFile {
    param(
        [Parameter(Mandatory)][string]$RelativePath,
        [Parameter(Mandatory)]$File
    )

    if ($RelativePath -match '(^|[\\/])__pycache__([\\/]|$)' -or $File.Extension -ieq '.pyc') {
        return $false
    }
    if ($RelativePath -match '(^|[\\/])(\.git|runtime|backups)([\\/]|$)') {
        throw "公開 payload 含有不允許目錄：$RelativePath"
    }
    $allowedExtensions = @('.json', '.jsonl', '.md', '.py', '.toml', '.txt', '.yaml', '.yml')
    if ($File.Name -ne 'VERSION' -and $allowedExtensions -notcontains $File.Extension.ToLowerInvariant()) {
        throw "公開 payload 含有不允許副檔名：$RelativePath"
    }
    return $true
}

function Assert-PublicTree {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$PackageRoot
    )

    $sourceFull = [System.IO.Path]::GetFullPath($Source)
    $packageFull = [System.IO.Path]::GetFullPath($PackageRoot)
    if (-not $sourceFull.StartsWith($packageFull + [System.IO.Path]::DirectorySeparatorChar, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "來源不在 package 內：$Source"
    }
    if (-not (Test-Path -LiteralPath $sourceFull -PathType Container)) {
        throw "找不到公開 payload 目錄：$sourceFull"
    }

    foreach ($file in Get-ChildItem -LiteralPath $sourceFull -Recurse -File -Force) {
        $relative = [System.IO.Path]::GetRelativePath($sourceFull, $file.FullName)
        $null = Test-PublicPayloadFile -RelativePath $relative -File $file
    }
}

function Backup-ExistingItem {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$BackupRoot,
        [Parameter(Mandatory)][string]$RelativePath
    )

    if (-not (Test-Path -LiteralPath $Source)) {
        return
    }
    $backupPath = Join-Path $BackupRoot $RelativePath
    if ($WhatIf) {
        Write-Host "WhatIf: backup $Source -> $backupPath"
        return
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $backupPath) | Out-Null
    Copy-Item -LiteralPath $Source -Destination $backupPath -Recurse -Force
}

function Backup-PublicTreeTargets {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$BackupRoot,
        [Parameter(Mandatory)][string]$RelativeRoot
    )

    foreach ($file in Get-ChildItem -LiteralPath $Source -Recurse -File -Force) {
        $relative = [System.IO.Path]::GetRelativePath($Source, $file.FullName)
        if (-not (Test-PublicPayloadFile -RelativePath $relative -File $file)) {
            continue
        }
        Backup-ExistingItem -Source (Join-Path $Destination $relative) -BackupRoot $BackupRoot -RelativePath (Join-Path $RelativeRoot $relative)
    }
}

function Copy-PublicTree {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination
    )

    foreach ($file in Get-ChildItem -LiteralPath $Source -Recurse -File -Force) {
        $relative = [System.IO.Path]::GetRelativePath($Source, $file.FullName)
        if (-not (Test-PublicPayloadFile -RelativePath $relative -File $file)) {
            continue
        }
        $target = Join-Path $Destination $relative
        if ($WhatIf) {
            Write-Host "WhatIf: copy $relative -> $target"
            continue
        }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $target) | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
    }
}

function Copy-PublicFiles {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][scriptblock]$Filter
    )

    foreach ($file in Get-ChildItem -LiteralPath $Source -File -Force | Where-Object $Filter) {
        $target = Join-Path $Destination $file.Name
        if ($WhatIf) {
            Write-Host "WhatIf: copy $($file.Name) -> $target"
            continue
        }
        New-Item -ItemType Directory -Force -Path $Destination | Out-Null
        Copy-Item -LiteralPath $file.FullName -Destination $target -Force
    }
}

function Set-TomlSetting {
    param(
        [Parameter(Mandatory)][AllowEmptyCollection()][AllowEmptyString()][System.Collections.Generic.List[string]]$Lines,
        [Parameter(Mandatory)][string]$Section,
        [Parameter(Mandatory)][string]$Key,
        [Parameter(Mandatory)][string]$Value
    )

    $sectionIndex = -1
    for ($index = 0; $index -lt $Lines.Count; $index++) {
        if ($Lines[$index] -match ('^\s*\[' + [regex]::Escape($Section) + '\]\s*(?:#.*)?$')) {
            $sectionIndex = $index
            break
        }
    }
    if ($sectionIndex -lt 0) {
        if ($Lines.Count -gt 0 -and $Lines[$Lines.Count - 1] -ne '') {
            $Lines.Add('')
        }
        $Lines.Add("[$Section]")
        $Lines.Add("$Key = $Value")
        return
    }

    $sectionEnd = $Lines.Count
    for ($index = $sectionIndex + 1; $index -lt $Lines.Count; $index++) {
        if ($Lines[$index] -match '^\s*\[') {
            $sectionEnd = $index
            break
        }
        if ($Lines[$index] -match ('^\s*' + [regex]::Escape($Key) + '\s*=')) {
            $Lines[$index] = "$Key = $Value"
            return
        }
    }
    $Lines.Insert($sectionEnd, "$Key = $Value")
}

function Update-WorkersGroupConfig {
    param([Parameter(Mandatory)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        $newline = [Environment]::NewLine
        $content = "[features]${newline}hooks = true${newline}multi_agent = true${newline}${newline}[agents]${newline}max_threads = 4${newline}"
    } else {
        $lines = [System.Collections.Generic.List[string]]::new()
        foreach ($line in (Get-Content -LiteralPath $Path -Encoding utf8)) {
            $lines.Add($line)
        }
        Set-TomlSetting -Lines $lines -Section 'features' -Key 'hooks' -Value 'true'
        Set-TomlSetting -Lines $lines -Section 'features' -Key 'multi_agent' -Value 'true'
        Set-TomlSetting -Lines $lines -Section 'agents' -Key 'max_threads' -Value '4'
        $content = [string]::Join([Environment]::NewLine, $lines) + [Environment]::NewLine
    }

    if ($WhatIf) {
        Write-Host "WhatIf: create or merge Workers Group settings -> $Path"
        return
    }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Path) | Out-Null
    Set-Content -LiteralPath $Path -Value $content -Encoding utf8NoBOM -NoNewline
}

function Get-InstallRecord {
    param(
        [Parameter(Mandatory)][string]$Target,
        [Parameter(Mandatory)][string]$Backup
    )

    if (-not (Test-Path -LiteralPath $Target -PathType Leaf)) {
        throw "無法建立安裝收據，找不到目標檔案：$Target"
    }
    [ordered]@{
        target = [System.IO.Path]::GetFullPath($Target)
        backup = if (Test-Path -LiteralPath $Backup -PathType Leaf) { [System.IO.Path]::GetFullPath($Backup) } else { $null }
        installedSha256 = (Get-FileHash -LiteralPath $Target -Algorithm SHA256).Hash
    }
}

function Get-PublicTreeInstallRecords {
    param(
        [Parameter(Mandatory)][string]$Source,
        [Parameter(Mandatory)][string]$Destination,
        [Parameter(Mandatory)][string]$BackupRoot,
        [Parameter(Mandatory)][string]$RelativeRoot
    )

    $records = @()
    foreach ($file in Get-ChildItem -LiteralPath $Source -Recurse -File -Force) {
        $relative = [System.IO.Path]::GetRelativePath($Source, $file.FullName)
        if (-not (Test-PublicPayloadFile -RelativePath $relative -File $file)) {
            continue
        }
        $records += Get-InstallRecord -Target (Join-Path $Destination $relative) -Backup (Join-Path $BackupRoot (Join-Path $RelativeRoot $relative))
    }
    return $records
}

function Read-HooksManifest {
    param([Parameter(Mandatory)][string]$Path)

    try {
        $manifest = Get-Content -LiteralPath $Path -Raw -Encoding utf8 | ConvertFrom-Json -AsHashtable
    } catch {
        throw "hooks manifest 不是可解析的 JSON：$Path。$($_.Exception.Message)"
    }
    if (-not $manifest.ContainsKey('hooks') -or $manifest.hooks -isnot [System.Collections.IDictionary]) {
        throw "hooks manifest 缺少 hooks 物件：$Path"
    }
    return $manifest
}

function Assert-WorkersGroupManifest {
    param([Parameter(Mandatory)]$Manifest)

    $count = 0
    foreach ($eventName in $Manifest.hooks.Keys) {
        foreach ($entry in @($Manifest.hooks[$eventName])) {
            $ids = @(Get-WgHookIdsFromEntry -Entry $entry)
            if ($ids.Count -eq 0) {
                throw "公開 hooks manifest 包含非 Workers Group handler：$eventName"
            }
            if ($ids.Count -ne @($entry.hooks).Count) {
                throw "公開 hooks manifest 混入非 Workers Group handler：$eventName"
            }
            foreach ($hook in @($entry.hooks)) {
                foreach ($property in 'command', 'commandWindows') {
                    if (-not $hook.ContainsKey($property) -or $hook[$property] -notlike '*__CODEX_HOME__*') {
                        throw "公開 hooks manifest 的 $eventName 必須使用 __CODEX_HOME__ placeholder。"
                    }
                }
            }
            $count += $ids.Count
        }
    }
    if ($count -eq 0) {
        throw '公開 hooks manifest 未包含任何 WG-HOOK handler。'
    }
}

function Resolve-WorkersGroupHookPaths {
    param(
        [Parameter(Mandatory)]$Manifest,
        [Parameter(Mandatory)][string]$CodexHome
    )

    $posixHome = $CodexHome.Replace('\', '/')
    foreach ($eventName in $Manifest.hooks.Keys) {
        foreach ($entry in @($Manifest.hooks[$eventName])) {
            foreach ($hook in @($entry.hooks)) {
                $hook.command = $hook.command.Replace('__CODEX_HOME__', $posixHome)
                $hook.commandWindows = $hook.commandWindows.Replace('__CODEX_HOME__', $CodexHome)
            }
        }
    }
    return $Manifest
}

function Merge-WorkersGroupHooks {
    param(
        [Parameter(Mandatory)]$Incoming,
        [Parameter(Mandatory)][string]$Destination
    )

    $installed = if (Test-Path -LiteralPath $Destination -PathType Leaf) {
        Read-HooksManifest -Path $Destination
    } else {
        @{ hooks = @{} }
    }

    foreach ($eventName in $Incoming.hooks.Keys) {
        if (-not $installed.hooks.ContainsKey($eventName)) {
            $installed.hooks[$eventName] = @()
        }
        $existingEntries = @($installed.hooks[$eventName])
        foreach ($incomingEntry in @($Incoming.hooks[$eventName])) {
            foreach ($hookId in @(Get-WgHookIdsFromEntry -Entry $incomingEntry)) {
                $matches = @(
                    foreach ($existingEntry in $existingEntries) {
                        if ((Get-WgHookIdsFromEntry -Entry $existingEntry) -contains $hookId) {
                            $existingEntry
                        }
                    }
                )
                if ($matches.Count -gt 1) {
                    throw "全域 hooks.json 有重複的 $hookId，請先人工處理。"
                }
                if ($matches.Count -eq 1) {
                    if ((Get-CanonicalJson -Value $matches[0]) -ne (Get-CanonicalJson -Value $incomingEntry)) {
                        throw "全域 hooks.json 的 $hookId 與公開 payload 不同；已停止，未覆寫。"
                    }
                    continue
                }
                $existingEntries += ,$incomingEntry
            }
        }
        $installed.hooks[$eventName] = $existingEntries
    }
    return $installed
}

$packageRoot = Split-Path -Parent $PSScriptRoot
$payload = [ordered]@{
    Skill = Join-Path $packageRoot 'package/global-skill'
    Static = Join-Path $packageRoot 'package/workers-group-static'
    Agents = Join-Path $packageRoot 'package/global-agents'
    Hook = Join-Path $packageRoot 'package/hooks/workers_group_hook.py'
    HooksManifest = Join-Path $packageRoot 'package/hooks/workers-group-hooks.json'
}
$codexHomeFull = [System.IO.Path]::GetFullPath($CodexHome)
$userHome = Split-Path -Parent $codexHomeFull
$destinations = [ordered]@{
    Skill = Join-Path $codexHomeFull 'skills/orchestrating-workers-group'
    Static = Join-Path $userHome '.workers-group'
    Agents = Join-Path $codexHomeFull 'agents'
    Hook = Join-Path $codexHomeFull 'hooks/workers_group_hook.py'
    HooksManifest = Join-Path $codexHomeFull 'hooks.json'
    Config = Join-Path $codexHomeFull 'config.toml'
    Receipt = Join-Path $codexHomeFull 'workers-group-install-receipt.json'
}

Assert-PublicTree -Source $payload.Skill -PackageRoot $packageRoot
Assert-PublicTree -Source $payload.Static -PackageRoot $packageRoot
Assert-PublicTree -Source $payload.Agents -PackageRoot $packageRoot
if (-not (Test-Path -LiteralPath $payload.Hook -PathType Leaf)) {
    throw "找不到公開 hook 入口檔：$($payload.Hook)"
}
if (-not (Test-Path -LiteralPath $payload.HooksManifest -PathType Leaf)) {
    throw "找不到公開 hooks manifest：$($payload.HooksManifest)"
}
if (@(Get-ChildItem -LiteralPath $payload.Agents -File -Force | Where-Object { $_.Name -notmatch '^workers_(boss|executor|planner|pm|qa)\.toml$' }).Count -gt 0) {
    throw 'package/global-agents 只能包含 workers_*.toml 角色設定檔。'
}
$expectedAgentNames = @('workers_boss.toml', 'workers_executor.toml', 'workers_planner.toml', 'workers_pm.toml', 'workers_qa.toml')
$actualAgentNames = @(Get-ChildItem -LiteralPath $payload.Agents -File -Force | ForEach-Object Name | Sort-Object)
if ((Compare-Object -ReferenceObject ($expectedAgentNames | Sort-Object) -DifferenceObject $actualAgentNames)) {
    throw 'package/global-agents 必須且只能包含五個 Workers Group 角色設定檔。'
}
$incomingHooks = Read-HooksManifest -Path $payload.HooksManifest
Assert-WorkersGroupManifest -Manifest $incomingHooks
$incomingHooks = Resolve-WorkersGroupHookPaths -Manifest $incomingHooks -CodexHome $codexHomeFull
$mergedHooks = Merge-WorkersGroupHooks -Incoming $incomingHooks -Destination $destinations.HooksManifest

$backupRoot = Join-Path $codexHomeFull (Join-Path 'backups/workers-group-install' (Get-Date -Format 'yyyyMMddTHHmmss'))
if (-not $WhatIf) {
    New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
}
Backup-PublicTreeTargets -Source $payload.Skill -Destination $destinations.Skill -BackupRoot $backupRoot -RelativeRoot 'skills/orchestrating-workers-group'
Backup-PublicTreeTargets -Source $payload.Static -Destination $destinations.Static -BackupRoot $backupRoot -RelativeRoot 'workers-group-static'
Backup-ExistingItem -Source $destinations.Hook -BackupRoot $backupRoot -RelativePath 'hooks/workers_group_hook.py'
Backup-ExistingItem -Source $destinations.HooksManifest -BackupRoot $backupRoot -RelativePath 'hooks.json'
Backup-ExistingItem -Source $destinations.Config -BackupRoot $backupRoot -RelativePath 'config.toml'
foreach ($agentName in 'workers_boss.toml', 'workers_executor.toml', 'workers_planner.toml', 'workers_pm.toml', 'workers_qa.toml') {
    Backup-ExistingItem -Source (Join-Path $destinations.Agents $agentName) -BackupRoot $backupRoot -RelativePath (Join-Path 'agents' $agentName)
}

Copy-PublicTree -Source $payload.Skill -Destination $destinations.Skill
Copy-PublicTree -Source $payload.Static -Destination $destinations.Static
Copy-PublicFiles -Source $payload.Agents -Destination $destinations.Agents -Filter { $_.Name -match '^workers_(boss|executor|planner|pm|qa)\.toml$' }
Update-WorkersGroupConfig -Path $destinations.Config
if ($WhatIf) {
    Write-Host "WhatIf: copy workers_group_hook.py -> $($destinations.Hook)"
    Write-Host "WhatIf: merge Workers Group handlers -> $($destinations.HooksManifest)"
} else {
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $destinations.Hook) | Out-Null
    Copy-Item -LiteralPath $payload.Hook -Destination $destinations.Hook -Force
    $mergedHooks | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $destinations.HooksManifest -Encoding utf8NoBOM

    if (-not (Test-Path -LiteralPath $destinations.Receipt -PathType Leaf)) {
        $records = @()
        $records += Get-PublicTreeInstallRecords -Source $payload.Skill -Destination $destinations.Skill -BackupRoot $backupRoot -RelativeRoot 'skills/orchestrating-workers-group'
        $records += Get-PublicTreeInstallRecords -Source $payload.Static -Destination $destinations.Static -BackupRoot $backupRoot -RelativeRoot 'workers-group-static'
        foreach ($agentName in 'workers_boss.toml', 'workers_executor.toml', 'workers_planner.toml', 'workers_pm.toml', 'workers_qa.toml') {
            $records += Get-InstallRecord -Target (Join-Path $destinations.Agents $agentName) -Backup (Join-Path $backupRoot (Join-Path 'agents' $agentName))
        }
        $records += Get-InstallRecord -Target $destinations.Hook -Backup (Join-Path $backupRoot 'hooks/workers_group_hook.py')
        $receipt = [ordered]@{
            schemaVersion = 1
            installedAt = (Get-Date).ToString('o')
            files = $records
            config = Get-InstallRecord -Target $destinations.Config -Backup (Join-Path $backupRoot 'config.toml')
            hooks = Get-InstallRecord -Target $destinations.HooksManifest -Backup (Join-Path $backupRoot 'hooks.json')
        }
        $receipt | ConvertTo-Json -Depth 20 | Set-Content -LiteralPath $destinations.Receipt -Encoding utf8NoBOM
    } else {
        Write-Host "保留既有解除安裝收據：$($destinations.Receipt)"
    }
}

if ($WhatIf) {
    Write-Host '預演完成，未寫入任何檔案。'
} else {
    Write-Host "安裝完成。備份位置：$backupRoot"
}
Write-Host 'config.toml 僅建立最小設定，或合併 Workers Group 的三個必要設定；不會以完整範本覆寫。'
