# Claude Code + Moonshot AI (Kimi) 永久配置脚本
# 此脚本会将配置添加到您的PowerShell配置文件，使其永久生效

Write-Host "正在配置 Claude Code 使用 Kimi 模型（永久生效）..." -ForegroundColor Green

# 获取PowerShell配置文件路径
$profilePath = $PROFILE

if (!(Test-Path $profilePath)) {
    Write-Host "创建新的PowerShell配置文件..." -ForegroundColor Yellow
    New-Item -Path $profilePath -ItemType File -Force
}

# 要添加的配置内容
$configContent = @"

# Claude Code + Moonshot AI (Kimi) 配置
`$env:ANTHROPIC_BASE_URL="https://api.kimi.com/coding/"
`$env:ANTHROPIC_API_KEY="sk-kimi-Eiq0gGy7Rjz3t8sgCpB9TSMMk4bDnF63H9eceTeO9affYN8Sk4cCX2D9fLVakIDM"
`$env:ANTHROPIC_MODEL="kimi-k2-thinking-turbo"
`$env:ANTHROPIC_DEFAULT_OPUS_MODEL="kimi-k2-thinking-turbo"
`$env:ANTHROPIC_DEFAULT_SONNET_MODEL="kimi-k2-thinking-turbo"
`$env:ANTHROPIC_DEFAULT_HAIKU_MODEL="kimi-k2-thinking-turbo"
`$env:CLAUDE_CODE_SUBAGENT_MODEL="kimi-k2-thinking-turbo"

Write-Host "✅ Claude Code 已配置使用 Kimi 模型" -ForegroundColor Green
"@

# 检查配置是否已存在
$existingContent = Get-Content $profilePath -Raw
if ($existingContent -match "ANTHROPIC_BASE_URL.*kimi") {
    Write-Host "⚠️  检测到已存在Kimi配置，将更新为最新设置..." -ForegroundColor Yellow
    # 移除旧的配置
    $newContent = $existingContent -replace "(?s)# Claude Code \+ Moonshot AI \(Kimi\).*?`"@", ""
    Set-Content -Path $profilePath -Value $newContent
}

# 添加新配置
Add-Content -Path $profilePath -Value $configContent

Write-Host "✅ 配置已添加到PowerShell配置文件！" -ForegroundColor Green
Write-Host ""
Write-Host "配置文件位置: $profilePath" -ForegroundColor Gray
Write-Host ""
Write-Host "下次打开PowerShell时，这些环境变量将自动设置。" -ForegroundColor Yellow
Write-Host "现在请重新打开PowerShell或运行: . `$PROFILE" -ForegroundColor Yellow
Write-Host ""
Write-Host "要验证配置是否生效，请运行: Get-ChildItem env: | Where-Object {$_.Name -like '*ANTHROPIC*'}" -ForegroundColor Cyan