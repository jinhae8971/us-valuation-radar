[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$OutputEncoding            = [System.Text.Encoding]::UTF8
chcp 65001 | Out-Null

# ============================================================================
# US Valuation Radar - GitHub 셋업 스크립트
# ============================================================================
$GH_USER     = "jinhae8971"
$GH_REPO     = "us-valuation-radar"

# PAT 토큰은 환경변수에서 읽음 (보안)
# PowerShell에서 실행 전:  $env:GH_PAT = "ghp_xxx..."
$GH_TOKEN = $env:GH_PAT
if (-not $GH_TOKEN) {
    Write-Host "❌ 환경변수 GH_PAT 미설정" -ForegroundColor Red
    Write-Host "   실행 전:  `$env:GH_PAT = `"ghp_xxx...`"" -ForegroundColor White
    exit 1
}

$REMOTE_URL  = "https://$GH_TOKEN@github.com/$GH_USER/$GH_REPO.git"
$TG_TOKEN    = $env:TG_BOT_TOKEN
if (-not $TG_TOKEN) { $TG_TOKEN = "8481005106:AAESmINZyjDHrbno69EVB6kSMSjWyG_dyCU" }
$TG_CHAT_ID  = "954137156"
$PAGES_URL   = "https://$GH_USER.github.io/$GH_REPO/"

$API_HDR = @{
    "Authorization" = "token $GH_TOKEN"
    "Accept"        = "application/vnd.github+json"
    "User-Agent"    = "USValuationRadarDeploy"
}
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ScriptDir

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  US Valuation Radar - Deploy Script" -ForegroundColor Cyan
Write-Host "  Repo: $GH_USER/$GH_REPO" -ForegroundColor White
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# [1] Git 초기화 & 원격 설정
# ---------------------------------------------------------------------------
git config --global --add safe.directory ($ScriptDir -replace '\\','/') 2>$null
if (-not (Test-Path ".git")) {
    git init | Out-Null
    Write-Host "[1] git init OK" -ForegroundColor Green
} else {
    Write-Host "[1] .git already exists" -ForegroundColor Yellow
}

$prev = $ErrorActionPreference
$ErrorActionPreference = "SilentlyContinue"
git remote remove origin 2>$null | Out-Null
$ErrorActionPreference = $prev
git remote add origin $REMOTE_URL
git config user.name  $GH_USER
git config user.email "jinhae8971@gmail.com"
Write-Host "[1] Remote configured: $GH_USER/$GH_REPO" -ForegroundColor Green

# ---------------------------------------------------------------------------
# [2] GitHub 레포 생성 (없을 때만)
# ---------------------------------------------------------------------------
try {
    Invoke-RestMethod -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO" -Headers $API_HDR | Out-Null
    Write-Host "[2] Repo exists on GitHub" -ForegroundColor Green
} catch {
    try {
        $body = @{
            name         = $GH_REPO
            description  = "US AI/Semi/Big Tech valuation radar - daily Z-score scan"
            private      = $false   # GitHub Pages는 public 추천
            auto_init    = $false
            has_issues   = $true
            has_wiki     = $false
        } | ConvertTo-Json
        Invoke-RestMethod -Method Post -Uri "https://api.github.com/user/repos" `
            -Headers $API_HDR -Body $body -ContentType "application/json" | Out-Null
        Write-Host "[2] Repo created" -ForegroundColor Green
        Start-Sleep -Seconds 2
    } catch {
        Write-Host "[2] Create manually: https://github.com/new (name: $GH_REPO)" -ForegroundColor Red
        Read-Host "Press Enter after creating repo"
    }
}

# ---------------------------------------------------------------------------
# [3] Commit & Push
# ---------------------------------------------------------------------------
$ErrorActionPreference = "SilentlyContinue"
git add .
git commit -m "feat: initial US Valuation Radar deploy" 2>$null
if ($LASTEXITCODE -ne 0) {
    git commit --allow-empty -m "chore: redeploy" 2>$null
}
git branch -M main
git push -u origin main --force 2>$null
$pushCode = $LASTEXITCODE
$ErrorActionPreference = "Stop"

if ($pushCode -ne 0) {
    Write-Host ""
    Write-Host "PUSH FAILED. Token needs 'repo' scope:" -ForegroundColor Red
    Write-Host "  https://github.com/settings/tokens/new" -ForegroundColor White
    exit 1
}
Write-Host "[3] Push OK" -ForegroundColor Green

