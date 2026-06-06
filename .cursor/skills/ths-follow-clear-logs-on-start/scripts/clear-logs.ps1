# 清空 signal-server / follow-client 的 logs 目录（*.log 及 TimedRotating 后缀文件）
# Fallback: 当 $PSScriptRoot 为空时（某些 cmd -> powershell -File 调用场景），手动推算
if ($PSScriptRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..\..\..")).Path
} else {
    $RepoRoot = (Resolve-Path (Join-Path $MyInvocation.PSCommandPath "..\..\..\..\..")).Path
    if (-not $RepoRoot) {
        # 最后手段：基于脚本自身位置硬编码相对路径
        $RepoRoot = "D:\ewili\fileDoc\code\ths_follow"
        Write-Warning "PSScriptRoot was empty; using hardcoded RepoRoot: $RepoRoot"
    }
}

$removed = @()
$failed = @()
foreach ($svc in @("signal-server", "follow-client")) {
    $logDir = Join-Path (Join-Path $RepoRoot $svc) "logs"
    if (-not (Test-Path $logDir)) {
        continue
    }
    Get-ChildItem -Path $logDir -File -Force -Filter "*.log*" | ForEach-Object {
        try {
            Remove-Item -LiteralPath $_.FullName -Force -ErrorAction Stop
            $removed += $_.FullName
        } catch {
            $failed += $_.FullName
        }
    }
}

if ($removed.Count -eq 0 -and $failed.Count -eq 0) {
    Write-Host "No log files to remove under signal-server/logs or follow-client/logs."
} else {
    if ($removed.Count -gt 0) {
        Write-Host "Removed $($removed.Count) log file(s):"
        $removed | ForEach-Object { Write-Host "  $_" }
    }
    if ($failed.Count -gt 0) {
        Write-Warning "Could not remove $($failed.Count) file(s) (stop uvicorn first):"
        $failed | ForEach-Object { Write-Warning "  $_" }
        exit 1
    }
}
