# Claude Code + Moonshot AI (Kimi) 配置脚本
# 运行此脚本可以快速配置 Claude Code 使用 Kimi 模型

Write-Host "正在配置 Claude Code 使用 Kimi 模型..." -ForegroundColor Green

# 设置环境变量
$env:ANTHROPIC_BASE_URL="https://api.kimi.com/coding/"
$env:ANTHROPIC_API_KEY="sk-kimi-Eiq0gGy7Rjz3t8sgCpB9TSMMk4bDnF63H9eceTeO9affYN8Sk4cCX2D9fLVakIDM"
$env:ANTHROPIC_MODEL="kimi-k2-thinking-turbo"
$env:ANTHROPIC_DEFAULT_OPUS_MODEL="kimi-k2-thinking-turbo"
$env:ANTHROPIC_DEFAULT_SONNET_MODEL="kimi-k2-thinking-turbo"
$env:ANTHROPIC_DEFAULT_HAIKU_MODEL="kimi-k2-thinking-turbo"
$env:CLAUDE_CODE_SUBAGENT_MODEL="kimi-k2-thinking-turbo"

Write-Host "✅ 环境变量设置完成！" -ForegroundColor Green
Write-Host ""
Write-Host "当前配置：" -ForegroundColor Yellow
Write-Host "  • API端点: $($env:ANTHROPIC_BASE_URL)" -ForegroundColor White
Write-Host "  • 使用模型: $($env:ANTHROPIC_MODEL)" -ForegroundColor White
Write-Host "  • API密钥: $($($env:ANTHROPIC_API_KEY).Substring(0,20))..." -ForegroundColor White
Write-Host ""
Write-Host "注意：使用 ANTHROPIC_API_KEY 而不是 ANTHROPIC_AUTH_TOKEN" -ForegroundColor Yellow
Write-Host ""
Write-Host "现在您可以运行 claude 命令开始使用 Kimi 模型了！" -ForegroundColor Green
Write-Host ""
Write-Host "提示：此配置仅在当前PowerShell会话中有效。" -ForegroundColor Gray
Write-Host "如需永久生效，请运行: setup_claude_kimi_permanent.ps1" -ForegroundColor Gray