# ---------------------------------------------------------------------------
# [4] GitHub Secrets & Variables 등록
# ---------------------------------------------------------------------------
$secrets = @{
    TELEGRAM_TOKEN   = $TG_TOKEN
    TELEGRAM_CHAT_ID = $TG_CHAT_ID
}
$variables = @{
    PAGES_URL = $PAGES_URL
}

if (Get-Command gh -ErrorAction SilentlyContinue) {
    $env:GH_TOKEN = $GH_TOKEN
    foreach ($s in $secrets.GetEnumerator()) {
        gh secret set $s.Key --body $s.Value --repo "$GH_USER/$GH_REPO" 2>$null
    }
    foreach ($v in $variables.GetEnumerator()) {
        gh variable set $v.Key --body $v.Value --repo "$GH_USER/$GH_REPO" 2>$null
    }
    Write-Host "[4] Secrets & Variables set via gh CLI" -ForegroundColor Green
} else {
    Write-Host "[4] gh CLI 미설치 - 수동 등록 필요" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  → Secrets:   https://github.com/$GH_USER/$GH_REPO/settings/secrets/actions" -ForegroundColor White
    Write-Host "  → Variables: https://github.com/$GH_USER/$GH_REPO/settings/variables/actions" -ForegroundColor White
    Write-Host ""
    Write-Host "  [Secrets]" -ForegroundColor Cyan
    foreach ($s in $secrets.GetEnumerator()) {
        Write-Host "    $($s.Key) = $($s.Value)" -ForegroundColor White
    }
    Write-Host "  [Variables]" -ForegroundColor Cyan
    foreach ($v in $variables.GetEnumerator()) {
        Write-Host "    $($v.Key) = $($v.Value)" -ForegroundColor White
    }
    Write-Host ""
    Read-Host "Press Enter after adding Secrets & Variables"
}

# ---------------------------------------------------------------------------
# [5] GitHub Pages 활성화 (API)
# ---------------------------------------------------------------------------
try {
    $pagesBody = @{
        source = @{ branch = "main"; path = "/docs" }
    } | ConvertTo-Json -Depth 3

    try {
        Invoke-RestMethod -Method Post `
            -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO/pages" `
            -Headers $API_HDR -Body $pagesBody -ContentType "application/json" | Out-Null
        Write-Host "[5] GitHub Pages 활성화 완료" -ForegroundColor Green
    } catch {
        # 이미 활성화돼 있으면 PUT으로 업데이트
        Invoke-RestMethod -Method Put `
            -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO/pages" `
            -Headers $API_HDR -Body $pagesBody -ContentType "application/json" | Out-Null
        Write-Host "[5] GitHub Pages 설정 업데이트" -ForegroundColor Green
    }
} catch {
    Write-Host "[5] Pages 수동 활성화 필요:" -ForegroundColor Yellow
    Write-Host "    https://github.com/$GH_USER/$GH_REPO/settings/pages" -ForegroundColor White
    Write-Host "    → Source: Deploy from a branch / Branch: main / Folder: /docs" -ForegroundColor White
}

# ---------------------------------------------------------------------------
# [6] Workflow 즉시 트리거
# ---------------------------------------------------------------------------
try {
    Invoke-RestMethod -Method Post `
        -Uri "https://api.github.com/repos/$GH_USER/$GH_REPO/actions/workflows/daily-update.yml/dispatches" `
        -Headers $API_HDR -Body '{"ref":"main"}' -ContentType "application/json" | Out-Null
    Write-Host "[6] Workflow triggered! 약 5분 후 첫 데이터 생성됨" -ForegroundColor Green
} catch {
    Write-Host "[6] Manual: https://github.com/$GH_USER/$GH_REPO/actions" -ForegroundColor White
}

Write-Host ""
Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  ✅ Deploy DONE" -ForegroundColor Green
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  📊 Dashboard:  $PAGES_URL" -ForegroundColor White
Write-Host "  ⚙️  Actions:    https://github.com/$GH_USER/$GH_REPO/actions" -ForegroundColor White
Write-Host "  📋 Settings:   https://github.com/$GH_USER/$GH_REPO/settings" -ForegroundColor White
Write-Host ""
Write-Host "  💬 첫 텔레그램 알림이 약 5분 후 도착합니다." -ForegroundColor Yellow
Write-Host ""
