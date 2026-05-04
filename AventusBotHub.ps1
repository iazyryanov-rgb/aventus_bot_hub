#Requires -Version 5

# Aventus Bot Hub — UTF-8 BOM — Windows GUI: компании (список + выбор) + операции + справочники (catalog.json).
# Запуск: AventusBotHub.cmd или: powershell -Sta -File .\AventusBotHub.ps1

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName Microsoft.VisualBasic

try {
    Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class HubUxTheme {
    [DllImport("uxtheme.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    public static extern int SetWindowTheme(IntPtr hwnd, string pszSubAppName, string pszSubIdList);
}
'@ -ErrorAction SilentlyContinue
} catch { }

$ErrorActionPreference = 'Stop'
$script:HubAppTitle = 'Aventus Bot Hub'
$script:HubDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:HubAppScriptPath = [string]$MyInvocation.MyCommand.Path
try {
    $script:HubSessionScriptUtc = ([System.IO.FileInfo]$script:HubAppScriptPath).LastWriteTimeUtc
} catch {
    $script:HubSessionScriptUtc = [DateTime]::MinValue
}
$script:HubProcessStartUtc = [DateTime]::UtcNow

$pathsFile = Join-Path $script:HubDir 'hub-paths.json'
if (-not (Test-Path -LiteralPath $pathsFile)) {
    [void][System.Windows.Forms.MessageBox]::Show("Не найден hub-paths.json:`n$pathsFile", $script:HubAppTitle)
    exit 1
}

$paths = [System.IO.File]::ReadAllText($pathsFile, [System.Text.UTF8Encoding]::new($false)) | ConvertFrom-Json
$script:RepoRoot = [string]$paths.wa_bot_root
if ([string]::IsNullOrWhiteSpace($script:RepoRoot)) { throw 'hub-paths.json: пустое wa_bot_root' }
if (-not (Test-Path -LiteralPath $script:RepoRoot)) {
    throw "wa_bot_root не найден на диске: $script:RepoRoot"
}

$script:SchemasDir = Join-Path $script:RepoRoot 'schemas'
$script:ConfigPath = Join-Path $script:SchemasDir 'deploy-config.json'
$script:CatalogTools = Join-Path $script:RepoRoot 'config\company-catalogs\tools'
$script:HubDataDir = Join-Path $script:HubDir 'data'
$script:HubCompaniesPath = Join-Path $script:HubDataDir 'companies.json'
$script:HubCatalogsRoot = Join-Path $script:HubDataDir 'catalogs'
$script:HubChatsArchiveRoot = Join-Path $script:HubDataDir 'chats-archive'
$script:HubTestersRoot = Join-Path $script:HubDataDir 'testers'
$script:RepoCompanyCatalogsRoot = Join-Path $script:RepoRoot 'config\company-catalogs'
$script:RegistryPath = Join-Path $script:HubCatalogsRoot 'registry.json'
$script:TrustedPath = Join-Path $script:HubCatalogsRoot 'trusted-sources.json'
$script:CompanyTreeSuppressCheck = $false
$script:CatalogGroupAboutCompany = 'О компании'
$script:CatalogGroupCrmClient = 'CRM - получение данных о клиенте'
$script:CatalogGroupCrmResults = 'CRM - Регистрация результатов'
$script:CatalogGroupGptMain = 'ChatGPT - main prompt'
$script:CatalogGroupGptExtra = 'ChatGPT - доп инструкции'
$script:CatalogGroupGptResults = 'ChatGPT - результаты'
$script:CatalogGroupGptFunctions = 'ChatGPT - функции'
$script:CatalogGroupBotFinal = 'Bot - финальные фразы'
$script:CatalogGroupGlobalVars = 'Глобальные переменные'
$script:CatalogGroupUngrouped = 'Без группы'
# Канонический id датасета в админке Webitel: system/globalVariables.
# В URL слэш кодируется как %2F; Invoke-WebRequest в .NET часто «раскрывает» %2F в путь → 404 (dataset dictionaries/system).
$script:WebitelGlobalVariablesDatasetId = 'system/globalVariables'
$script:CatalogEditRows = $null
$script:CatalogGridSuppressEvents = $false
$script:CatalogActiveGroupName = $null
$script:CatalogEditorMetaKey = '_hub_editor_meta'
$script:TlpCatalogPageRoot = $null
$script:PnlCatalogTop = $null
$script:PnlCatalogBodyShell = $null
$script:TlpCatalogInner = $null
$script:PnlCatalogGroups = $null
$script:PnlCatalogGridHost = $null
$script:PnlCatalogGutter = $null
$script:PnlCatalogGlobalActions = $null
$script:BtnCatLoadGlobals = $null
$script:CatalogContextCompanyKey = $null
$script:CatalogGlobalSchemaRefKeys = $null
$script:CatalogGlobalMissingKeysOrdered = $null
$script:CatalogUiMissingGlobalPathPrefix = '_hub_ui_missing_global'
$script:TpTesters = $null
$script:TpQueues = $null
$script:DgvQueues = $null
$script:CmsQueueSchemas = $null
$script:HubQueueSchemaMenuItemClickHandler = $null
$script:CmbQueuesTypeFilter = $null
$script:CmbQueuesTeamFilter = $null
$script:QueueControlTeamFilterEmptyLabel = '(без команды)'
$script:BtnQueuesRefresh = $null
$script:LblQueuesHint = $null
$script:PnlQueuesTop = $null
$script:QueueControlAllRows = @()
$script:QueuesSplit = $null
$script:LblQueuesDetailHead = $null
$script:DgvQueueMetrics = $null
$script:CmbQueuesAutoRefresh = $null
$script:TimerQueuesAuto = $null
$script:TimerCompanyTreeClock = $null
$script:TimerHubSelfUpdate = $null
$script:HubSelfUpdateRestarting = $false
$script:HubCompanyCalState = @{}
$script:HubCompanyCalLastRefreshUtc = $null
$script:QueuesRefreshWorker = $null
$script:QueueControlInGridRestore = $false
$script:HubLayoutQueuesTab = $null
$script:TestersSplit = $null
$script:LblTestersCompany = $null
$script:LblTestersPath = $null
$script:CmbTestersDefault = $null
$script:BtnTestersSave = $null
$script:BtnTestersAdd = $null
$script:BtnTestersRemove = $null
$script:LstTesters = $null
$script:DgvTestersDetail = $null
$script:TestersUiSuppress = $false
$script:TestersLoadedList = $null
$script:TestersCurrentKey = $null
$script:TestersJsonParseFailed = $false
$script:HubLayoutTestersTab = $null
# Палитра: светлый фон «SaaS», синий акцент, мягкие границы (как современные дашборды)
$script:HubUiPageBg = [System.Drawing.Color]::FromArgb(240, 244, 248)
$script:HubUiCard = [System.Drawing.Color]::FromArgb(255, 255, 255)
$script:HubUiNavy = [System.Drawing.Color]::FromArgb(37, 99, 235)
$script:HubUiNavyHi = [System.Drawing.Color]::FromArgb(59, 130, 246)
$script:HubUiNavyPress = [System.Drawing.Color]::FromArgb(29, 78, 216)
$script:HubUiInk = [System.Drawing.Color]::FromArgb(30, 41, 59)
$script:HubUiMuted = [System.Drawing.Color]::FromArgb(100, 116, 139)
$script:HubUiBorder = [System.Drawing.Color]::FromArgb(226, 232, 240)
$script:HubUiTrack = [System.Drawing.Color]::FromArgb(241, 245, 249)
$script:HubUiSuccess = [System.Drawing.Color]::FromArgb(22, 163, 74)
$script:HubUiSuccessHi = [System.Drawing.Color]::FromArgb(34, 197, 94)
$script:HubUiFontTab = $null
$script:HubUiFontTabSel = $null

function Get-HubBotChannelDefinitions {
    <# Типы ботов в дереве компаний (пока один канал на компанию). Расширяйте список при появлении новых ботов. #>
    return @(
        @{ Id = 'whatsapp_infobip'; Label = 'WhatsApp Infobip bot' }
    )
}

function Hub-GetBotChannelLabelForId {
    param([string]$BotId)
    if ([string]::IsNullOrWhiteSpace($BotId)) { return '' }
    foreach ($b in @(Get-HubBotChannelDefinitions)) {
        if ([string]$b.Id -eq $BotId) { return [string]$b.Label }
    }
    return $BotId
}

function Hub-GetCatalogRequiredBotId {
    <# Какой тип бота в дереве должен быть отмечен, чтобы открыть catalog.json компании (см. data\catalogs\registry.json → catalog_bot_id). #>
    param([string]$CompanyKey)
    if ([string]::IsNullOrWhiteSpace($CompanyKey)) { return 'whatsapp_infobip' }
    try {
        $reg = Hub-GetRegistryRoot
        if (-not $reg) { return 'whatsapp_infobip' }
        $node = $reg.$CompanyKey
        if ($null -ne $node -and $null -ne $node.catalog_bot_id) {
            $s = [string]$node.catalog_bot_id
            if (-not [string]::IsNullOrWhiteSpace($s)) { return $s.Trim() }
        }
    } catch { }
    return 'whatsapp_infobip'
}

function Hub-GetCatalogSelectionMismatchHint {
    <# Подсказка, если отмечен тип бота, не совпадающий с привязкой справочника в registry. #>
    if ($null -eq $script:TvCompanies) { return $null }
    foreach ($root in $script:TvCompanies.Nodes) {
        foreach ($ch in $root.Nodes) {
            if (-not $ch.Checked) { continue }
            $tg = [string]$ch.Tag
            if ($tg -notmatch '^BOT\|([A-Z0-9_]+)\|(.+)$') { continue }
            $k = [string]$Matches[1]
            $bid = [string]$Matches[2]
            $req = Hub-GetCatalogRequiredBotId $k
            if ($bid -ne $req) {
                $lab = Hub-GetBotChannelLabelForId $req
                return ("Справочник для ключа «$k» привязан к типу бота «$lab» (поле catalog_bot_id в data\catalogs\registry.json).`n" +
                    'Отметьте этот тип у компании или снимите отметку с другого типа.')
            }
        }
    }
    return $null
}

function Hub-FormatCompanyRootLabel([string]$Key) {
    $c = $script:Companies.$Key
    if (-not $c) { return $Key }
    $nm = [string]$c.name
    $ct = [string]$c.country
    $kDisp = $Key -replace '_', ' '
    if ([string]::IsNullOrWhiteSpace($ct)) {
        if ([string]::IsNullOrWhiteSpace($nm)) { return $kDisp }
        return ($kDisp + ' — ' + $nm)
    }
    return ($kDisp + ' — ' + $nm + ' (' + $ct + ')')
}

function Hub-ResolveWindowsTimeZoneIdFromCountry([string]$Country) {
    <# Сопоставление поля country (как в конфиге) с идентификатором часового пояса Windows для DateTime. #>
    if ([string]::IsNullOrWhiteSpace($Country)) { return $null }
    $n = $Country.Trim().ToLowerInvariant()
    if ($n -match 'argentina|аргентин') { return 'Argentina Standard Time' }
    if ($n -match 'colombia|колумб') { return 'SA Pacific Standard Time' }
    if ($n -match 'peru|перу|perú') { return 'SA Pacific Standard Time' }
    if ($n -match 'ecuador|эквадор') { return 'SA Pacific Standard Time' }
    if ($n -match 'bolivia|болив') { return 'SA Western Standard Time' }
    if ($n -match 'venezuela|венесуэл') { return 'Venezuela Standard Time' }
    if ($n -match 'chile|чили') { return 'Pacific SA Standard Time' }
    if ($n -match 'paraguay|парагв') { return 'Paraguay Standard Time' }
    if ($n -match 'uruguay|уругв') { return 'Montevideo Standard Time' }
    if ($n -match 'brazil|brasil|бразил') { return 'E. South America Standard Time' }
    if ($n -match 'mexico|méxico|мексик') { return 'Central Standard Time (Mexico)' }
    if ($n -match 'guatemala|гватемал') { return 'Central America Standard Time' }
    if ($n -match 'panama|панам') { return 'SA Pacific Standard Time' }
    if ($n -match 'costa rica|коста-рик') { return 'Central America Standard Time' }
    if ($n -match 'dominic|доминикан') { return 'SA Western Standard Time' }
    if ($n -match 'spain|испани|españa') { return 'Central European Standard Time' }
    if ($n -match 'ukraine|украин') { return 'FLE Standard Time' }
    if ($n -match 'poland|польш') { return 'Central European Standard Time' }
    if ($n -match 'india|инди') { return 'India Standard Time' }
    if ($n -match 'philippines|филиппин') { return 'Singapore Standard Time' }
    if ($n -match 'united states|usa|u\.s\.|сша') { return 'Eastern Standard Time' }
    if ($n -match 'canada|канада') { return 'Eastern Standard Time' }
    if ($n -match 'united kingdom|uk|britain|англи|великобрит') { return 'GMT Standard Time' }
    if ($n -match 'germany|герман') { return 'W. Europe Standard Time' }
    if ($n -match 'france|франц') { return 'Romance Standard Time' }
    return $null
}

function Hub-FormatCompanyTreeRootWithClock([string]$Key) {
    $base = Hub-FormatCompanyRootLabel $Key
    $c = $script:Companies.$Key
    if (-not $c) { return $base }
    $ct = ([string]$c.country).Trim()
    if ([string]::IsNullOrWhiteSpace($ct)) { return $base }
    $winId = Hub-ResolveWindowsTimeZoneIdFromCountry $ct
    if ([string]::IsNullOrWhiteSpace($winId)) { return $base }
    try {
        $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById($winId)
        $now = [System.TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow, $tz)
        $clk = $now.ToString('HH:mm:ss', [System.Globalization.CultureInfo]::InvariantCulture)
        return ($base + '  ' + $clk)
    } catch {
        return $base
    }
}

function Hub-QueueControlFetchSampleQueueCalendarId {
    <# Первая очередь с непустым calendar (лёгкий запрос) — для индикатора рабочего времени в дереве. #>
    param([Parameter(Mandatory)][string]$Key)
    $c = $script:Companies.$Key
    if (-not $c) { return '' }
    $hostB = [string]$c.webitel_host
    $tok = [string]$c.access_token
    if ([string]::IsNullOrWhiteSpace($hostB) -or $hostB -match '^PASTE_') { return '' }
    if ([string]::IsNullOrWhiteSpace($tok) -or $tok -match '^PASTE_') { return '' }
    $base = @{ page = 1; size = 40; sort = @('name'); fields = @('id', 'name', 'calendar') }
    try {
        $resp = Hub-WebitelRestGet -WebitelHost $hostB -AccessToken $tok -RelativeApiPath '/call_center/queues' -Query $base
        $items = @()
        if ($resp.PSObject.Properties['items'] -and $null -ne $resp.items) { $items = @($resp.items) }
        foreach ($it in $items) {
            if ($null -eq $it) { continue }
            $cid = Hub-QueueControlExtractCalendarId $it
            if (-not [string]::IsNullOrWhiteSpace($cid)) { return $cid.Trim() }
        }
    } catch { }
    return ''
}

function Hub-CompanyCalendarNormalizeAccepts($Cal) {
    if ($null -eq $Cal -or -not ($Cal.PSObject.Properties['accepts'])) { return @() }
    $a = $Cal.accepts
    if ($a -is [string]) {
        try { return @($a | ConvertFrom-Json) } catch { return @() }
    }
    return @($a)
}

function Hub-CompanyCalendarDotNetDowMatchesAcceptDay {
    param([int]$DotNetDow, $AcceptDay)
    try {
        $d = [int][int64]$AcceptDay
    } catch { return $false }
    if ($d -ge 0 -and $d -le 6) { return ($d -eq $DotNetDow) }
    $iso = if ($DotNetDow -eq 0) { 7 } else { $DotNetDow }
    return ($d -eq $iso)
}

function Hub-CompanyCalendarTodayIsExceptOff {
    param($Cal, [datetime]$LocalNow)
    if ($null -eq $Cal -or -not ($Cal.PSObject.Properties['excepts'])) { return $false }
    $ex = $Cal.excepts
    if ($ex -is [string]) {
        try { $ex = $ex | ConvertFrom-Json } catch { return $false }
    }
    foreach ($row in @($ex)) {
        if ($null -eq $row) { continue }
        $dis = $false
        try { $dis = [bool]$row.disabled } catch { }
        if ($dis) { continue }
        $working = $true
        try { if ($null -ne $row.working) { $working = [bool]$row.working } } catch { }
        if ($working) { continue }
        $dts = 0L
        try { if ($null -ne $row.date) { $dts = [int64]$row.date } } catch { }
        if ($dts -le 0) { continue }
        try {
            $dt = if ($dts -gt 1000000000000) {
                [DateTimeOffset]::FromUnixTimeMilliseconds($dts).DateTime
            } else {
                [DateTimeOffset]::FromUnixTimeSeconds($dts).DateTime
            }
            if ($dt.Date -eq $LocalNow.Date) { return $true }
        } catch { }
    }
    return $false
}

function Hub-CompanyCalendarCollectTodayIntervalsMinutes {
    param($Cal, [datetime]$LocalNow)
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($a in @(Hub-CompanyCalendarNormalizeAccepts $Cal)) {
        if ($null -eq $a) { continue }
        $dis = $false
        try { $dis = [bool]$a.disabled } catch { }
        if ($dis) { continue }
        if (-not (Hub-CompanyCalendarDotNetDowMatchesAcceptDay -DotNetDow ([int]$LocalNow.DayOfWeek) -AcceptDay $a.day)) { continue }
        $st = 0
        $en = 0
        try { $st = [int][int64]$a.start_time_of_day } catch { }
        try { $en = [int][int64]$a.end_time_of_day } catch { }
        if ($en -le $st) { continue }
        [void]$list.Add([pscustomobject]@{ Start = $st; End = $en })
    }
    return @($list.ToArray())
}

function Hub-CompanyCalendarComputeWorkStateFromDetail {
    <# before — до начала первого окна; open — внутри окна accepts; after/mid/off — иначе (перерыв, конец дня, выходной). #>
    param($Cal, [datetime]$LocalNow)
    if ($null -eq $Cal) { return $null }
    if (Hub-CompanyCalendarTodayIsExceptOff -Cal $Cal -LocalNow $LocalNow) { return 'off' }
    $intervals = @(Hub-CompanyCalendarCollectTodayIntervalsMinutes -Cal $Cal -LocalNow $LocalNow)
    if ($intervals.Count -eq 0) { return 'off' }
    $m = [int]$LocalNow.Hour * 60 + [int]$LocalNow.Minute
    foreach ($iv in $intervals) {
        if ($m -ge $iv.Start -and $m -lt $iv.End) { return 'open' }
    }
    $minStart = ($intervals | ForEach-Object { [int]$_.Start } | Measure-Object -Minimum).Minimum
    if ($m -lt $minStart) { return 'before' }
    return 'mid'
}

function Hub-CompanyCalendarFetchDetailById {
    param(
        [Parameter(Mandatory)][string]$Key,
        [Parameter(Mandatory)][string]$CalendarId
    )
    $cid = ([string]$CalendarId).Trim()
    if ([string]::IsNullOrWhiteSpace($cid)) { return $null }
    $c = $script:Companies.$Key
    if (-not $c) { return $null }
    $hostB = [string]$c.webitel_host
    $tok = [string]$c.access_token
    if ([string]::IsNullOrWhiteSpace($hostB) -or $hostB -match '^PASTE_') { return $null }
    if ([string]::IsNullOrWhiteSpace($tok) -or $tok -match '^PASTE_') { return $null }
    $relPaths = @(
        ('/lookups/calendars/' + $cid),
        ('/call_center/calendars/' + $cid)
    )
    $fieldSets = @(
        @('id', 'name', 'accepts', 'excepts', 'specials', 'timezone'),
        @('id', 'name', 'accepts', 'timezone'),
        @('id', 'name', 'accepts')
    )
    foreach ($rel in $relPaths) {
        foreach ($fd in $fieldSets) {
            try {
                $r = Hub-WebitelRestGet -WebitelHost $hostB -AccessToken $tok -RelativeApiPath $rel -Query @{ fields = $fd }
                if ($null -eq $r) { continue }
                if ($r.PSObject.Properties['items'] -and $null -ne $r.items) {
                    $arr = @($r.items)
                    if ($arr.Count -gt 0) { $r = $arr[0] } else { continue }
                }
                elseif ($r.PSObject.Properties['data'] -and $null -ne $r.data) {
                    $d = $r.data
                    if ($d -is [System.Collections.IList] -and @($d).Count -gt 0) { $r = @($d)[0] }
                    elseif ($d -is [pscustomobject]) { $r = $d }
                }
                return $r
            } catch { }
        }
    }
    return $null
}

function Hub-CompanyTreeUpdateCalStateForCompanyKey {
    param([Parameter(Mandatory)][string]$Key)
    try {
        $calId = Hub-QueueControlFetchSampleQueueCalendarId $Key
        if ([string]::IsNullOrWhiteSpace($calId)) {
            $script:HubCompanyCalState[$Key] = $null
            return
        }
        $detail = Hub-CompanyCalendarFetchDetailById -Key $Key -CalendarId $calId
        if ($null -eq $detail) {
            $script:HubCompanyCalState[$Key] = $null
            return
        }
        $co = $script:Companies.$Key
        $ctry = ''
        try { $ctry = [string]$co.country } catch { }
        $localNow = [datetime]::Now
        $winId = Hub-ResolveWindowsTimeZoneIdFromCountry $ctry
        if (-not [string]::IsNullOrWhiteSpace($winId)) {
            try {
                $tz = [System.TimeZoneInfo]::FindSystemTimeZoneById($winId)
                $localNow = [System.TimeZoneInfo]::ConvertTimeFromUtc([datetime]::UtcNow, $tz)
            } catch { }
        }
        $script:HubCompanyCalState[$Key] = Hub-CompanyCalendarComputeWorkStateFromDetail -Cal $detail -LocalNow $localNow
    } catch {
        $script:HubCompanyCalState[$Key] = $null
    }
}

function Hub-CompanyTreeCalendarRefreshCache {
    if ($null -eq $script:TvCompanies) { return }
    foreach ($root in $script:TvCompanies.Nodes) {
        $tg = ''
        try { $tg = [string]$root.Tag } catch { }
        if ($tg -notmatch '^COMPANY\|(.+)$') { continue }
        $qk = $Matches[1].Trim()
        if ([string]::IsNullOrWhiteSpace($qk)) { continue }
        try { Hub-CompanyTreeUpdateCalStateForCompanyKey $qk } catch { }
    }
}

function Hub-CompanyTreeGetCalEmojiPrefix {
    param([string]$Key)
    if ($null -eq $script:HubCompanyCalState) { return '' }
    if (-not ($script:HubCompanyCalState.ContainsKey($Key))) { return '' }
    $st = $script:HubCompanyCalState[$Key]
    if ($null -eq $st) { return '' }
    switch ([string]$st) {
        'open' { return '🟢 ' }
        'before' { return '🟡 ' }
        default { return '⚪ ' }
    }
}

function Hub-FormatCompanyTreeRootWithClockAndCal {
    param([string]$Key)
    return ((Hub-CompanyTreeGetCalEmojiPrefix $Key) + (Hub-FormatCompanyTreeRootWithClock $Key))
}

function Hub-CompanyTreeClockApplyToAllRoots {
    $tv = $script:TvCompanies
    if ($null -eq $tv) { return }
    $nowU = [datetime]::UtcNow
    if ($null -eq $script:HubCompanyCalLastRefreshUtc -or ($nowU - $script:HubCompanyCalLastRefreshUtc).TotalSeconds -ge 55) {
        $script:HubCompanyCalLastRefreshUtc = $nowU
        try { Hub-CompanyTreeCalendarRefreshCache } catch { }
    }
    foreach ($root in $tv.Nodes) {
        $tg = ''
        try { $tg = [string]$root.Tag } catch { }
        if ($tg -notmatch '^COMPANY\|(.+)$') { continue }
        $qk = $Matches[1].Trim()
        if ([string]::IsNullOrWhiteSpace($qk)) { continue }
        try { $root.Text = Hub-FormatCompanyTreeRootWithClockAndCal $qk } catch { }
    }
}

function Hub-FormatBotChannelTreeLabel {
    param([string]$CompanyKey, $Bot)
    $blb = [string]$Bot.Label
    $stamp = Hub-GetLastBuildStampText -CompanyKey $CompanyKey
    if ([string]::IsNullOrWhiteSpace($stamp)) { return $blb }
    return ($blb + ' (build ' + $stamp + ')')
}

function Hub-RefreshCompanyTree {
    $tv = $script:TvCompanies
    if ($null -eq $tv) { return }
    $checkedBotTags = New-Object 'System.Collections.Generic.HashSet[string]'
    foreach ($root in $tv.Nodes) {
        foreach ($ch in $root.Nodes) {
            $tg = [string]$ch.Tag
            if ($ch.Checked -and $tg.StartsWith('BOT|')) { [void]$checkedBotTags.Add($tg) }
        }
    }

    $tv.BeginUpdate()
    $script:CompanyTreeSuppressCheck = $true
    try {
        $tv.Nodes.Clear()
        foreach ($k in $script:ProjectKeys) {
            $root = New-Object System.Windows.Forms.TreeNode (Hub-FormatCompanyTreeRootWithClockAndCal $k)
            $root.Tag = ('COMPANY|' + $k)
            foreach ($bot in @(Get-HubBotChannelDefinitions)) {
                $bid = [string]$bot.Id
                $leafText = Hub-FormatBotChannelTreeLabel -CompanyKey $k -Bot $bot
                $leaf = New-Object System.Windows.Forms.TreeNode $leafText
                $leaf.Tag = ('BOT|' + $k + '|' + $bid)
                $leaf.Checked = $checkedBotTags.Contains($leaf.Tag)
                [void]$root.Nodes.Add($leaf)
            }
            [void]$tv.Nodes.Add($root)
        }
        $tv.ExpandAll()
        $hadChecked = $checkedBotTags.Count -gt 0
        if (-not $hadChecked -and $tv.Nodes.Count -gt 0) {
            foreach ($root in $tv.Nodes) {
                foreach ($ch in $root.Nodes) { $ch.Checked = $true }
                $root.Checked = $true
            }
        }
        if ($tv.Nodes.Count -gt 0) {
            $firstLeaf = $tv.Nodes[0].FirstNode
            if ($null -ne $firstLeaf) {
                $tv.SelectedNode = $firstLeaf
            } else {
                $tv.SelectedNode = $tv.Nodes[0]
            }
        }
    } finally {
        $script:CompanyTreeSuppressCheck = $false
        $tv.EndUpdate()
    }
    try {
        Hub-CompanyTreeCalendarRefreshCache
        $script:HubCompanyCalLastRefreshUtc = [datetime]::UtcNow
    } catch { }
    try { Hub-CompanyTreeClockApplyToAllRoots } catch { }
}

function Get-SelectedProjectKeys {
    $set = New-Object 'System.Collections.Generic.HashSet[string]'
    if ($null -eq $script:TvCompanies) { return @() }
    foreach ($root in $script:TvCompanies.Nodes) {
        foreach ($ch in $root.Nodes) {
            if (-not $ch.Checked) { continue }
            $tg = [string]$ch.Tag
            if ($tg -match '^BOT\|([A-Z0-9_]+)\|') { [void]$set.Add($Matches[1]) }
        }
    }
    return @($set | Sort-Object)
}

function Hub-GetFirstSelectedCompanyKey {
    if ($null -eq $script:TvCompanies) { return $null }
    $sn = $script:TvCompanies.SelectedNode
    if ($null -ne $sn) {
        $t = [string]$sn.Tag
        if ($t -match '^BOT\|([A-Z0-9_]+)\|') { return [string]$Matches[1] }
        if ($t -match '^COMPANY\|(.+)$') { return [string]$Matches[1].Trim() }
    }
    foreach ($root in $script:TvCompanies.Nodes) {
        foreach ($ch in $root.Nodes) {
            if (-not $ch.Checked) { continue }
            $tg = [string]$ch.Tag
            if ($tg -match '^BOT\|([A-Z0-9_]+)\|') { return [string]$Matches[1] }
        }
    }
    return $null
}

function Hub-CompanyKeyIsCheckedInTree {
    <# Есть ли у компании с ключом $CompanyKey в дереве галочка на корне или на любом боте (ищем корень по тегу COMPANY| без учёта регистра префикса). #>
    param([string]$CompanyKey)
    if ($null -eq $script:TvCompanies) { return $false }
    if ([string]::IsNullOrWhiteSpace($CompanyKey)) { return $false }
    foreach ($root in $script:TvCompanies.Nodes) {
        $tg = [string]$root.Tag
        if ($tg -notmatch '^(?i)COMPANY\|(.+)$') { continue }
        $rk = ([string]$Matches[1]).Trim()
        if (-not [string]::Equals($rk, $CompanyKey.Trim(), [StringComparison]::OrdinalIgnoreCase)) { continue }
        if ($root.Checked) { return $true }
        foreach ($ch in $root.Nodes) {
            if ($ch.Checked) { return $true }
        }
        return $false
    }
    return $false
}

function Hub-GetQueueControlCompanyKeysFromTree {
    <# Ключи в порядке deploy-config (ProjectKeys): ключ попадает в список, если для него Hub-CompanyKeyIsCheckedInTree. Так обрабатываются все отмеченные компании при «Все», без зависимости от перечисления Nodes. Если ни одна не отмечена — выделенный узел. #>
    if ($null -eq $script:TvCompanies) { return @() }
    $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($pk in @($script:ProjectKeys)) {
        if ($null -eq $pk) { continue }
        $k = ([string]$pk).Trim()
        if ([string]::IsNullOrWhiteSpace($k)) { continue }
        if (-not (Hub-CompanyKeyIsCheckedInTree -CompanyKey $k)) { continue }
        if ($seen.Add($k)) { [void]$out.Add($k) }
    }
    if ($out.Count -gt 0) {
        return @($out.ToArray())
    }
    $sn = $script:TvCompanies.SelectedNode
    if ($null -ne $sn) {
        $t = [string]$sn.Tag
        if ($t -match '^(?i)COMPANY\|(.+)$') {
            $k = ([string]$Matches[1]).Trim()
            if (-not [string]::IsNullOrWhiteSpace($k)) { return @($k) }
        }
        if ($t -match '^(?i)BOT\|([^|]+)\|') {
            $bk = ([string]$Matches[1]).Trim()
            if (-not [string]::IsNullOrWhiteSpace($bk)) { return @($bk) }
        }
    }
    return @()
}

function Hub-GetCatalogCompanyKeyFromTree {
    if ($null -eq $script:TvCompanies) { return $null }
    foreach ($root in $script:TvCompanies.Nodes) {
        foreach ($ch in $root.Nodes) {
            if (-not $ch.Checked) { continue }
            $tg = [string]$ch.Tag
            if ($tg -notmatch '^BOT\|([A-Z0-9_]+)\|(.+)$') { continue }
            $k = [string]$Matches[1]
            $bid = [string]$Matches[2]
            if ($bid -eq (Hub-GetCatalogRequiredBotId $k)) { return $k }
        }
    }
    $sn = $script:TvCompanies.SelectedNode
    if ($null -ne $sn) {
        $t = [string]$sn.Tag
        if ($t -match '^BOT\|([A-Z0-9_]+)\|(.+)$') {
            $k = [string]$Matches[1]
            $bid = [string]$Matches[2]
            if ($bid -eq (Hub-GetCatalogRequiredBotId $k)) { return $k }
        }
        if ($t -match '^COMPANY\|(.+)$') {
            $k = [string]$Matches[1].Trim()
            if ([string]::IsNullOrWhiteSpace($k)) { return $null }
            $req = Hub-GetCatalogRequiredBotId $k
            $needTag = 'BOT|' + $k + '|' + $req
            foreach ($root2 in $script:TvCompanies.Nodes) {
                foreach ($ch2 in $root2.Nodes) {
                    if ([string]$ch2.Tag -ne $needTag) { continue }
                    if ($ch2.Checked) { return $k }
                }
            }
        }
    }
    return $null
}

function Hub-GetCompanyKeyForRemoveAction {
    if ($null -eq $script:TvCompanies) { return $null }
    $sn = $script:TvCompanies.SelectedNode
    if ($null -ne $sn) {
        $t = [string]$sn.Tag
        if ($t -match '^BOT\|([A-Z0-9_]+)\|') { return [string]$Matches[1] }
        if ($t -match '^COMPANY\|(.+)$') { return [string]$Matches[1].Trim() }
    }
    return (Hub-GetFirstSelectedCompanyKey)
}

function Hub-EnsureHubDataDirs {
    if (-not (Test-Path -LiteralPath $script:HubDataDir)) {
        [void](New-Item -ItemType Directory -Force -Path $script:HubDataDir)
    }
    if (-not (Test-Path -LiteralPath $script:HubCatalogsRoot)) {
        [void](New-Item -ItemType Directory -Force -Path $script:HubCatalogsRoot)
    }
    if (-not (Test-Path -LiteralPath $script:HubChatsArchiveRoot)) {
        [void](New-Item -ItemType Directory -Force -Path $script:HubChatsArchiveRoot)
    }
    if (-not (Test-Path -LiteralPath $script:HubTestersRoot)) {
        [void](New-Item -ItemType Directory -Force -Path $script:HubTestersRoot)
    }
}

function Hub-GetTestersJsonPath {
    param([string]$CompanyKey)
    if ([string]::IsNullOrWhiteSpace($CompanyKey)) { return $null }
    $k = $CompanyKey.Trim()
    return (Join-Path $script:HubTestersRoot ($k + '.json'))
}

function Hub-GetTesterPhoneNorm {
    param($Tester)
    if ($null -eq $Tester) { return '' }
    foreach ($prop in @('phone_e164', 'phone_digits', 'destination')) {
        if ($Tester.PSObject.Properties[$prop] -and $null -ne $Tester.$prop) {
            $s = ([string]$Tester.$prop).Trim() -replace '\D', ''
            if ($s.Length -ge 6) { return $s }
        }
    }
    return ''
}

function Hub-GetTesterDedupeKey {
    <# Ключ для слияния с catalog: длинный номер; иначе стабильный id. #>
    param($Tester)
    $pn = Hub-GetTesterPhoneNorm -Tester $Tester
    if ($pn.Length -ge 8) { return ('p:' + $pn) }
    if ($pn.Length -ge 6) { return ('p:' + $pn) }
    $id = Hub-TesterStableId -Tester $Tester -Index 0
    return ('i:' + $id.ToLowerInvariant())
}

function Hub-GetCatalogTestersPeople {
    <# Массив людей из активного catalog.json → company.testers.people (раньше хранилось в справочнике WA). #>
    param([string]$CompanyKey)
    if ([string]::IsNullOrWhiteSpace($CompanyKey)) { return @() }
    $path = Get-ActiveCatalogJsonPath -Key $CompanyKey.Trim()
    if (-not $path -or -not (Test-Path -LiteralPath $path)) { return @() }
    try {
        $raw = [System.IO.File]::ReadAllText($path, [System.Text.UTF8Encoding]::new($false))
        $cat = $raw | ConvertFrom-Json
        if ($null -eq $cat -or -not $cat.PSObject.Properties['testers']) { return @() }
        $tw = $cat.testers
        if ($null -eq $tw -or -not $tw.PSObject.Properties['people']) { return @() }
        return @($tw.people)
    } catch {
        return @()
    }
}

function Hub-ConvertCatalogPersonToTester {
    param($Person)
    if ($null -eq $Person) { return $null }
    $tok = ''
    if ($Person.PSObject.Properties['test_owner_key'] -and $null -ne $Person.test_owner_key) {
        $tok = ([string]$Person.test_owner_key).Trim()
    }
    if ([string]::IsNullOrWhiteSpace($tok) -and $Person.PSObject.Properties['display_name']) {
        $tok = ([string]$Person.display_name).Trim()
    }
    if ([string]::IsNullOrWhiteSpace($tok)) { $tok = 'tester' }
    $idBase = [regex]::Replace($tok, '[^\p{L}\p{N}]+', '_').Trim('_')
    if ([string]::IsNullOrWhiteSpace($idBase)) { $idBase = 'tester' }
    if ($idBase.Length -gt 64) { $idBase = $idBase.Substring(0, 64).TrimEnd('_') }
    $digits = ''
    if ($Person.PSObject.Properties['phone_digits'] -and $null -ne $Person.phone_digits) {
        $digits = ([string]$Person.phone_digits).Trim() -replace '\D', ''
    }
    $id = $idBase
    if ($digits.Length -ge 2) {
        $suf = $digits.Substring([Math]::Max(0, $digits.Length - 8))
        $id = ($idBase + '_' + $suf)
    }
    if ($id.Length -gt 96) { $id = $id.Substring(0, 96).TrimEnd('_') }
    $e164 = ''
    if ($Person.PSObject.Properties['phone_e164'] -and $null -ne $Person.phone_e164) {
        $e164 = ([string]$Person.phone_e164).Trim()
    }
    $dn = $tok
    if ($Person.PSObject.Properties['display_name'] -and $null -ne $Person.display_name) {
        $t = ([string]$Person.display_name).Trim()
        if (-not [string]::IsNullOrWhiteSpace($t)) { $dn = $t }
    }
    $co = ''
    if ($Person.PSObject.Properties['company'] -and $null -ne $Person.company) {
        $co = ([string]$Person.company).Trim()
    }
    $towner = ''
    if ($Person.PSObject.Properties['test_owner_key'] -and $null -ne $Person.test_owner_key) {
        $towner = ([string]$Person.test_owner_key).Trim()
    }
    return [pscustomobject]@{
        id               = $id
        display_name     = $dn
        phone_e164       = $e164
        destination      = $digits
        company          = $co
        test_owner_key   = $towner
        notes            = 'Из catalog.json (блок testers.people, WhatsApp / справочник)'
    }
}

function Hub-MergeCatalogTestersIntoArray {
    <# Дописывает людей из каталога, если такого ключа (телефон / id) ещё нет в списке файла. #>
    param($ExistingTesters, $CatalogPeople)
    $out = New-Object System.Collections.Generic.List[object]
    $seen = @{}
    foreach ($t in @($ExistingTesters)) {
        if ($null -eq $t) { continue }
        [void]$out.Add($t)
        $k = Hub-GetTesterDedupeKey -Tester $t
        if (-not [string]::IsNullOrWhiteSpace($k)) { $seen[$k] = $true }
    }
    foreach ($p in @($CatalogPeople)) {
        $t = Hub-ConvertCatalogPersonToTester -Person $p
        if ($null -eq $t) { continue }
        $k = Hub-GetTesterDedupeKey -Tester $t
        if (-not [string]::IsNullOrWhiteSpace($k) -and $seen.ContainsKey($k)) { continue }
        [void]$out.Add($t)
        if (-not [string]::IsNullOrWhiteSpace($k)) { $seen[$k] = $true }
    }
    return @($out.ToArray())
}

function Hub-MigrateAllTestersFromCatalogJson {
    <# Записывает в data\testers\<ключ>.json объединение файла и testers.people из активного catalog.json по всем ключам из companies. #>
    Hub-EnsureHubDataDirs
    if ($null -eq $script:ProjectKeys) { return 'Нет ключей проектов (companies).' }
    $sb = New-Object System.Text.StringBuilder
    foreach ($k in @($script:ProjectKeys)) {
        $path = Hub-GetTestersJsonPath -CompanyKey $k
        if ($null -eq $path) { continue }
        $arr = @()
        $defId = ''
        if (Test-Path -LiteralPath $path) {
            try {
                $raw = [System.IO.File]::ReadAllText($path, [System.Text.UTF8Encoding]::new($false))
                $doc = $raw | ConvertFrom-Json
                if ($null -ne $doc -and $doc.PSObject.Properties['testers'] -and $null -ne $doc.testers) {
                    $arr = @($doc.testers)
                }
                if ($null -ne $doc -and $doc.PSObject.Properties['default_tester_id'] -and $null -ne $doc.default_tester_id) {
                    $defId = ([string]$doc.default_tester_id).Trim()
                }
            } catch {
                [void]$sb.AppendLine("[$k] ошибка чтения JSON: " + $_.Exception.Message)
                continue
            }
        }
        $people = Hub-GetCatalogTestersPeople -CompanyKey $k
        if ($people.Count -eq 0) {
            [void]$sb.AppendLine("[$k] нет testers.people в активном catalog.json")
            continue
        }
        $before = $arr.Count
        $merged = Hub-MergeCatalogTestersIntoArray -ExistingTesters $arr -CatalogPeople $people
        $after = $merged.Count
        if ($after -le $before) {
            [void]$sb.AppendLine("[$k] каталог: $($people.Count) чел.; новых записей нет (в файле $before)")
            continue
        }
        $outObj = [ordered]@{
            default_tester_id = $defId
            testers           = @($merged)
        }
        $json = ($outObj | ConvertTo-Json -Depth 40)
        if (-not $json.EndsWith("`n")) { $json = $json + "`r`n" }
        [System.IO.File]::WriteAllText($path, $json, (New-Object System.Text.UTF8Encoding $false))
        [void]$sb.AppendLine("[$k] добавлено $($after - $before) из catalog → всего $after → " + [System.IO.Path]::GetFileName($path))
    }
    $s = $sb.ToString().TrimEnd()
    if ([string]::IsNullOrWhiteSpace($s)) { return 'Готово.' }
    return $s
}

function Hub-TesterStableId {
    param($Tester, [int]$Index)
    if ($null -eq $Tester) { return ('tester_' + [string]$Index) }
    foreach ($prop in @('id', 'key', 'code')) {
        if ($Tester.PSObject.Properties[$prop] -and $null -ne $Tester.$prop) {
            $s = ([string]$Tester.$prop).Trim()
            if (-not [string]::IsNullOrWhiteSpace($s)) { return $s }
        }
    }
    return ('tester_' + [string]$Index)
}

function Hub-TesterDisplayNameForList {
    param($Tester, [int]$Index)
    if ($null -eq $Tester) { return ('Тестер ' + [string]$Index) }
    foreach ($prop in @('display_name', 'name', 'title', 'label')) {
        if ($Tester.PSObject.Properties[$prop] -and $null -ne $Tester.$prop) {
            $s = ([string]$Tester.$prop).Trim()
            if (-not [string]::IsNullOrWhiteSpace($s)) { return $s }
        }
    }
    return (Hub-TesterStableId -Tester $Tester -Index $Index)
}

function Hub-TesterFormatPhoneForList {
    param($Tester)
    if ($null -eq $Tester) { return 'нет номера' }
    if ($Tester.PSObject.Properties['phone_e164'] -and $null -ne $Tester.phone_e164) {
        $s = ([string]$Tester.phone_e164).Trim()
        if (-not [string]::IsNullOrWhiteSpace($s)) { return $s }
    }
    $digits = Hub-GetTesterPhoneNorm -Tester $Tester
    if ($digits.Length -ge 6) { return $digits }
    if ($digits.Length -ge 1) { return $digits }
    return 'нет номера'
}

function Hub-TesterListLabel {
    param($Tester, [int]$Index)
    $nm = Hub-TesterDisplayNameForList -Tester $Tester -Index $Index
    $ph = Hub-TesterFormatPhoneForList -Tester $Tester
    return ($nm + ' (' + $ph + ')')
}

function Hub-TestersPopulateListAndCombo {
    <# Обновляет LstTesters и CmbTestersDefault из массива (без чтения файла). #>
    param(
        [object[]]$Merged,
        [string]$DefaultTesterIdPrefer = '',
        [int]$ListSelectIndex = 0
    )
    $merged = @($Merged)
    $script:TestersLoadedList = $merged
    $script:TestersJsonParseFailed = $false
    $script:TestersUiSuppress = $true
    try {
        if ($null -ne $script:LstTesters) { $script:LstTesters.Items.Clear() }
        if ($null -ne $script:CmbTestersDefault) {
            $script:CmbTestersDefault.Items.Clear()
            [void]$script:CmbTestersDefault.Items.Add('<нет>')
        }
        $ix = 0
        for ($i = 0; $i -lt $merged.Count; $i++) {
            $tid = Hub-TesterStableId -Tester $merged[$i] -Index $i
            if ($null -ne $script:LstTesters) {
                [void]$script:LstTesters.Items.Add((Hub-TesterListLabel -Tester $merged[$i] -Index $i))
            }
            if ($null -ne $script:CmbTestersDefault) {
                [void]$script:CmbTestersDefault.Items.Add($tid)
                if (-not [string]::IsNullOrWhiteSpace($DefaultTesterIdPrefer) -and ($tid -eq $DefaultTesterIdPrefer)) {
                    $ix = $i + 1
                }
            }
        }
        if ($null -ne $script:CmbTestersDefault -and $script:CmbTestersDefault.Items.Count -gt 0) {
            $script:CmbTestersDefault.SelectedIndex = [Math]::Min($ix, $script:CmbTestersDefault.Items.Count - 1)
        }
    } finally {
        $script:TestersUiSuppress = $false
    }
    if ($null -ne $script:LstTesters -and $script:LstTesters.Items.Count -gt 0) {
        $si = [Math]::Max(0, [Math]::Min($ListSelectIndex, $script:LstTesters.Items.Count - 1))
        $script:LstTesters.SelectedIndex = $si
    } elseif ($null -ne $script:LstTesters) {
        Hub-ApplyTestersDetailGrid -Tester $null
    }
    if ($null -ne $script:LstTesters -and $script:LstTesters.SelectedIndex -ge 0) {
        Hub-TestersListSelectedChanged
    }
    Hub-TestersUpdateAddRemoveButtons
}

function Hub-TestersUpdateAddRemoveButtons {
    $can = $false
    if ($null -ne $script:TestersCurrentKey -and -not [string]::IsNullOrWhiteSpace($script:TestersCurrentKey) -and -not $script:TestersJsonParseFailed) {
        $can = $true
    }
    if ($null -ne $script:BtnTestersAdd) { $script:BtnTestersAdd.Enabled = $can }
    $rm = $false
    if ($can -and $null -ne $script:LstTesters -and $script:LstTesters.Items.Count -gt 0 -and $script:LstTesters.SelectedIndex -ge 0) {
        $rm = $true
    }
    if ($null -ne $script:BtnTestersRemove) { $script:BtnTestersRemove.Enabled = $rm }
}

function Hub-TestersSuggestNewTesterId {
    $base = 'tester_new_' + (Get-Date -Format 'yyyyMMddHHmmss')
    $merged = @()
    if ($null -ne $script:TestersLoadedList) { $merged = @($script:TestersLoadedList) }
    $try = $base
    $n = 0
    while ($true) {
        $ok = $true
        for ($i = 0; $i -lt $merged.Count; $i++) {
            if ((Hub-TesterStableId -Tester $merged[$i] -Index $i) -eq $try) { $ok = $false; break }
        }
        if ($ok) { return $try }
        $n++
        $try = $base + '_' + [string]$n
        if ($n -gt 500) { return ([guid]::NewGuid().ToString('n')) }
    }
}

function Hub-TestersPromptNewTesterFields {
    <# Имя и телефон для нового тестера; при отмене имени — $null; без Microsoft.VisualBasic — имя по умолчанию. #>
    $name = 'Новый тестер'
    $phone = ''
    try {
        Add-Type -AssemblyName Microsoft.VisualBasic -ErrorAction Stop
        $p1 = [Microsoft.VisualBasic.Interaction]::InputBox('Отображаемое имя тестера:', 'Новый тестер', $name)
        if ([string]::IsNullOrWhiteSpace($p1)) { return $null }
        $name = $p1.Trim()
        $p2 = [Microsoft.VisualBasic.Interaction]::InputBox('Телефон (цифры или E.164, можно оставить пустым):', 'Новый тестер', $phone)
        if ($null -ne $p2) { $phone = $p2.Trim() }
    } catch {
        # диалогов нет — оставляем «Новый тестер» и пустой телефон
    }
    return [pscustomobject]@{ DisplayName = $name; Phone = $phone }
}

function Hub-TestersAddNewClick {
    if ([string]::IsNullOrWhiteSpace($script:TestersCurrentKey)) {
        $k = Hub-GetFirstSelectedCompanyKey
        if ([string]::IsNullOrWhiteSpace($k)) {
            [void][System.Windows.Forms.MessageBox]::Show('Выберите в дереве проект (компанию / бота).', $script:HubAppTitle)
            return
        }
        $script:TestersCurrentKey = $k
    }
    $fields = Hub-TestersPromptNewTesterFields
    if ($null -eq $fields) { return }
    $id = Hub-TestersSuggestNewTesterId
    $phRaw = ''
    if ($null -ne $fields.Phone) { $phRaw = [string]$fields.Phone }
    $digits = ($phRaw -replace '\D', '')
    $e164 = ''
    if ($phRaw.Trim().StartsWith('+')) { $e164 = $phRaw.Trim() }
    $merged = @()
    if ($null -ne $script:TestersLoadedList) { $merged = @($script:TestersLoadedList) }
    $list = New-Object System.Collections.Generic.List[object]
    foreach ($x in $merged) { [void]$list.Add($x) }
    $newT = [pscustomobject]@{
        id               = $id
        display_name     = $fields.DisplayName
        phone_e164       = $e164
        destination      = $digits
        notes            = ''
    }
    [void]$list.Add($newT)
    $merged = @($list.ToArray())
    $defPref = ''
    if ($null -ne $script:CmbTestersDefault -and $script:CmbTestersDefault.SelectedIndex -gt 0) {
        $defPref = [string]$script:CmbTestersDefault.SelectedItem
    }
    Hub-TestersPopulateListAndCombo -Merged $merged -DefaultTesterIdPrefer $defPref -ListSelectIndex ($merged.Count - 1)
    if ($null -ne $script:BtnTestersSave) { $script:BtnTestersSave.Enabled = $true }
}

function Hub-TestersRemoveClick {
    $lst = $script:LstTesters
    if ($null -eq $lst -or $lst.SelectedIndex -lt 0) { return }
    $idx = $lst.SelectedIndex
    $merged = @()
    if ($null -ne $script:TestersLoadedList) { $merged = @($script:TestersLoadedList) }
    if ($idx -ge $merged.Count) { return }
    $nm = Hub-TesterListLabel -Tester $merged[$idx] -Index $idx
    $r = [System.Windows.Forms.MessageBox]::Show(
        "Удалить тестера из списка в памяти?`n$nm`n`nИзменения запишутся в JSON только после «Сохранить тестеров».",
        $script:HubAppTitle,
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question)
    if ($r -ne [System.Windows.Forms.DialogResult]::Yes) { return }
    $removedId = Hub-TesterStableId -Tester $merged[$idx] -Index $idx
    $list = New-Object System.Collections.Generic.List[object]
    for ($i = 0; $i -lt $merged.Count; $i++) {
        if ($i -ne $idx) { [void]$list.Add($merged[$i]) }
    }
    $merged = @($list.ToArray())
    $defPref = ''
    if ($null -ne $script:CmbTestersDefault -and $script:CmbTestersDefault.SelectedIndex -gt 0) {
        $cur = [string]$script:CmbTestersDefault.SelectedItem
        if ($cur -ne '<нет>' -and $cur -ne $removedId) { $defPref = $cur }
    }
    $newSel = [Math]::Min($idx, [Math]::Max(0, $merged.Count - 1))
    if ($merged.Count -eq 0) { $newSel = 0 }
    Hub-TestersPopulateListAndCombo -Merged $merged -DefaultTesterIdPrefer $defPref -ListSelectIndex $newSel
    if ($null -ne $script:BtnTestersSave) { $script:BtnTestersSave.Enabled = $true }
}

function Hub-FlattenTesterObjectToRows {
    <# Плоский список полей для таблицы (вложенные объекты и массивы — как JSON в «Значение»). #>
    param($Node, [string]$Prefix = '')
    $list = New-Object System.Collections.Generic.List[object]
    function LocalWalkTester($o, [string]$pfx) {
        if ($null -eq $o) {
            [void]$list.Add([pscustomobject]@{ Path = $pfx; Value = '' })
            return
        }
        if ($o -is [string] -or $o -is [char]) {
            [void]$list.Add([pscustomobject]@{ Path = $pfx; Value = [string]$o })
            return
        }
        if ($o -is [bool]) {
            [void]$list.Add([pscustomobject]@{ Path = $pfx; Value = ([string]$o).ToLowerInvariant() })
            return
        }
        if ($o -is [int] -or $o -is [long] -or $o -is [double] -or $o -is [decimal]) {
            [void]$list.Add([pscustomobject]@{ Path = $pfx; Value = [string]$o })
            return
        }
        if ($o -is [System.Collections.IList] -and $o -isnot [string] -and $o -isnot [char[]]) {
            try {
                $js = ($o | ConvertTo-Json -Depth 30 -Compress -ErrorAction Stop)
                [void]$list.Add([pscustomobject]@{ Path = $pfx; Value = $js })
            } catch {
                [void]$list.Add([pscustomobject]@{ Path = $pfx; Value = [string]$o })
            }
            return
        }
        if ($o -is [hashtable]) {
            foreach ($k in @($o.Keys | Sort-Object)) {
                $np = if ([string]::IsNullOrWhiteSpace($pfx)) { [string]$k } else { $pfx + '.' + [string]$k }
                LocalWalkTester $o[$k] $np
            }
            return
        }
        if ($null -ne $o.PSObject) {
            $props = @($o.PSObject.Properties | Where-Object { $_.MemberType -eq 'NoteProperty' })
            foreach ($p in $props) {
                $nm = [string]$p.Name
                $np = if ([string]::IsNullOrWhiteSpace($pfx)) { $nm } else { $pfx + '.' + $nm }
                LocalWalkTester $p.Value $np
            }
            return
        }
        [void]$list.Add([pscustomobject]@{ Path = $pfx; Value = [string]$o })
    }
    LocalWalkTester $Node $Prefix
    return @($list.ToArray())
}

function Hub-TestersApplyDgvColumnWidths {
    <# Колонки: поле | значение (Fill) | адрес (схема) — как на вкладке «Справочники». #>
    $dgv = $script:DgvTestersDetail
    if ($null -eq $dgv) { return }
    $cK = $dgv.Columns['ColTesterKey']
    $cV = $dgv.Columns['ColTesterVal']
    $cA = $dgv.Columns['ColTesterAddr']
    if ($null -eq $cK -or $null -eq $cV -or $null -eq $cA) { return }
    $cw = [int]$dgv.ClientSize.Width
    if ($cw -lt 160) { return }
    $minVal = 100
    $minAddr = 96
    $rest = $cw - $minVal - $minAddr - 10
    if ($rest -lt 80) { $rest = [Math]::Max(72, $cw - $minAddr - 16) }
    $keyW = [int][Math]::Max(100, [Math]::Min(240, [Math]::Floor($rest * 0.40)))
    $addrW = [int][Math]::Max($minAddr, [Math]::Min(220, [Math]::Floor($cw * 0.24)))
    if ($keyW + $addrW + $minVal -gt $cw) {
        $s = ($cw - $minVal - 8) / [double][Math]::Max(1, ($keyW + $addrW))
        $keyW = [int][Math]::Max(88, [Math]::Floor($keyW * $s))
        $addrW = [int][Math]::Max(72, [Math]::Floor($addrW * $s))
    }
    $dgv.SuspendLayout()
    try {
        $cK.DisplayIndex = 0
        $cV.DisplayIndex = 1
        $cA.DisplayIndex = 2
        $cV.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::Fill
        $cK.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::None
        $cA.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::None
        $cK.Width = $keyW
        $cA.Width = $addrW
        try { $dgv.HorizontalScrollingOffset = 0 } catch { }
        try { $dgv.FirstDisplayedScrollingColumnIndex = 0 } catch { }
    } finally {
        try { $dgv.ResumeLayout($true) } catch { }
    }
}

function Hub-ApplyTestersDetailGrid {
    param($Tester)
    $dgv = $script:DgvTestersDetail
    if ($null -eq $dgv) { return }
    $dgv.SuspendLayout()
    $script:TestersUiSuppress = $true
    try {
        $dgv.Rows.Clear()
        if ($null -eq $Tester) { return }
        $catRoot = $null
        $ck = [string]$script:TestersCurrentKey
        if (-not [string]::IsNullOrWhiteSpace($ck)) {
            $cp = Get-ActiveCatalogJsonPath -Key $ck.Trim()
            if ($null -ne $cp -and (Test-Path -LiteralPath $cp)) {
                try {
                    $raw = [System.IO.File]::ReadAllText($cp, [System.Text.UTF8Encoding]::new($false))
                    $catRoot = $raw | ConvertFrom-Json
                } catch { $catRoot = $null }
            }
        }
        foreach ($row in @(Hub-FlattenTesterObjectToRows -Node $Tester)) {
            $addr = ''
            if ($null -ne $catRoot) {
                try {
                    $addr = [string](Hub-GetCatalogSuggestSchemaAddress -Path ([string]$row.Path) -Root $catRoot)
                } catch { $addr = '' }
            }
            [void]$dgv.Rows.Add([string]$row.Path, [string]$row.Value, $addr)
        }
    } finally {
        $script:TestersUiSuppress = $false
        $dgv.ResumeLayout()
        try { Hub-TestersApplyDgvColumnWidths } catch { }
    }
}

function Hub-RefreshTestersTab {
    Hub-EnsureHubDataDirs
    $key = Hub-GetFirstSelectedCompanyKey
    $script:TestersCurrentKey = $key
    $tp = $script:TpTesters
    if ($null -eq $tp) { return }
    $path = Hub-GetTestersJsonPath -CompanyKey $key
    $c = $null
    if (-not [string]::IsNullOrWhiteSpace($key) -and $null -ne $script:Companies -and $script:Companies.PSObject.Properties[$key]) {
        $c = $script:Companies.$key
    }
    $compLine = if ([string]::IsNullOrWhiteSpace($key)) {
        'Проект: в дереве слева выберите компанию или отмеченного бота — по ключу (CO_, PE_, …) подгружается файл тестеров.'
    } else {
        $nm = if ($c) { [string]$c.name } else { '' }
        $cc = if ($c) { [string]$c.country } else { '' }
        ('Проект: ' + $key + $(if ($nm) { ' — ' + $nm } else { '' }) + $(if ($cc) { ' (' + $cc + ')' } else { '' }))
    }
    if ($null -ne $script:LblTestersCompany) { $script:LblTestersCompany.Text = $compLine }
    $script:TestersJsonParseFailed = $false
    $parseErr = $null
    $merged = @()
    $defId = ''
    $script:TestersUiSuppress = $true
    try {
        if ($null -ne $script:LstTesters) { $script:LstTesters.Items.Clear() }
        if ($null -ne $script:CmbTestersDefault) { $script:CmbTestersDefault.Items.Clear() }
        $script:TestersLoadedList = @()
        $pathLine = if ($path) { 'Файл: data\testers\' + [System.IO.Path]::GetFileName($path) } else { 'Файл: —' }
        if ([string]::IsNullOrWhiteSpace($key)) {
            if ($null -ne $script:LblTestersPath) { $script:LblTestersPath.Text = $pathLine }
            if ($null -ne $script:CmbTestersDefault) { [void]$script:CmbTestersDefault.Items.Add('<нет>') }
            if ($null -ne $script:CmbTestersDefault) { $script:CmbTestersDefault.SelectedIndex = 0 }
            Hub-ApplyTestersDetailGrid -Tester $null
            if ($null -ne $script:BtnTestersSave) { $script:BtnTestersSave.Enabled = $false }
            Hub-TestersUpdateAddRemoveButtons
            return
        }
        $arr = @()
        if ($path -and (Test-Path -LiteralPath $path)) {
            try {
                $raw = [System.IO.File]::ReadAllText($path, [System.Text.UTF8Encoding]::new($false))
                $doc = $raw | ConvertFrom-Json
                if ($null -ne $doc -and $doc.PSObject.Properties['testers'] -and $null -ne $doc.testers) {
                    $arr = @($doc.testers)
                }
                if ($null -ne $doc -and $doc.PSObject.Properties['default_tester_id'] -and $null -ne $doc.default_tester_id) {
                    $defId = ([string]$doc.default_tester_id).Trim()
                }
            } catch {
                $parseErr = $_.Exception.Message
            }
        }
        if ($null -ne $parseErr) {
            $script:TestersJsonParseFailed = $true
            if ($null -ne $script:LblTestersPath) {
                $script:LblTestersPath.Text = $pathLine + [Environment]::NewLine + 'Ошибка JSON: ' + $parseErr
            }
            Hub-ApplyTestersDetailGrid -Tester $null
            if ($null -ne $script:CmbTestersDefault) { [void]$script:CmbTestersDefault.Items.Add('<нет>') }
            if ($null -ne $script:CmbTestersDefault) { $script:CmbTestersDefault.SelectedIndex = 0 }
            if ($null -ne $script:BtnTestersSave) { $script:BtnTestersSave.Enabled = $true }
            Hub-TestersUpdateAddRemoveButtons
            return
        }
        $fromFileCount = $arr.Count
        $people = Hub-GetCatalogTestersPeople -CompanyKey $key
        $merged = Hub-MergeCatalogTestersIntoArray -ExistingTesters $arr -CatalogPeople $people
        if ($null -ne $script:LblTestersPath) {
            $extra = ''
            if ($people.Count -gt 0) {
                $added = $merged.Count - $fromFileCount
                if ($added -gt 0) {
                    $extra = [Environment]::NewLine + "Из catalog.json (testers.people): +$added чел. к списку (всего $($merged.Count))."
                } else {
                    $extra = [Environment]::NewLine + 'catalog.json: testers.people учтён (новых номеров нет).'
                }
            }
            $script:LblTestersPath.Text = $pathLine + $extra
        }
    } finally {
        $script:TestersUiSuppress = $false
    }
    if (-not [string]::IsNullOrWhiteSpace($key) -and $null -eq $parseErr) {
        Hub-TestersPopulateListAndCombo -Merged $merged -DefaultTesterIdPrefer $defId -ListSelectIndex 0
        if ($null -ne $script:BtnTestersSave) { $script:BtnTestersSave.Enabled = $true }
    } else {
        Hub-TestersUpdateAddRemoveButtons
    }
}

function Hub-TestersListSelectedChanged {
    if ($script:TestersUiSuppress) { return }
    $lst = $script:LstTesters
    if ($null -eq $lst -or $lst.SelectedIndex -lt 0) {
        Hub-ApplyTestersDetailGrid -Tester $null
        Hub-TestersUpdateAddRemoveButtons
        return
    }
    $arr = $script:TestersLoadedList
    if ($null -eq $arr -or $lst.SelectedIndex -ge $arr.Count) {
        Hub-ApplyTestersDetailGrid -Tester $null
        Hub-TestersUpdateAddRemoveButtons
        return
    }
    Hub-ApplyTestersDetailGrid -Tester $arr[$lst.SelectedIndex]
    Hub-TestersUpdateAddRemoveButtons
}

function Hub-SaveTestersDocument {
    Hub-EnsureHubDataDirs
    $key = $script:TestersCurrentKey
    if ([string]::IsNullOrWhiteSpace($key)) {
        $key = Hub-GetFirstSelectedCompanyKey
    }
    if ([string]::IsNullOrWhiteSpace($key)) {
        [void][System.Windows.Forms.MessageBox]::Show('Выберите в дереве проект (компанию / бота).', $script:HubAppTitle)
        return
    }
    $path = Hub-GetTestersJsonPath -CompanyKey $key
    if ($null -eq $path) { return }
    $defOut = ''
    if ($null -ne $script:CmbTestersDefault -and $script:CmbTestersDefault.SelectedIndex -ge 0) {
        $sel = [string]$script:CmbTestersDefault.SelectedItem
        if ($sel -ne '<нет>') { $defOut = $sel }
    }
    $arr = @()
    if ($null -ne $script:TestersLoadedList) { $arr = @($script:TestersLoadedList) }
    $known = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::Ordinal)
    for ($i = 0; $i -lt $arr.Count; $i++) {
        [void]$known.Add((Hub-TesterStableId -Tester $arr[$i] -Index $i))
    }
    if (-not [string]::IsNullOrWhiteSpace($defOut) -and -not $known.Contains($defOut)) {
        [void][System.Windows.Forms.MessageBox]::Show(
            "Дефолтный тестер «$defOut» не найден среди id в списке. Выберите id из комбобокса или добавьте тестера в JSON.",
            $script:HubAppTitle, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Warning)
        return
    }
    $outObj = [ordered]@{
        default_tester_id = $defOut
        testers           = @($arr)
    }
    $json = ($outObj | ConvertTo-Json -Depth 40)
    if (-not $json.EndsWith("`n")) { $json = $json + "`r`n" }
    [System.IO.File]::WriteAllText($path, $json, (New-Object System.Text.UTF8Encoding $false))
    if ($null -ne $script:TxtLog) { Append-Log ("Тестеры сохранены: $path") }
    [void][System.Windows.Forms.MessageBox]::Show("Записано:`n$path", $script:HubAppTitle,
        [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
}

function Hub-AttachCompaniesToCfgRoot {
    if ($null -eq $script:CfgRoot -or $null -eq $script:Companies) { return }
    $script:CfgRoot | Add-Member -MemberType NoteProperty -Name companies -Value $script:Companies -Force
}

function Hub-MigrateCompanyCatalogsFromRepo {
    if (Test-Path -LiteralPath $script:RegistryPath) { return $false }
    if (-not (Test-Path -LiteralPath $script:RepoCompanyCatalogsRoot)) { return $false }
    Hub-EnsureHubDataDirs
    foreach ($item in @(Get-ChildItem -LiteralPath $script:RepoCompanyCatalogsRoot -Force)) {
        if ($item.Name -eq 'tools') { continue }
        $dest = Join-Path $script:HubCatalogsRoot $item.Name
        if ($item.PSIsContainer) {
            Copy-Item -LiteralPath $item.FullName -Destination $dest -Recurse -Force
        } else {
            Copy-Item -LiteralPath $item.FullName -Destination $dest -Force
        }
    }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    if (-not (Test-Path -LiteralPath $script:HubCompaniesPath)) {
        $cfgText = [System.IO.File]::ReadAllText($script:ConfigPath, $utf8)
        $cfgObj = $cfgText | ConvertFrom-Json
        $coJson = ($cfgObj.companies | ConvertTo-Json -Depth 40) + "`r`n"
        [System.IO.File]::WriteAllText($script:HubCompaniesPath, $coJson, $utf8)
    }
    return $true
}

function Hub-ReloadDeployConfig {
    if (-not (Test-Path -LiteralPath $script:ConfigPath)) {
        throw "Не найден deploy-config.json: $($script:ConfigPath)"
    }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $cfgText = [System.IO.File]::ReadAllText($script:ConfigPath, $utf8)
    $script:CfgRoot = $cfgText | ConvertFrom-Json
    if (Test-Path -LiteralPath $script:HubCompaniesPath) {
        $hubCoText = [System.IO.File]::ReadAllText($script:HubCompaniesPath, $utf8)
        $script:Companies = $hubCoText | ConvertFrom-Json
        Hub-AttachCompaniesToCfgRoot
    } else {
        $script:Companies = $script:CfgRoot.companies
    }
    $script:ProjectKeys = @(
        $script:Companies.PSObject.Properties.Name | Where-Object { $_ -notmatch '^_' } | Sort-Object
    )
    if ($null -ne $script:TvCompanies) {
        Hub-RefreshCompanyTree
    }
}

function Hub-SaveDeployConfigToDisk {
    $utf8 = New-Object System.Text.UTF8Encoding $false
    Hub-EnsureHubDataDirs
    Hub-AttachCompaniesToCfgRoot
    $coJson = ($script:Companies | ConvertTo-Json -Depth 40) + "`r`n"
    [System.IO.File]::WriteAllText($script:HubCompaniesPath, $coJson, $utf8)
    $json = ($script:CfgRoot | ConvertTo-Json -Depth 40) + "`r`n"
    [System.IO.File]::WriteAllText($script:ConfigPath, $json, $utf8)
}

function Hub-GetRegistryRoot {
    if (-not (Test-Path -LiteralPath $script:RegistryPath)) { return $null }
    return [System.IO.File]::ReadAllText($script:RegistryPath, [System.Text.UTF8Encoding]::new($false)) | ConvertFrom-Json
}

function Hub-SaveRegistryRoot {
    param($RegObj)
    Hub-EnsureHubDataDirs
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $json = ($RegObj | ConvertTo-Json -Depth 40) + "`r`n"
    [System.IO.File]::WriteAllText($script:RegistryPath, $json, $utf8)
    Hub-MirrorCatalogFileToRepo -FullPath $script:RegistryPath
}

function Get-ActiveCatalogJsonPath {
    param([string]$Key)
    if (-not (Test-Path -LiteralPath $script:RegistryPath)) { return $null }
    $reg = Hub-GetRegistryRoot
    if (-not $reg) { return $null }
    $node = $reg.$Key
    if (-not $node) { return $null }
    $ver = [string]$node.active_version
    if ([string]::IsNullOrWhiteSpace($ver)) { return $null }
    return (Join-Path $script:HubCatalogsRoot "$Key\$ver\catalog.json")
}

function Hub-MirrorCatalogFileToRepo {
    param([string]$FullPath)
    if ([string]::IsNullOrWhiteSpace($FullPath)) { return }
    if (-not (Test-Path -LiteralPath $FullPath)) { return }
    if (-not (Test-Path -LiteralPath $script:RepoCompanyCatalogsRoot)) { return }
    $normHub = [System.IO.Path]::GetFullPath($script:HubCatalogsRoot)
    $normFile = [System.IO.Path]::GetFullPath($FullPath)
    if ($normFile.Length -lt $normHub.Length) { return }
    if (-not $normFile.StartsWith($normHub, [System.StringComparison]::OrdinalIgnoreCase)) { return }
    $tail = $normFile.Substring($normHub.Length).TrimStart('\')
    if ([string]::IsNullOrWhiteSpace($tail)) { return }
    $dest = Join-Path $script:RepoCompanyCatalogsRoot $tail
    $destParent = Split-Path -Parent $dest
    if (-not (Test-Path -LiteralPath $destParent)) {
        [void](New-Item -ItemType Directory -Force -Path $destParent)
    }
    Copy-Item -LiteralPath $normFile -Destination $dest -Force
}

function Get-CurrentSchemaPath {
    param([string]$Key)
    $c = $script:Companies.$Key
    if (-not $c) { return $null }
    $name = [string]$c.schema_name + '.json'
    return Join-Path (Join-Path $script:SchemasDir 'current') $name
}

function Hub-GetLastBuildStampText {
    <# Дата «последнего билда»: max(mtime current-схемы, mtime файлов stable\{schema_name}-*.json). #>
    param([string]$CompanyKey)
    if ([string]::IsNullOrWhiteSpace($CompanyKey)) { return $null }
    if ($null -eq $script:Companies) { return $null }
    try { $c = $script:Companies.$CompanyKey } catch { return $null }
    if (-not $c) { return $null }
    $times = New-Object 'System.Collections.Generic.List[datetime]'
    try {
        $pCur = Get-CurrentSchemaPath $CompanyKey
        if ($pCur -and (Test-Path -LiteralPath $pCur)) {
            [void]$times.Add((Get-Item -LiteralPath $pCur).LastWriteTime)
        }
        $sn = [string]$c.schema_name
        if (-not [string]::IsNullOrWhiteSpace($sn)) {
            $sd = Join-Path $script:SchemasDir 'stable'
            if (Test-Path -LiteralPath $sd) {
                foreach ($f in Get-ChildItem -LiteralPath $sd -Filter ($sn + '-*.json') -ErrorAction SilentlyContinue) {
                    [void]$times.Add($f.LastWriteTime)
                }
            }
        }
    } catch { return $null }
    if ($times.Count -eq 0) { return $null }
    $mx = [datetime]::MinValue
    foreach ($tEnt in $times) { if ($tEnt -gt $mx) { $mx = $tEnt } }
    return $mx.ToString('dd.MM.yyyy')
}

function Hub-ResolveCatalogSchemaFileForCompanyScan {
    <# JSON схемы для сверки с глобальными переменными: current → пути из catalog.company. #>
    param([string]$CompanyKey)
    if ([string]::IsNullOrWhiteSpace($CompanyKey)) { return $null }
    $pCur = Get-CurrentSchemaPath $CompanyKey
    if ($pCur -and (Test-Path -LiteralPath $pCur)) { return $pCur }
    if ($null -eq $script:CatalogRootObject) { return $null }
    try {
        if ($script:CatalogRootObject.company -and $script:CatalogRootObject.company.PSObject.Properties['schema_reference']) {
            $ref = [string]$script:CatalogRootObject.company.schema_reference
            if (-not [string]::IsNullOrWhiteSpace($ref)) {
                $candidates = @(
                    (Join-Path $script:RepoRoot $ref),
                    (Join-Path $script:HubDir $ref),
                    $ref
                )
                foreach ($c in $candidates) {
                    if ($c -and (Test-Path -LiteralPath $c)) { return $c }
                }
            }
        }
        if ($script:CatalogRootObject.company -and $script:CatalogRootObject.company.PSObject.Properties['trusted_result_mapping_schema']) {
            $t = [string]$script:CatalogRootObject.company.trusted_result_mapping_schema
            if (-not [string]::IsNullOrWhiteSpace($t) -and (Test-Path -LiteralPath $t)) { return $t }
        }
    } catch { }
    return $null
}

function Hub-ExtractGlobalVariableNamesFromSchemaText {
    <# Имена глобальных переменных в тексте схемы: globalVariables.X, ${global.X}, ${globalVariables.X}. #>
    param([string]$Text)
    $set = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $set }
    $patterns = @(
        '(?i)globalVariables\.([A-Za-z0-9_]+)'
        '(?i)\$\{\s*global\.([A-Za-z0-9_]+)\s*\}'
        '(?i)\$\{\s*globalVariables\.([A-Za-z0-9_]+)\s*\}'
    )
    foreach ($pat in $patterns) {
        foreach ($m in [regex]::Matches($Text, $pat)) {
            if ($m.Success -and $m.Groups.Count -gt 1) {
                $nm = [string]$m.Groups[1].Value
                if (-not [string]::IsNullOrWhiteSpace($nm)) { [void]$set.Add($nm) }
            }
        }
    }
    return $set
}

function Hub-CatalogUpdateGlobalVariableSchemaHighlightState {
    <# Заполняет наборы: ссылки в схеме, загруженные ключи Webitel, отсутствующие в Webitel. #>
    param([string]$CompanyKey)
    $script:CatalogGlobalSchemaRefKeys = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    $script:CatalogGlobalMissingKeysOrdered = @()
    if ([string]::IsNullOrWhiteSpace($CompanyKey) -or $null -eq $script:CatalogRootObject) { return }
    $loaded = New-Object 'System.Collections.Generic.HashSet[string]' ([StringComparer]::OrdinalIgnoreCase)
    try {
        $gv = $script:CatalogRootObject.webitel_global_variables
        if ($null -ne $gv) {
            foreach ($pr in $gv.PSObject.Properties) {
                if ($pr.MemberType -ne 'NoteProperty') { continue }
                [void]$loaded.Add([string]$pr.Name)
            }
        }
    } catch { }
    $schemaPath = Hub-ResolveCatalogSchemaFileForCompanyScan -CompanyKey $CompanyKey
    if ($schemaPath) {
        try {
            $raw = [System.IO.File]::ReadAllText($schemaPath, [System.Text.UTF8Encoding]::new($false))
            foreach ($n in @(Hub-ExtractGlobalVariableNamesFromSchemaText $raw)) {
                [void]$script:CatalogGlobalSchemaRefKeys.Add([string]$n)
            }
        } catch { }
    }
    $miss = New-Object System.Collections.Generic.List[string]
    $refList = New-Object System.Collections.Generic.List[string]
    foreach ($x in $script:CatalogGlobalSchemaRefKeys) { [void]$refList.Add([string]$x) }
    $refList.Sort([StringComparer]::OrdinalIgnoreCase)
    foreach ($n in $refList) {
        if (-not $loaded.Contains([string]$n)) { [void]$miss.Add([string]$n) }
    }
    $script:CatalogGlobalMissingKeysOrdered = @($miss.ToArray())
}

function Invoke-HubPowerShellFile {
    <#
    Запуск дочернего powershell.exe с -File: одна строка аргументов и кавычки вокруг путей,
    иначе WinPS 5.1 Start-Process -ArgumentList @(...) ломает пути с пробелом (например WA bot).
    #>
    param(
        [Parameter(Mandatory)][string]$ScriptPath,
        [Parameter(Mandatory)][string]$WorkingDirectory,
        [System.Collections.IDictionary]$BoundParameters = $null
    )
    function Hub-CliQuote([string]$s) {
        if ($null -eq $s) { $s = '' }
        '"' + ($s -replace '"', '""') + '"'
    }
    $exe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($t in @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', (Hub-CliQuote $ScriptPath))) {
        [void]$parts.Add($t)
    }
    if ($null -ne $BoundParameters) {
        foreach ($kv in $BoundParameters.GetEnumerator()) {
            $flag = '-' + [string]$kv.Key
            [void]$parts.Add($flag)
            [void]$parts.Add((Hub-CliQuote ([string]$kv.Value)))
        }
    }
    $argLine = [string]::Join(' ', $parts)
    return Start-Process -FilePath $exe -ArgumentList $argLine -WorkingDirectory $WorkingDirectory -Wait -PassThru -WindowStyle Hidden
}

function Set-HubExecutionStatus {
    param([ValidateSet('idle','running','success','error')] [string]$State)
    if ($null -eq $script:LblExecStatus -or $null -eq $script:PnlExecStatus) { return }
    switch ($State) {
        'idle' {
            $script:LblExecStatus.Text = 'Готово'
            $script:PnlExecStatus.BackColor = $script:HubUiTrack
            $script:LblExecStatus.ForeColor = $script:HubUiMuted
        }
        'running' {
            $script:LblExecStatus.Text = 'Выполняется…'
            $script:PnlExecStatus.BackColor = [System.Drawing.Color]::FromArgb(254, 243, 199)
            $script:LblExecStatus.ForeColor = [System.Drawing.Color]::FromArgb(120, 53, 15)
        }
        'success' {
            $script:LblExecStatus.Text = 'Успешно'
            $script:PnlExecStatus.BackColor = [System.Drawing.Color]::FromArgb(220, 252, 231)
            $script:LblExecStatus.ForeColor = [System.Drawing.Color]::FromArgb(22, 101, 52)
        }
        'error' {
            $script:LblExecStatus.Text = 'Ошибка'
            $script:PnlExecStatus.BackColor = [System.Drawing.Color]::FromArgb(254, 226, 226)
            $script:LblExecStatus.ForeColor = [System.Drawing.Color]::FromArgb(127, 29, 29)
        }
    }
    [System.Windows.Forms.Application]::DoEvents()
}

function Hub-OpsProgressSetVisible {
    param([bool]$Visible)
    if ($null -eq $script:PrgOpsProgress) { return }
    $script:PrgOpsProgress.Visible = $Visible
    if ($Visible) {
        $script:PrgOpsProgress.Style = [System.Windows.Forms.ProgressBarStyle]::Marquee
        $script:PrgOpsProgress.MarqueeAnimationSpeed = 35
    } else {
        $script:PrgOpsProgress.Style = [System.Windows.Forms.ProgressBarStyle]::Continuous
        $script:PrgOpsProgress.Value = 0
    }
    [void][System.Windows.Forms.Application]::DoEvents()
}

function Hub-OpsSetCommandButtonsEnabled {
    param([bool]$Enabled)
    if ($null -eq $script:OpsCommandButtons) { return }
    foreach ($b in @($script:OpsCommandButtons)) {
        if ($null -ne $b) { $b.Enabled = $Enabled }
    }
}

function Hub-OpsRunConfirmed {
    <# Подтверждение Да/Нет, затем прогресс и выполнение (UI не зависает от Marquee). #>
    param(
        [Parameter(Mandatory)][string]$ConfirmMessage,
        [Parameter(Mandatory)][scriptblock]$Work
    )
    $r = [System.Windows.Forms.MessageBox]::Show(
        $ConfirmMessage,
        $script:HubAppTitle,
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Question)
    if ($r -ne [System.Windows.Forms.DialogResult]::Yes) { return }
    Set-HubExecutionStatus -State running
    $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
    Hub-OpsSetCommandButtonsEnabled $false
    Hub-OpsProgressSetVisible $true
    try {
        & $Work
        Set-HubExecutionStatus -State success
    } catch {
        Append-Log ("ОШИБКА: " + $_.Exception.Message)
        Set-HubExecutionStatus -State error
        [void][System.Windows.Forms.MessageBox]::Show(
            $_.Exception.Message,
            $script:HubAppTitle,
            [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error)
    } finally {
        Hub-OpsProgressSetVisible $false
        $form.Cursor = [System.Windows.Forms.Cursors]::Default
        Hub-OpsSetCommandButtonsEnabled $true
    }
}

function Append-Log {
    param([string]$Text)
    $script:TxtLog.AppendText(("`r`n--- " + (Get-Date -Format 'HH:mm:ss') + " ---`r`n" + $Text + "`r`n"))
    $script:TxtLog.SelectionStart = $script:TxtLog.Text.Length
    $script:TxtLog.ScrollToCaret()
    [System.Windows.Forms.Application]::DoEvents()
}

if (-not (Test-Path -LiteralPath $script:ConfigPath)) {
    [void][System.Windows.Forms.MessageBox]::Show("Не найден deploy-config.json:`n$($script:ConfigPath)", $script:HubAppTitle)
    exit 1
}

Hub-EnsureHubDataDirs
[void](Hub-MigrateCompanyCatalogsFromRepo)
Hub-ReloadDeployConfig

# --- flatten catalog JSON ---
function Split-HubCatalogPath([string]$path) {
    if ([string]::IsNullOrWhiteSpace($path)) { return @() }
    return @([regex]::Matches($path, '[^\.\[\]]+|\[\d+\]') | ForEach-Object { $_.Value })
}

function Test-HubCatalogLeafNode {
    param($Node)
    if ($null -eq $Node) { return $true }
    if ($Node -is [string]) { return $true }
    if ($Node -is [bool]) { return $true }
    if ($Node -is [int] -or $Node -is [long] -or $Node -is [double] -or $Node -is [decimal]) { return $true }
    if ($Node -is [datetime]) { return $true }
    return $false
}

function Format-HubCatalogLeafNode {
    param($Node)
    if ($null -eq $Node) { return 'null' }
    if ($Node -is [bool]) { if ($Node) { return 'true' } else { return 'false' } }
    if ($Node -is [double] -or $Node -is [decimal] -or $Node -is [int] -or $Node -is [long]) {
        return [string]::Format([System.Globalization.CultureInfo]::InvariantCulture, '{0}', $Node)
    }
    return [string]$Node
}

function Get-HubCatalogFlattenRows {
    param($Node, [string]$Prefix)
    $list = New-Object System.Collections.Generic.List[object]
    if (Test-HubCatalogLeafNode -Node $Node) {
        if (-not [string]::IsNullOrWhiteSpace($Prefix)) {
            [void]$list.Add([ordered]@{ Path = $Prefix; Value = (Format-HubCatalogLeafNode $Node) })
        }
        return $list
    }
    if ($Node -is [System.Collections.IList] -and $Node -isnot [string] -and $Node -isnot [char[]]) {
        for ($i = 0; $i -lt $Node.Count; $i++) {
            $el = $Node[$i]
            $nextPrefix = if ($Prefix) { "$Prefix[$i]" } else { "[$i]" }
            foreach ($x in @(Get-HubCatalogFlattenRows -Node $el -Prefix $nextPrefix)) {
                [void]$list.Add($x)
            }
        }
        return $list
    }
    if ($Node -is [hashtable]) {
        foreach ($key in @($Node.Keys | Sort-Object)) {
            $child = $Node[$key]
            $np = if ($Prefix) { "$Prefix.$key" } else { [string]$key }
            foreach ($x in @(Get-HubCatalogFlattenRows -Node $child -Prefix $np)) { [void]$list.Add($x) }
        }
        return $list
    }
    $props = @($Node.PSObject.Properties | Where-Object { $_.MemberType -eq 'NoteProperty' })
    foreach ($prop in $props) {
        $name = $prop.Name
        $child = $prop.Value
        $np = if ($Prefix) { "$Prefix.$name" } else { $name }
        foreach ($x in @(Get-HubCatalogFlattenRows -Node $child -Prefix $np)) { [void]$list.Add($x) }
    }
    return $list
}

function Hub-NavOneStep {
    param($Node, [string]$Token)
    if ($null -eq $Node) { return $null }
    if ($Token -match '^\[(\d+)\]$') {
        return $Node[[int]$Matches[1]]
    }
    if ($Node -is [hashtable]) { return $Node[$Token] }
    return $Node.$Token
}

function Convert-HubCatalogCellToValue {
    param([string]$s)
    if ($null -eq $s) { return $null }
    $t = $s.Trim()
    if ($t -eq '' -or $t -eq 'null') { return $null }
    if ($t -eq 'true') { return $true }
    if ($t -eq 'false') { return $false }
    $ci = [System.Globalization.CultureInfo]::InvariantCulture
    $d = 0.0
    if ([double]::TryParse($t, [System.Globalization.NumberStyles]::Float, $ci, [ref]$d)) { return $d }
    $lg = 0L
    if ([long]::TryParse($t, [ref]$lg)) { return $lg }
    return $s
}

function Set-HubCatalogValueByPath {
    param([object]$Root, [string]$Path, [string]$ValueText)
    $parts = @(Split-HubCatalogPath $Path)
    if ($parts.Count -eq 0) { return }
    $val = Convert-HubCatalogCellToValue $ValueText
    if ($parts.Count -eq 1) {
        $t = $parts[0]
        if ($t -match '^\[(\d+)\]$') { $Root[[int]$Matches[1]] = $val }
        elseif ($Root -is [hashtable]) { $Root[$t] = $val }
        else { $Root.$t = $val }
        return
    }
    $parent = $Root
    for ($i = 0; $i -lt $parts.Count - 1; $i++) {
        $parent = Hub-NavOneStep -Node $parent -Token $parts[$i]
        if ($null -eq $parent) { throw "Путь не найден: $Path (сегмент $($parts[$i]))" }
    }
    $last = $parts[-1]
    if ($last -match '^\[(\d+)\]$') { $parent[[int]$Matches[1]] = $val }
    elseif ($parent -is [hashtable]) { $parent[$last] = $val }
    else { $parent.$last = $val }
}

function Hub-ReadCatalogEditorMetaLookups {
    <# titles/addresses: ключ = JSON-путь к листу, значение = подпись / адрес в схеме (${…}). #>
    param($Root)
    $ts = @{}
    $ad = @{}
    if ($null -eq $Root) { return @{ Titles = $ts; Addrs = $ad } }
    $mk = [string]$script:CatalogEditorMetaKey
    if (-not ($Root.PSObject.Properties[$mk])) { return @{ Titles = $ts; Addrs = $ad } }
    $m = $Root.$mk
    if ($null -eq $m) { return @{ Titles = $ts; Addrs = $ad } }
    if ($m.PSObject.Properties['titles'] -and $null -ne $m.titles) {
        foreach ($pr in $m.titles.PSObject.Properties) {
            if ($pr.MemberType -ne 'NoteProperty') { continue }
            $ts[$pr.Name] = [string]$pr.Value
        }
    }
    if ($m.PSObject.Properties['addresses'] -and $null -ne $m.addresses) {
        foreach ($pr in $m.addresses.PSObject.Properties) {
            if ($pr.MemberType -ne 'NoteProperty') { continue }
            $ad[$pr.Name] = [string]$pr.Value
        }
    }
    return @{ Titles = $ts; Addrs = $ad }
}

function Hub-GetCatalogSuggestSchemaAddress {
    <# Подсказка адреса: id узла из wa_promt_gpt.schema_node + последний сегмент пути в ${…}. #>
    param([string]$Path, $Root)
    if ([string]::IsNullOrWhiteSpace($Path) -or $null -eq $Root) { return '' }
    if ($Path -match '(?i)^webitel_global_variables\.([^.]+)\.value$') {
        return ('globalVariables.' + $Matches[1])
    }
    $nodeId = ''
    try {
        if ($Root.PSObject.Properties['wa_promt_gpt'] -and $Root.wa_promt_gpt) {
            $w = $Root.wa_promt_gpt
            if ($w.PSObject.Properties['schema_node'] -and $null -ne $w.schema_node) {
                $nodeId = [string]$w.schema_node
            }
        }
    } catch { }
    if ([string]::IsNullOrWhiteSpace($nodeId)) { return '' }
    if ($Path -match '(?i)\.export_variables\[(\d+)\]\.(flow_variable|flowVariable)$') {
        $idx = $Matches[1]
        return ('${' + $nodeId + '}.export_variables[' + $idx + ']')
    }
    $leaf = $Path
    if ($leaf -match '\.([^.\[\]]+)$') { $leaf = $Matches[1] }
    elseif ($leaf -match '\[(\d+)\]$') { $leaf = 'item' + $Matches[1] }
    return ('${' + $nodeId + '}.' + $leaf)
}

function Hub-ApplyCatalogEditorMetaToDraft {
    <# Записывает в $Draft объект _hub_editor_meta из CatalogEditRows (подписи и адреса). #>
    param($Draft)
    if ($null -eq $Draft) { return }
    $mk = [string]$script:CatalogEditorMetaKey
    $rows = $script:CatalogEditRows
    if ($null -eq $rows -or $rows.Count -eq 0) {
        $prRm = $Draft.PSObject.Properties[$mk]
        if ($null -ne $prRm) { [void]$Draft.PSObject.Properties.Remove($prRm) }
        return
    }
    $tHash = [ordered]@{}
    $aHash = [ordered]@{}
    foreach ($er in @($rows)) {
        $p = [string]$er.Full
        if ([string]::IsNullOrWhiteSpace($p)) { continue }
        if ($p -match '(?i)^_hub_company(\.|$)') { continue }
        if ($p -match ('^' + [regex]::Escape($mk) + '(\.|$)')) { continue }
        $def = [string]$er.DefaultTit
        $tit = [string]$er.Tit
        $addr = [string]$er.Addr
        $isMrg = $false
        if ($er.PSObject.Properties['IsCrmExportMerged']) { try { $isMrg = [bool]$er.IsCrmExportMerged } catch { $isMrg = $false } }
        if ($isMrg) {
            if (-not [string]::IsNullOrWhiteSpace($addr)) { $aHash[$p] = $addr }
            continue
        }
        if ($tit -ne $def -and -not [string]::IsNullOrWhiteSpace($tit)) { $tHash[$p] = $tit }
        if (-not [string]::IsNullOrWhiteSpace($addr)) { $aHash[$p] = $addr }
    }
    if ($tHash.Count -eq 0 -and $aHash.Count -eq 0) {
        $prRm2 = $Draft.PSObject.Properties[$mk]
        if ($null -ne $prRm2) { [void]$Draft.PSObject.Properties.Remove($prRm2) }
        return
    }
    # WinPS 5.1: Add-Member -NotePropertyName требует -NotePropertyValue, не -Value (иначе сбой параметров / исключения при сохранении).
    $titlesPlain = @{}
    foreach ($k in $tHash.Keys) { $titlesPlain[[string]$k] = [string]$tHash[$k] }
    $addrsPlain = @{}
    foreach ($k in $aHash.Keys) { $addrsPlain[[string]$k] = [string]$aHash[$k] }
    $metaJson = (@{ titles = $titlesPlain; addresses = $addrsPlain } | ConvertTo-Json -Depth 30 -Compress)
    $metaObj = $metaJson | ConvertFrom-Json
    if ($Draft.PSObject.Properties[$mk]) {
        $Draft.$mk = $metaObj
    } else {
        $Draft | Add-Member -MemberType NoteProperty -Name $mk -Value $metaObj
    }
}

function Test-HubCatalogPathIsCrmPhoneLookup([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $false }
    $seg = '(client_lookup_by_phone|clientLookupByPhone)'
    # Корень: crm.<сегмент>…
    if ($Path -match "(?i)^crm\.$seg(\.|$)") { return $true }
    # Вложение: …crm.<сегмент>…
    if ($Path -match "(?i)\.crm\.$seg(\.|$)") { return $true }
    # Любой путь crm.*, где встречается блок lookup по телефону (заголовок уже «CRM: client lookup…»)
    if ($Path -match '(?i)^crm\.') {
        if ($Path -match '(?i)client_lookup_by_phone') { return $true }
        if ($Path -match '(?i)clientLookupByPhone') { return $true }
    }
    return $false
}

function Get-HubCatalogVariableGroup([string]$Path) {
    if ([string]::IsNullOrWhiteSpace($Path)) { return $script:CatalogGroupUngrouped }
    if ($Path -match '(?i)^_hub_company(\.|$)') { return $script:CatalogGroupAboutCompany }
    if ($Path -match '(?i)^catalog_version(\.|$)') { return $script:CatalogGroupAboutCompany }
    if ($Path -match '(?i)^company(\.|$)') { return $script:CatalogGroupAboutCompany }
    if ($Path -match '(?i)^project_index(\.|$)') { return $script:CatalogGroupAboutCompany }
    if (Test-HubCatalogPathIsCrmPhoneLookup $Path) { return $script:CatalogGroupCrmClient }
    if ($Path -match '(?i)^crm\.(result_submit|resultSubmit)(\.|$)') { return $script:CatalogGroupCrmResults }
    if ($Path -match '(?i)\.crm\.(result_submit|resultSubmit)(\.|$)') { return $script:CatalogGroupCrmResults }
    if ($Path -match '(?i)^crm\.') {
        if ($Path -match '(?i)result_submit') { return $script:CatalogGroupCrmResults }
        if ($Path -match '(?i)resultSubmit') { return $script:CatalogGroupCrmResults }
    }
    if ($Path -match '(?i)^(wa_promt_gpt|wa_propt_gpt)(\.|$)') { return $script:CatalogGroupGptMain }
    if ($Path -match '(?i)^openai_style_rules(\.|$)') { return $script:CatalogGroupGptExtra }
    if ($Path -match '(?i)^result_mapping(\.|$)') { return $script:CatalogGroupGptResults }
    if ($Path -match '(?i)^taxonomy(\.|$)') { return $script:CatalogGroupGptFunctions }
    if ($Path -match '(?i)^final_messages(\.|$)') { return $script:CatalogGroupBotFinal }
    if ($Path -match '(?i)^webitel_global_variables(\.|$)') { return $script:CatalogGroupGlobalVars }
    if ($Path -match ('(?i)^' + [regex]::Escape($script:CatalogUiMissingGlobalPathPrefix) + '(\.|$)')) {
        return $script:CatalogGroupGlobalVars
    }
    return $script:CatalogGroupUngrouped
}

function Get-HubCatalogGroupWeight([string]$Group) {
    if ($Group -eq $script:CatalogGroupAboutCompany) { return 0 }
    if ($Group -eq $script:CatalogGroupCrmClient) { return 1 }
    if ($Group -eq $script:CatalogGroupCrmResults) { return 2 }
    if ($Group -eq $script:CatalogGroupGptMain) { return 3 }
    if ($Group -eq $script:CatalogGroupGptExtra) { return 4 }
    if ($Group -eq $script:CatalogGroupGptResults) { return 5 }
    if ($Group -eq $script:CatalogGroupGptFunctions) { return 6 }
    if ($Group -eq $script:CatalogGroupBotFinal) { return 7 }
    if ($Group -eq $script:CatalogGroupGlobalVars) { return 8 }
    if ($Group -eq $script:CatalogGroupUngrouped) { return 99 }
    return 50
}

function Get-HubCatalogFriendlyTitle([string]$Path) {
    $map = @{
        'catalog_version'                          = 'Версия справочника'
        'project_index'                            = 'Индекс проекта (ключ папки)'
        '_hub_company.project_index'               = 'Индекс проекта (companies.json / хаб)'
        '_hub_company.display_name'                = 'Название компании (хаб)'
        '_hub_company.crm_url'                     = 'URL CRM (хаб)'
        '_hub_company.webitel_host'                = 'URL Webitel Engine (хаб)'
        '_hub_company.access_token'                = 'Токен админа Webitel (хаб, превью)'
        'company.display_name'                     = 'Название компании (экран)'
        'company.legal_context'                    = 'Юридический контекст'
        'company.country'                          = 'Страна'
        'company.schema_reference'                 = 'Ссылка на схему'
        'wa_propt_gpt.flow_variable'               = 'Переменная потока (GPT)'
        'wa_propt_gpt.source_file'                 = 'Файл промпта'
        'wa_propt_gpt.encoding'                    = 'Кодировка файла промпта'
        'wa_propt_gpt.schema_node'                 = 'Узел схемы (промпт)'
        'wa_propt_gpt.note'                        = 'Заметка (промпт)'
        'openai_style_rules'                       = 'Правила стиля OpenAI (корень)'
        'crm.client_lookup_by_phone.id'           = 'Id блока lookup'
        'crm.client_lookup_by_phone.method'       = 'HTTP-метод (общий)'
        'crm.client_lookup_by_phone.url_template' = 'Шаблон URL (общий)'
        'crm.clientLookupByPhone.id'              = 'Id блока lookup'
        'crm.clientLookupByPhone.method'          = 'HTTP-метод (общий)'
        'crm.clientLookupByPhone.urlTemplate'     = 'Шаблон URL (общий)'
    }
    if ($map.ContainsKey($Path)) { return $map[$Path] }
    if ($Path -match '(?i)^webitel_global_variables\.([^.]+)\.value$') {
        return ('Глобальная: ' + $Matches[1])
    }
    if ($Path -match '(?i)^webitel_global_variables\.([^.]+)\.id$') {
        return ('Глобальная: ' + $Matches[1] + ' (id Webitel)')
    }
    if ($Path -match '(?i)^webitel_global_variables\.([^.]+)\.encrypt$') {
        return ('Глобальная: ' + $Matches[1] + ' (encrypt)')
    }
    if ($Path -match ('(?i)^' + [regex]::Escape($script:CatalogUiMissingGlobalPathPrefix) + '\.([^.]+)$')) {
        return ('Нет в Webitel: ' + $Matches[1])
    }
    <# До ветки «путь заканчивается на [n]» — иначе для CRM lookup остаётся только последний сегмент без primary/alternate. #>
    if ($Path -match '(?i)^crm\.(client_lookup_by_phone|clientLookupByPhone)(\.(.+))?$') {
        $rest = $Matches[3]
        if ([string]::IsNullOrWhiteSpace($rest)) { return 'Клиент по телефону (корень блока)' }
        return (Get-HubCatalogHumanizePathSuffix $rest)
    }
    if ($Path -match '\[(\d+)\]$') {
        $ix = $Matches[1]
        $base = $Path -replace '\[\d+\]$', ''
        if ($map.ContainsKey($base)) { return ($map[$base] + " [$ix]") }
        if ($base -match '^openai_style_rules\.append_to_developer_message$') {
            return "Правила: доп. текст для developer [$ix]"
        }
        if ($base -match '^openai_style_rules\.') {
            $tail = $base -replace '^openai_style_rules\.', ''
            return (Get-HubCatalogHumanizeSegment $tail) + " [$ix]"
        }
        if ($base -match '\.([^.\[]+)$') {
            return (Get-HubCatalogHumanizeSegment $Matches[1]) + " [$ix]"
        }
    }
    if ($Path -match '^crm\.') {
        $tail = $Path -replace '^crm\.', '' -replace '\.headers\.', ' / заголовок '
        return 'CRM: ' + (Get-HubCatalogHumanizeSegment ($tail -replace '\.', ' / '))
    }
    if ($Path -match '\.([^.\[]+)$') {
        return Get-HubCatalogHumanizeSegment $Matches[1]
    }
    return Get-HubCatalogHumanizeSegment $Path
}

function Get-HubCatalogHumanizeSegment([string]$s) {
    if ([string]::IsNullOrWhiteSpace($s)) { return $s }
    return (($s -replace '_', ' ') -replace '\s+', ' ').Trim()
}

function Get-HubCatalogHumanizePathSuffix([string]$Suffix) {
    <# Человекочитаемый хвост пути: сегменты через « / », индексы [n] сохраняются. #>
    if ([string]::IsNullOrWhiteSpace($Suffix)) { return 'Корень блока' }
    $tok = @(Split-HubCatalogPath $Suffix)
    if ($tok.Count -eq 0) { return (Get-HubCatalogHumanizeSegment $Suffix) }
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($t in $tok) {
        if ($t -match '^\[(\d+)\]$') {
            [void]$parts.Add(('[' + $Matches[1] + ']'))
        } else {
            [void]$parts.Add((Get-HubCatalogHumanizeSegment $t))
        }
    }
    return [string]::Join(' / ', $parts)
}

function Get-HubCatalogVariableDataType {
    param([string]$Path, [string]$ValueText)
    $v = if ($null -eq $ValueText) { '' } else { ([string]$ValueText).Trim() }
    if ($v -eq 'true' -or $v -eq 'false') { return 'Логический' }
    if ($Path -match '(?i)\.(id|schema_id|schemaId|flow_id|flowId|queue_id|queueId|timeout|retries|max_|min_|size|page)$') {
        $lg = 0L
        if ([long]::TryParse($v, [ref]$lg)) { return 'Целое число' }
    }
    $ci = [System.Globalization.CultureInfo]::InvariantCulture
    $d = 0.0
    if ([double]::TryParse($v, [System.Globalization.NumberStyles]::Float, $ci, [ref]$d)) { return 'Число' }
    $lg2 = 0L
    if ([long]::TryParse($v, [ref]$lg2)) { return 'Целое число' }
    if ($v.Length -ge 2 -and (($v.StartsWith('{') -and $v.EndsWith('}')) -or ($v.StartsWith('[') -and $v.EndsWith(']')))) {
        return 'JSON'
    }
    if ($v.Length -gt 240) { return 'Строка (длинная)' }
    return 'Строка'
}

function Get-HubCatalogVariablePresentation([string]$Path) {
    $group = Get-HubCatalogVariableGroup -Path $Path
    $title = Get-HubCatalogFriendlyTitle -Path $Path
    return [pscustomobject]@{ Group = $group; Title = $title; Sort = (Get-HubCatalogGroupWeight $group) }
}

function Hub-WalkCrmBlockForExportVariableMerges {
    <# Под crm.client_lookup_by_phone (или camelCase): все массивы export_variables — по одной строке редактора на элемент. #>
    param(
        $Node,
        [string]$PathPrefix,
        $Root,
        $Look,
        [ref]$MergeOrder
    )
    if ($null -eq $Node) { return }
    if ($Node.PSObject.Properties['export_variables']) {
        $arr = $Node.export_variables
        if ($null -ne $arr -and $arr -is [System.Collections.IList] -and $arr -isnot [string] -and $arr -isnot [char[]]) {
            for ($i = 0; $i -lt $arr.Count; $i++) {
                $it = $arr[$i]
                if ($null -eq $it) { continue }
                $flowLeaf = ''
                $crmLeaf = ''
                if ($it.PSObject.Properties['flow_variable']) { $flowLeaf = 'flow_variable' }
                elseif ($it.PSObject.Properties['flowVariable']) { $flowLeaf = 'flowVariable' }
                if ($it.PSObject.Properties['crm_response_field']) { $crmLeaf = 'crm_response_field' }
                elseif ($it.PSObject.Properties['crmResponseField']) { $crmLeaf = 'crmResponseField' }
                if ([string]::IsNullOrWhiteSpace($flowLeaf) -or [string]::IsNullOrWhiteSpace($crmLeaf)) { continue }
                $fv = [string]$it.$flowLeaf
                $cv = [string]$it.$crmLeaf
                $flowPath = "$PathPrefix.export_variables[$i].$flowLeaf"
                $crmPath = "$PathPrefix.export_variables[$i].$crmLeaf"
                $pres = Get-HubCatalogVariablePresentation -Path $flowPath
                $addr = ''
                if ($null -ne $Look -and $Look.Addrs.ContainsKey($flowPath)) { $addr = [string]$Look.Addrs[$flowPath] }
                if ([string]::IsNullOrWhiteSpace($addr)) {
                    $addr = Hub-GetCatalogSuggestSchemaAddress -Path $flowPath -Root $Root
                }
                $ord = $MergeOrder.Value
                $MergeOrder.Value = $MergeOrder.Value + 1
                [void]$script:CatalogEditRows.Add([pscustomobject]@{
                        SortG             = [int]$pres.Sort
                        SortOrder         = 1000 + $ord
                        Gr                = [string]$pres.Group
                        Tit               = $cv
                        DefaultTit        = $cv
                        Full              = $flowPath
                        Val               = $fv
                        Addr              = $addr
                        IsCrmExportMerged  = $true
                        ExportCrmPath     = $crmPath
                        ExportFlowPath    = $flowPath
                    })
            }
        }
    }
    foreach ($prop in @($Node.PSObject.Properties)) {
        if ($prop.MemberType -ne 'NoteProperty') { continue }
        $name = [string]$prop.Name
        if ($name -eq 'export_variables') { continue }
        $ch = $prop.Value
        if ($null -eq $ch) { continue }
        if ($ch -is [System.Collections.IList] -and $ch -isnot [string] -and $ch -isnot [char[]]) {
            for ($j = 0; $j -lt $ch.Count; $j++) {
                $el = $ch[$j]
                if ($null -eq $el) { continue }
                if ($el -is [string] -or $el -is [double] -or $el -is [int] -or $el -is [long] -or $el -is [bool]) { continue }
                $np = "$PathPrefix.$name[$j]"
                Hub-WalkCrmBlockForExportVariableMerges -Node $el -PathPrefix $np -Root $Root -Look $Look -MergeOrder $MergeOrder
            }
            continue
        }
        if ($ch -is [string] -or $ch -is [double] -or $ch -is [int] -or $ch -is [long] -or $ch -is [bool]) { continue }
        if ($ch -is [hashtable] -or ($null -ne $ch.PSObject)) {
            Hub-WalkCrmBlockForExportVariableMerges -Node $ch -PathPrefix ($PathPrefix + '.' + $name) -Root $Root -Look $Look -MergeOrder $MergeOrder
        }
    }
}

function Hub-AppendCrmPhoneLookupExportMergedRows {
    param($Root, $Look)
    if ($null -eq $Root -or -not ($Root.PSObject.Properties['crm'])) { return }
    $crm = $Root.crm
    $mergeCounter = 0
    $ordRef = [ref]$mergeCounter
    foreach ($seg in @('client_lookup_by_phone', 'clientLookupByPhone')) {
        if (-not ($crm.PSObject.Properties[$seg])) { continue }
        $blk = $crm.$seg
        if ($null -eq $blk) { continue }
        Hub-WalkCrmBlockForExportVariableMerges -Node $blk -PathPrefix "crm.$seg" -Root $Root -Look $Look -MergeOrder $ordRef
    }
}

function Get-HubCatalogGroupLabel {
    param([string]$CatalogPathLine)
    return (Get-HubCatalogVariablePresentation -Path $CatalogPathLine).Group
}

function Set-HubCatalogPillVisual {
    param(
        [Parameter(Mandatory)][System.Windows.Forms.Button]$Button,
        [Parameter(Mandatory)][bool]$Active
    )
    $Button.UseVisualStyleBackColor = $false
    $Button.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $Button.Cursor = [System.Windows.Forms.Cursors]::Hand
    $Button.Font = New-Object System.Drawing.Font('Segoe UI', 9.5, $(if ($Active) { [System.Drawing.FontStyle]::Bold } else { [System.Drawing.FontStyle]::Regular }))
    $Button.AutoSize = $false
    $Button.Padding = New-Object System.Windows.Forms.Padding(12, 6, 12, 6)
    $Button.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 8)
    $Button.MinimumSize = New-Object System.Drawing.Size(44, 32)
    $Button.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
    $Button.UseCompatibleTextRendering = $true
    if ($Active) {
        $Button.BackColor = $script:HubUiNavy
        $Button.ForeColor = [System.Drawing.Color]::White
        $Button.FlatAppearance.BorderSize = 0
        $Button.FlatAppearance.MouseOverBackColor = $script:HubUiNavyHi
        $Button.FlatAppearance.MouseDownBackColor = $script:HubUiNavyPress
    } else {
        $Button.BackColor = $script:HubUiCard
        $Button.ForeColor = $script:HubUiInk
        $Button.FlatAppearance.BorderSize = 1
        $Button.FlatAppearance.BorderColor = $script:HubUiBorder
        $Button.FlatAppearance.MouseOverBackColor = $script:HubUiTrack
        $Button.FlatAppearance.MouseDownBackColor = [System.Drawing.Color]::FromArgb(226, 232, 240)
    }
    # Без Region — иначе при переносе строк / смене размера текст обрезается «пустыми» плашками
    $Button.Region = $null
}

function Hub-CatalogPillClick {
    param([Parameter(Mandatory)][System.Windows.Forms.Button]$Sender)
    $gname = [string]$Sender.Tag
    if ([string]::IsNullOrWhiteSpace($gname)) { return }
    $script:CatalogActiveGroupName = $gname
    $flp = $script:FlpCatalogPills
    if ($null -ne $flp) {
        foreach ($c in $flp.Controls) {
            if ($c -isnot [System.Windows.Forms.Button]) { continue }
            Set-HubCatalogPillVisual -Button ([System.Windows.Forms.Button]$c) -Active ($c.Tag -eq $gname)
        }
    }
    Hub-CatalogApplyGroupFilter
    Hub-CatalogApplyDgvColumnWidths
    Hub-CatalogLayoutPillWidths
    Hub-CatalogUpdateGlobalLoadButtonVisibility
}

function Hub-CatalogLayoutPillWidths {
    <# Вертикальный список групп: ширина по клиенту FLP; высота по TextRenderer (корректнее для кириллицы и GDI+). #>
    $flp = $script:FlpCatalogPills
    if ($null -eq $flp) { return }
    $cw = [int]$flp.ClientSize.Width
    if ($cw -lt 48 -and $null -ne $flp.Parent) {
        $cw = [int][Math]::Max($cw, $flp.Parent.ClientSize.Width - $flp.Margin.Horizontal - 8)
    }
    if ($cw -lt 48 -and $null -ne $script:PnlCatalogGroups) {
        $cw = [int][Math]::Max($cw, $script:PnlCatalogGroups.ClientSize.Width - 24)
    }
    if ($cw -lt 80) { $cw = 200 }
    $pad = $flp.Padding.Left + $flp.Padding.Right + 8
    $w = [Math]::Max(120, $cw - $pad)
    $tf = [System.Windows.Forms.TextFormatFlags]::WordBreak -bor [System.Windows.Forms.TextFormatFlags]::TextBoxControl -bor [System.Windows.Forms.TextFormatFlags]::NoPrefix
    foreach ($c in $flp.Controls) {
        if ($c -isnot [System.Windows.Forms.Button]) { continue }
        $b = [System.Windows.Forms.Button]$c
        $b.AutoSize = $false
        $b.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
        $b.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 8)
        $b.Width = $w
        $innerW = [Math]::Max(48, $w - $b.Padding.Horizontal - 4)
        try {
            $sz = [System.Windows.Forms.TextRenderer]::MeasureText($b.Text, $b.Font, [System.Drawing.Size]::new($innerW, 4000), $tf)
            $b.Height = [Math]::Max(44, $sz.Height + $b.Padding.Vertical + 10)
        } catch {
            $b.Height = 48
        }
        try { $b.Invalidate() } catch { }
    }
}

function Hub-CatalogScheduleRelayout {
    <# После смены вкладки / первой отрисовки ширина FLP часто 0 — пересчёт на следующем кадре. #>
    $hostCtl = $script:FlpCatalogPills
    if ($null -eq $hostCtl) { return }
    $frm = $null
    try { $frm = $hostCtl.FindForm() } catch { }
    if ($null -eq $frm) { return }
    [void]$frm.BeginInvoke([action]{
            try {
                if ($null -ne $script:HubLayoutCatalogTab) { & $script:HubLayoutCatalogTab }
                Hub-CatalogLayoutPillWidths
            } catch { }
        })
}

function Hub-CatalogRefreshGroupList {
    $flp = $script:FlpCatalogPills
    if ($null -eq $flp) { return }
    $flp.SuspendLayout()
    try {
        $flp.Controls.Clear()
        $script:CatalogActiveGroupName = $null
        if ($null -eq $script:CatalogEditRows -or $script:CatalogEditRows.Count -eq 0) { return }
        $names = New-Object 'System.Collections.Generic.HashSet[string]'
        foreach ($row in $script:CatalogEditRows) { [void]$names.Add([string]$row.Gr) }
        $ordered = @(
            $script:CatalogGroupAboutCompany,
            $script:CatalogGroupCrmClient,
            $script:CatalogGroupCrmResults,
            $script:CatalogGroupGptMain,
            $script:CatalogGroupGptExtra,
            $script:CatalogGroupGptResults,
            $script:CatalogGroupGptFunctions,
            $script:CatalogGroupBotFinal,
            $script:CatalogGroupGlobalVars,
            $script:CatalogGroupUngrouped
        )
        $groupsList = New-Object System.Collections.Generic.List[string]
        # «О компании» — всегда первая плашка при открытом справочнике (даже если в JSON нет company).
        [void]$groupsList.Add($script:CatalogGroupAboutCompany)
        foreach ($g in $ordered) {
            if ($g -eq $script:CatalogGroupAboutCompany) { continue }
            if ($names.Contains($g) -or $g -eq $script:CatalogGroupGlobalVars) { [void]$groupsList.Add($g) }
        }
        $rest = New-Object System.Collections.Generic.List[string]
        foreach ($n in $names) {
            if ($n -eq $script:CatalogGroupAboutCompany) { continue }
            if ($ordered -notcontains $n) { [void]$rest.Add($n) }
        }
        foreach ($g in ($rest | Sort-Object { [int](Get-HubCatalogGroupWeight $_) }, { $_ })) { [void]$groupsList.Add($g) }
        $ix = 0
        foreach ($g in $groupsList) {
            $b = New-Object System.Windows.Forms.Button
            $b.Text = $g
            $b.Tag = $g
            Set-HubCatalogPillVisual -Button $b -Active ($ix -eq 0)
            $b.Add_Click({ param($Sender, $Ev) Hub-CatalogPillClick -Sender ([System.Windows.Forms.Button]$Sender) })
            [void]$flp.Controls.Add($b)
            $ix++
        }
        if ($groupsList.Count -gt 0) { $script:CatalogActiveGroupName = [string]$groupsList[0] }
        Hub-CatalogLayoutPillWidths
    } finally {
        $flp.ResumeLayout($true)
        Hub-CatalogUpdateGlobalLoadButtonVisibility
    }
}

function Hub-CatalogApplyDgvColumnWidths {
    <# Колонки: название | значение (Fill) | адрес; скрытый Path не участвует. #>
    $dgv = $script:DgvCatalog
    if ($null -eq $dgv) { return }
    $cT = $dgv.Columns['ColTitle']
    $cV = $dgv.Columns['ColValue']
    $cA = $dgv.Columns['ColAddr']
    if ($null -eq $cT -or $null -eq $cV -or $null -eq $cA) { return }
    $cw = [int]$dgv.ClientSize.Width
    if ($cw -lt 140) { return }
    $minVal = 120
    $minAddr = 100
    $rest = $cw - $minVal - $minAddr - 10
    if ($rest -lt 100) { $rest = [Math]::Max(80, $cw - $minAddr - 20) }
    $titleW = [int][Math]::Max(100, [Math]::Min(280, [Math]::Floor($rest * 0.42)))
    $addrW = [int][Math]::Max($minAddr, [Math]::Min(240, [Math]::Floor($cw * 0.22)))
    if ($titleW + $addrW + $minVal -gt $cw) {
        $s = ($cw - $minVal - 8) / [double][Math]::Max(1, ($titleW + $addrW))
        $titleW = [int][Math]::Max(90, [Math]::Floor($titleW * $s))
        $addrW = [int][Math]::Max(80, [Math]::Floor($addrW * $s))
    }
    $dgv.SuspendLayout()
    try {
        $cT.DisplayIndex = 0
        $cV.DisplayIndex = 1
        $cA.DisplayIndex = 2
        $cV.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::Fill
        $cT.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::None
        $cA.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::None
        $cT.Width = $titleW
        $cA.Width = $addrW
        try { $dgv.HorizontalScrollingOffset = 0 } catch { }
        try { $dgv.FirstDisplayedScrollingColumnIndex = 0 } catch { }
    } finally {
        try { $dgv.ResumeLayout($true) } catch { }
    }
}

function Hub-GetCompanyCrmUrlFromObject {
    param($CompanyObj)
    if ($null -eq $CompanyObj) { return '' }
    foreach ($p in @('crm_url', 'crm_host', 'crmHost', 'crm_api_url', 'crmApiUrl')) {
        if (-not ($CompanyObj.PSObject.Properties[$p])) { continue }
        $v = [string]$CompanyObj.$p
        if (-not [string]::IsNullOrWhiteSpace($v)) { return $v.Trim() }
    }
    return ''
}

function Hub-FormatAdminTokenPreviewForCatalog {
    param([string]$Token)
    $t = if ($null -eq $Token) { '' } else { $Token.Trim() }
    if ($t.Length -eq 0) { return '' }
    if ($t.Length -le 8) { return ('•••• (' + $t.Length.ToString() + ' симв.)') }
    return ($t.Substring(0, 4) + ' … ' + $t.Substring($t.Length - 4) + '  (' + $t.Length.ToString() + ' симв.)')
}

function Hub-AppendHubCompanySyntheticCatalogRows {
    <# Строки только для UI: не пишутся в catalog.json. Группа «О компании». #>
    if ($null -eq $script:CatalogEditRows) { return }
    $key = [string]$script:CatalogContextCompanyKey
    if ([string]::IsNullOrWhiteSpace($key)) { return }
    $c = $null
    try { $c = $script:Companies.$key } catch { }
    if ($null -eq $c) { return }
    $g = $script:CatalogGroupAboutCompany
    $wg = [int](Get-HubCatalogGroupWeight $g)
    $projIx = $key
    if ($c.PSObject.Properties['project_index'] -and -not [string]::IsNullOrWhiteSpace([string]$c.project_index)) {
        $projIx = [string]$c.project_index
    }
    $crm = Hub-GetCompanyCrmUrlFromObject $c
    $wh = ''
    if ($c.PSObject.Properties['webitel_host']) { $wh = [string]$c.webitel_host }
    $tok = ''
    if ($c.PSObject.Properties['access_token']) { $tok = [string]$c.access_token }
    $nm = ''
    if ($c.PSObject.Properties['name']) { $nm = [string]$c.name }
    $defs = @(
        @{ Path = '_hub_company.project_index'; Tit = 'Индекс проекта (companies.json / хаб)'; Val = $projIx }
        @{ Path = '_hub_company.display_name'; Tit = 'Название компании (хаб)'; Val = $nm }
        @{ Path = '_hub_company.crm_url'; Tit = 'URL CRM (хаб)'; Val = $crm }
        @{ Path = '_hub_company.webitel_host'; Tit = 'URL Webitel Engine (хаб)'; Val = $wh }
        @{ Path = '_hub_company.access_token'; Tit = 'Токен админа Webitel (хаб, превью)'; Val = (Hub-FormatAdminTokenPreviewForCatalog $tok) }
    )
    $so = -120
    foreach ($d in $defs) {
        [void]$script:CatalogEditRows.Add([pscustomobject]@{
                SortG                 = $wg
                SortOrder             = $so
                Gr                    = $g
                Tit                   = [string]$d.Tit
                DefaultTit            = [string]$d.Tit
                Full                  = [string]$d.Path
                Val                   = [string]$d.Val
                Addr                  = ''
                IsHubCompanySynthetic = $true
            })
        $so++
    }
}

function Hub-CatalogApplyGroupFilter {
    $dgv = $script:DgvCatalog
    if ($null -eq $dgv) { return }
    $dgv.SuspendLayout()
    $script:CatalogGridSuppressEvents = $true
    try {
        $dgv.Rows.Clear()
        if ($null -eq $script:CatalogEditRows) { return }
        $sel = [string]$script:CatalogActiveGroupName
        if ([string]::IsNullOrWhiteSpace($sel)) { $sel = $script:CatalogGroupUngrouped }
        $miss = $script:CatalogGlobalMissingKeysOrdered
        $wantSynth = ($sel -eq $script:CatalogGroupGlobalVars) -and ($null -ne $miss) -and ($miss.Count -gt 0)
        if ($script:CatalogEditRows.Count -eq 0 -and -not $wantSynth) { return }
        foreach ($item in ($script:CatalogEditRows | Sort-Object SortG, Gr, SortOrder, Full)) {
            if ([string]$item.Gr -ne $sel) { continue }
            [void]$dgv.Rows.Add($item.Tit, $item.Val, $item.Addr, $item.Full)
            try {
                $ix = $dgv.Rows.Count - 1
                if ($ix -ge 0) {
                    $hubSyn = $false
                    if ($item.PSObject.Properties['IsHubCompanySynthetic']) {
                        try { $hubSyn = [bool]$item.IsHubCompanySynthetic } catch { $hubSyn = $false }
                    }
                    if ($hubSyn) { $dgv.Rows[$ix].ReadOnly = $true }
                }
            } catch { }
        }
        if ($wantSynth) {
            $schemaHint = ''
            if (-not [string]::IsNullOrWhiteSpace($script:CatalogContextCompanyKey)) {
                $sp = Hub-ResolveCatalogSchemaFileForCompanyScan -CompanyKey $script:CatalogContextCompanyKey
                if ($sp) { $schemaHint = [System.IO.Path]::GetFileName($sp) }
            }
            $hint = if ([string]::IsNullOrWhiteSpace($schemaHint)) {
                'Есть в текущей схеме (файл не найден — проверьте schemas/current и company.schema_reference), нет среди глобальных Webitel.'
            } else {
                ('Есть в схеме «{0}», нет среди загруженных глобальных Webitel.' -f $schemaHint)
            }
            $pf = $script:CatalogUiMissingGlobalPathPrefix
            foreach ($mk in @($miss)) {
                if ([string]::IsNullOrWhiteSpace($mk)) { continue }
                [void]$dgv.Rows.Add(('Нет в Webitel: ' + $mk), $hint, '', ($pf + '.' + $mk))
            }
        }
    } finally {
        $script:CatalogGridSuppressEvents = $false
        $dgv.ResumeLayout()
    }
}

function Hub-FillCatalogGrid {
    $dgv = $script:DgvCatalog
    if ($null -eq $dgv) { return }
    $dgv.SuspendLayout()
    $script:CatalogGridSuppressEvents = $true
    try {
        $dgv.Rows.Clear()
        $script:CatalogEditRows = New-Object System.Collections.Generic.List[object]
        if ($null -eq $script:CatalogRootObject) {
            $script:CatalogContextCompanyKey = $null
            Hub-CatalogUpdateGlobalVariableSchemaHighlightState -CompanyKey ''
            Hub-CatalogRefreshGroupList
            Hub-CatalogApplyGroupFilter
            Hub-CatalogApplyDgvColumnWidths
            return
        }
        $metaSkip = '^' + [regex]::Escape($script:CatalogEditorMetaKey) + '(\.|$)'
        $look = Hub-ReadCatalogEditorMetaLookups $script:CatalogRootObject
        $rows = Get-HubCatalogFlattenRows -Node $script:CatalogRootObject -Prefix ''
        $crmExportLeafSkip = '(?i)^crm\.(client_lookup_by_phone|clientLookupByPhone)(\.[a-zA-Z0-9_]+)*\.export_variables\[\d+\]\.(flow_variable|crm_response_field|flowVariable|crmResponseField)$'
        foreach ($r in $rows) {
            $p = [string]$r.Path
            if ($p -match $metaSkip) { continue }
            if ($p -match $crmExportLeafSkip) { continue }
            $pres = Get-HubCatalogVariablePresentation -Path $p
            $vStr = [string]$r.Value
            $defTit = [string]$pres.Title
            $tit = $defTit
            if ($look.Titles.ContainsKey($p)) { $tit = [string]$look.Titles[$p] }
            $addr = ''
            if ($look.Addrs.ContainsKey($p)) { $addr = [string]$look.Addrs[$p] }
            if ([string]::IsNullOrWhiteSpace($addr)) {
                $addr = Hub-GetCatalogSuggestSchemaAddress -Path $p -Root $script:CatalogRootObject
            }
            [void]$script:CatalogEditRows.Add([pscustomobject]@{
                    SortG      = [int]$pres.Sort
                    SortOrder  = 0
                    Gr         = [string]$pres.Group
                    Tit        = $tit
                    DefaultTit = $defTit
                    Full       = $p
                    Val        = $vStr
                    Addr       = $addr
                })
        }
        Hub-AppendHubCompanySyntheticCatalogRows
        Hub-AppendCrmPhoneLookupExportMergedRows -Root $script:CatalogRootObject -Look $look
        $sorted = @($script:CatalogEditRows | Sort-Object SortG, Gr, SortOrder, Full)
        $script:CatalogEditRows = New-Object System.Collections.Generic.List[object]
        foreach ($x in $sorted) { [void]$script:CatalogEditRows.Add($x) }
    } finally {
        $script:CatalogGridSuppressEvents = $false
        $dgv.ResumeLayout()
    }
    Hub-CatalogRefreshGroupList
    if (-not [string]::IsNullOrWhiteSpace($script:CatalogContextCompanyKey)) {
        Hub-CatalogUpdateGlobalVariableSchemaHighlightState -CompanyKey $script:CatalogContextCompanyKey
    } else {
        Hub-CatalogUpdateGlobalVariableSchemaHighlightState -CompanyKey ''
    }
    Hub-CatalogApplyGroupFilter
    Hub-CatalogApplyDgvColumnWidths
    Hub-CatalogScheduleRelayout
}

function Hub-CatalogSyncEditRowFromGrid {
    param([int]$RowIndex)
    $dgv = $script:DgvCatalog
    if ($null -eq $dgv -or $null -eq $script:CatalogEditRows) { return }
    if ($RowIndex -lt 0 -or $RowIndex -ge $dgv.Rows.Count) { return }
    $row = $dgv.Rows[$RowIndex]
    if ($row.IsNewRow) { return }
    $pathCell = $row.Cells['ColPath'].Value
    $p = if ($null -eq $pathCell) { '' } else { [string]$pathCell }
    if ([string]::IsNullOrWhiteSpace($p)) { return }
    if ($p -match '(?i)^_hub_company(\.|$)') { return }
    if ($p -match ('^(?i)' + [regex]::Escape($script:CatalogUiMissingGlobalPathPrefix) + '\.')) { return }
    $titCell = $row.Cells['ColTitle'].Value
    $tit = if ($null -eq $titCell) { '' } else { [string]$titCell }
    $valCell = $row.Cells['ColValue'].Value
    $vStr = if ($null -eq $valCell) { '' } else { [string]$valCell }
    $addrCell = $row.Cells['ColAddr'].Value
    $addr = if ($null -eq $addrCell) { '' } else { [string]$addrCell }
    foreach ($er in $script:CatalogEditRows) {
        if ([string]$er.Full -ne $p) { continue }
        if ($er.PSObject.Properties['IsHubCompanySynthetic']) {
            try { if ([bool]$er.IsHubCompanySynthetic) { return } } catch { }
        }
        $er.Tit = $tit
        $er.Val = $vStr
        $er.Addr = $addr
        break
    }
}

function Hub-LoadCatalogEditor {
    $key = Hub-GetCatalogCompanyKeyFromTree
    if ([string]::IsNullOrWhiteSpace($key)) {
        $hint = Hub-GetCatalogSelectionMismatchHint
        if (-not [string]::IsNullOrWhiteSpace($hint)) {
            [void][System.Windows.Forms.MessageBox]::Show($hint, $script:HubAppTitle)
        } else {
            [void][System.Windows.Forms.MessageBox]::Show(
                ('Отметьте галочкой у компании тип бота, к которому привязан справочник (см. data\catalogs\registry.json → catalog_bot_id), ' +
                    'или выберите этот узел в дереве — по нему открывается catalog.json.'),
                $script:HubAppTitle)
        }
        return
    }
    $path = Get-ActiveCatalogJsonPath $key
    if (-not $path -or -not (Test-Path -LiteralPath $path)) {
        [void][System.Windows.Forms.MessageBox]::Show(
            "Не найден catalog.json для $key.`nПроверьте data\catalogs\registry.json в папке хаба и активную версию.",
            $script:HubAppTitle)
        $script:CatalogEditorPath = $null
        $script:CatalogRootObject = $null
        $script:CatalogContextCompanyKey = $null
        Hub-FillCatalogGrid
        return
    }
    $script:CatalogEditorPath = $path
    $raw = [System.IO.File]::ReadAllText($path, [System.Text.UTF8Encoding]::new($false))
    try {
        $script:CatalogRootObject = $raw | ConvertFrom-Json
    } catch {
        $script:CatalogRootObject = $null
        $script:CatalogContextCompanyKey = $null
        $script:LblCatalogPath.Text = $path
        $script:LblCatalogPath.ForeColor = $script:HubUiMuted
        [void][System.Windows.Forms.MessageBox]::Show(
            "Не JSON или ошибка:`n$($_.Exception.Message)",
            $script:HubAppTitle, [System.Windows.Forms.MessageBoxButtons]::OK,
            [System.Windows.Forms.MessageBoxIcon]::Error)
        Hub-FillCatalogGrid
        return
    }
    $bindId = Hub-GetCatalogRequiredBotId $key
    $bindLab = Hub-GetBotChannelLabelForId $bindId
    $script:LblCatalogPath.Text = ($path + [Environment]::NewLine + "Привязка справочника (registry): «$bindLab» (id: $bindId)")
    $script:LblCatalogPath.ForeColor = $script:HubUiInk
    $script:CatalogContextCompanyKey = $key
    Hub-FillCatalogGrid
}

function Hub-SaveCatalogEditor {
    if ([string]::IsNullOrWhiteSpace($script:CatalogEditorPath)) {
        [void][System.Windows.Forms.MessageBox]::Show('Сначала нажмите «Загрузить».', $script:HubAppTitle)
        return
    }
    if ($null -eq $script:CatalogRootObject) {
        [void][System.Windows.Forms.MessageBox]::Show('Нет загруженных данных.', $script:HubAppTitle)
        return
    }
    $dgv = $script:DgvCatalog
    $idxPath = $dgv.Columns['ColPath'].Index
    # Синхронизировать видимые строки грида в CatalogEditRows (подпись/значение/адрес), иначе мета не попадёт в файл.
    if ($null -ne $script:CatalogEditRows) {
        for ($ri = 0; $ri -lt $dgv.Rows.Count; $ri++) {
            Hub-CatalogSyncEditRowFromGrid -RowIndex $ri
        }
    }
    try {
        $draftJson = $script:CatalogRootObject | ConvertTo-Json -Depth 100 -Compress
        $draft = $draftJson | ConvertFrom-Json
        $rowsToSave = $script:CatalogEditRows
        if ($null -eq $rowsToSave -or $rowsToSave.Count -eq 0) {
            foreach ($row in $dgv.Rows) {
                if ($row.IsNewRow) { continue }
                $pCell = $row.Cells[$idxPath].Value
                $p = if ($null -eq $pCell) { '' } else { [string]$pCell }
                if ([string]::IsNullOrWhiteSpace($p)) { continue }
                if ($p -match '(?i)^_hub_company(\.|$)') { continue }
                if ($p -match ('^(?i)' + [regex]::Escape($script:CatalogUiMissingGlobalPathPrefix) + '\.')) { continue }
                $vCell = $row.Cells['ColValue'].Value
                $vStr = if ($null -eq $vCell) { '' } else { [string]$vCell }
                Set-HubCatalogValueByPath -Root $draft -Path $p -ValueText $vStr
            }
        } else {
            foreach ($er in $rowsToSave) {
                $p = [string]$er.Full
                if ([string]::IsNullOrWhiteSpace($p)) { continue }
                if ($p -match '(?i)^_hub_company(\.|$)') { continue }
                if ($er.PSObject.Properties['IsHubCompanySynthetic']) {
                    try { if ([bool]$er.IsHubCompanySynthetic) { continue } } catch { }
                }
                $isMrg = $false
                if ($er.PSObject.Properties['IsCrmExportMerged']) { try { $isMrg = [bool]$er.IsCrmExportMerged } catch { $isMrg = $false } }
                if ($isMrg -and $er.PSObject.Properties['ExportCrmPath']) {
                    $crmP = [string]$er.ExportCrmPath
                    if (-not [string]::IsNullOrWhiteSpace($crmP)) {
                        Set-HubCatalogValueByPath -Root $draft -Path $crmP -ValueText ([string]$er.Tit)
                    }
                    Set-HubCatalogValueByPath -Root $draft -Path $p -ValueText ([string]$er.Val)
                }
                else {
                    Set-HubCatalogValueByPath -Root $draft -Path $p -ValueText ([string]$er.Val)
                }
            }
        }
        Hub-ApplyCatalogEditorMetaToDraft -Draft $draft
        $outText = ($draft | ConvertTo-Json -Depth 100) + "`r`n"
        [System.IO.File]::WriteAllText($script:CatalogEditorPath, $outText, (New-Object System.Text.UTF8Encoding $false))
        Hub-MirrorCatalogFileToRepo -FullPath $script:CatalogEditorPath
        $script:CatalogRootObject = $draft
        Hub-FillCatalogGrid
    } catch {
        [void][System.Windows.Forms.MessageBox]::Show(
            "Не сохранено:`n$($_.Exception.Message)",
            $script:HubAppTitle, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
        return
    }
    [void][System.Windows.Forms.MessageBox]::Show("Запись завершена:`n$($script:CatalogEditorPath)",
        $script:HubAppTitle, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
    if ($null -ne $script:TxtLog) { Append-Log "Справочник сохранён: $($script:CatalogEditorPath)" }
}

function Invoke-FetchAndCurrent {
    param([string]$Key)
    $fetch = Join-Path $script:SchemasDir 'fetch-from-webitel.ps1'
    $p = Invoke-HubPowerShellFile -ScriptPath $fetch -WorkingDirectory $script:SchemasDir -BoundParameters @{
        ProjectIndex = $Key
    }
    if ($p.ExitCode -ne 0) { throw "fetch-from-webitel.ps1 exit $($p.ExitCode)" }
    $c = $script:Companies.$Key
    $slug = ([string]$c.name).ToLower() -replace '[^a-z0-9]', ''
    $testDir = Join-Path $script:SchemasDir 'test'
    $eaPrev = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'SilentlyContinue'
        $latest = Get-ChildItem -Path $testDir -Filter "*$slug*test*.json" -ErrorAction SilentlyContinue |
            Sort-Object LastWriteTime -Descending | Select-Object -First 1
        if (-not $latest) {
            $latest = Get-ChildItem -Path $testDir -Filter '*.json' -ErrorAction SilentlyContinue |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
        }
    } finally {
        $ErrorActionPreference = $eaPrev
    }
    if (-not $latest) { throw "Не найден сохранённый JSON в schemas\test" }
    $dest = Get-CurrentSchemaPath $Key
    Copy-Item -LiteralPath $latest.FullName -Destination $dest -Force
    $d = Get-Date -Format 'yyyy-MM-dd'
    $stableName = [string]$c.schema_name + "-$d.json"
    $stablePath = Join-Path (Join-Path $script:SchemasDir 'stable') $stableName
    Copy-Item -LiteralPath $latest.FullName -Destination $stablePath -Force
    $out = "Fetch OK`nTest: $($latest.Name)`nCurrent: $dest`nStable: $stablePath"
    if ($Key -eq 'CO_' -and (Test-Path -LiteralPath $script:TrustedPath)) {
        $abs = ($dest -replace '\\', '/')
        $raw = [System.IO.File]::ReadAllText($script:TrustedPath, [System.Text.UTF8Encoding]::new($false))
        if ($raw -match '"CO_"\s*:\s*\{') {
            $raw2 = $raw -replace '("result_mapping_schema"\s*:\s*")[^"]*(")', "`$1$abs`$2"
            [System.IO.File]::WriteAllText($script:TrustedPath, $raw2, [System.Text.UTF8Encoding]::new($false))
            Hub-MirrorCatalogFileToRepo -FullPath $script:TrustedPath
            $out += "`ntrusted-sources.json (CO_) → current"
        }
        $coCat = Get-ActiveCatalogJsonPath 'CO_'
        if ($coCat -and (Test-Path -LiteralPath $coCat)) {
            $catRaw = [System.IO.File]::ReadAllText($coCat, [System.Text.UTF8Encoding]::new($false))
            $cat2 = $catRaw -replace '("trusted_result_mapping_schema"\s*:\s*")[^"]*(")', "`$1$abs`$2"
            $cat2 = $cat2 -replace '("schema_file"\s*:\s*")[^"]*(")', "`$1$abs`$2"
            [System.IO.File]::WriteAllText($coCat, $cat2, [System.Text.UTF8Encoding]::new($false))
            Hub-MirrorCatalogFileToRepo -FullPath $coCat
            $out += "`nCO catalog.json → current paths"
        }
    }
    return $out
}

function Invoke-Deploy {
    param([string]$Key)
    $schema = Get-CurrentSchemaPath $Key
    if (-not (Test-Path -LiteralPath $schema)) { throw "Нет файла current: $schema" }
    $deploy = Join-Path $script:SchemasDir 'deploy-to-webitel.ps1'
    $notes = 'Aventus Bot Hub / ' + (Get-Date -Format 'yyyy-MM-dd HH:mm')
    $p = Invoke-HubPowerShellFile -ScriptPath $deploy -WorkingDirectory $script:SchemasDir -BoundParameters @{
        ProjectIndex = $Key
        SchemaFile   = $schema
        Notes        = $notes
    }
    if ($p.ExitCode -ne 0) { throw "deploy exit $($p.ExitCode)" }
    return "Deploy завершён (код $($p.ExitCode))"
}

function Invoke-CatalogChecklist {
    param([string]$Key)
    if (-not (Test-Path -LiteralPath $script:CatalogTools)) { throw "Нет папки: $($script:CatalogTools)" }
    $tmp = [System.IO.Path]::GetTempFileName()
    $hubCatEsc = $script:HubCatalogsRoot -replace '"', '""'
    $pre = "set `"WEBITEL_CATALOG_DATA_ROOT=$hubCatEsc`" && "
    cmd /c "$pre cd /d `"$($script:CatalogTools)`" && node catalog-checklist.mjs `"$Key`" > `"$tmp`" 2>&1"
    $txt = [System.IO.File]::ReadAllText($tmp, [System.Text.UTF8Encoding]::new($false))
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    return $txt
}

function Invoke-ValidateSchema {
    param([string]$Key)
    $schema = Get-CurrentSchemaPath $Key
    if (-not (Test-Path -LiteralPath $schema)) { throw "Нет current: $schema" }
    $val = Join-Path $script:SchemasDir 'validate-schema-connections.ps1'
    $tmp = [System.IO.Path]::GetTempFileName()
    cmd /c "cd /d `"$($script:SchemasDir)`" && powershell -NoProfile -ExecutionPolicy Bypass -File `"$val`" -SchemaFile `"$schema`" -ConnectionIntegrityOnly -CheckDeadCustomModule > `"$tmp`" 2>&1"
    $txt = [System.IO.File]::ReadAllText($tmp, [System.Text.UTF8Encoding]::new($false))
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    return $txt
}

function Invoke-CheckCrm {
    param([string]$Key)
    $schema = Get-CurrentSchemaPath $Key
    if (-not (Test-Path -LiteralPath $schema)) { throw "Нет current: $schema" }
    $chk = Join-Path $script:SchemasDir 'check-crm-phone-fetch.ps1'
    $tmp = [System.IO.Path]::GetTempFileName()
    cmd /c "cd /d `"$($script:SchemasDir)`" && powershell -NoProfile -ExecutionPolicy Bypass -File `"$chk`" -SchemaFile `"$schema`" > `"$tmp`" 2>&1"
    $txt = [System.IO.File]::ReadAllText($tmp, [System.Text.UTF8Encoding]::new($false))
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    return $txt
}

function Invoke-SyncCoMapping {
    $sync = Join-Path $script:CatalogTools 'sync-co-result-mapping-from-schema.mjs'
    if (-not (Test-Path -LiteralPath $sync)) { throw 'Нет sync-co-result-mapping-from-schema.mjs' }
    $tmp = [System.IO.Path]::GetTempFileName()
    $hubCatEsc = $script:HubCatalogsRoot -replace '"', '""'
    $pre = "set `"WEBITEL_CATALOG_DATA_ROOT=$hubCatEsc`" && "
    cmd /c "$pre cd /d `"$($script:CatalogTools)`" && node sync-co-result-mapping-from-schema.mjs > `"$tmp`" 2>&1"
    $txt = [System.IO.File]::ReadAllText($tmp, [System.Text.UTF8Encoding]::new($false))
    Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue
    $coPath = Get-ActiveCatalogJsonPath 'CO_'
    if ($coPath) { Hub-MirrorCatalogFileToRepo -FullPath $coPath }
    return $txt
}

$script:WebitelQueueTypeChatInbound = 6
$script:WebitelQueueTypePredictiveDialer = 5
$script:ChatQueuesLoaded = $false
$script:ChatQueueMeta = @{}
$script:ChatDialogsCache = @()
$script:ChatDialogsRawCache = @()
$script:ChatLastEnrichDetailCalls = 0
$script:ChatInboundQueueAllIds = New-Object 'System.Collections.Generic.HashSet[string]'
$script:ClbChatQueues = $null
$script:ChatQueueOutsideListLabel = '«Вне чат-очереди» — диалоги вне выбранных чат-очередей'
$script:TxtChatPhoneFilter = $null
$script:DgvChatDialogs = $null
$script:RbChatSrcAll = $null
$script:RbChatSrcBot = $null
$script:RbChatSrcAgent = $null
$script:ChatGridSuppressSelectionEvent = $false
$script:ChatTranscriptPendingDisplayRow = -1
$script:PnlChatTranscriptShell = $null
$script:LblChatTranscriptMeta = $null
$script:FlpChatTranscript = $null
$script:FlpChatTranscriptRu = $null
$script:ChatTranscriptSplit = $null

function Hub-ChatTextLooksMostlyCyrillic {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $false }
    $n = [regex]::Matches($Text, '[\u0400-\u04FF]').Count
    return (($n * 2) -ge [Math]::Min($Text.Length, 24))
}

function Hub-ChatTranslateChunkMyMemory {
    <# Бесплатный get MyMemory; несколько langpair. #>
    param([string]$Text, [string]$PreferredPair = '')
    $t = $Text
    if ([string]::IsNullOrWhiteSpace($t)) { return '' }
    if ($t.Length -gt 460) { $t = $t.Substring(0, 460) }
    $pairs = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($PreferredPair)) { [void]$pairs.Add($PreferredPair) }
    foreach ($x in @('es|ru', 'en|ru', 'pt|ru', 'de|ru', 'fr|ru', 'it|ru')) {
        if (-not $pairs.Contains($x)) { [void]$pairs.Add($x) }
    }
    foreach ($lp in $pairs) {
        try {
            $url = 'https://api.mymemory.translated.net/get?q=' + [uri]::EscapeDataString($t) + '&langpair=' + [uri]::EscapeDataString($lp)
            $r = Invoke-RestMethod -Uri $url -Method Get -TimeoutSec 35
            if ($null -eq $r) { continue }
            $st = $r.responseStatus
            if ([string]$st -ne '200') {
                try { if ([int]$st -ne 200) { continue } } catch { continue }
            }
            if ($null -eq $r.responseData) { continue }
            $tr = [string]$r.responseData.translatedText
            if (-not [string]::IsNullOrWhiteSpace($tr)) { return $tr }
        } catch { }
        Start-Sleep -Milliseconds 25
    }
    return $Text
}

function Hub-ChatTranslateBodyMyMemory {
    param([string]$Text)
    if ([string]::IsNullOrWhiteSpace($Text)) { return $Text }
    if (Hub-ChatTextLooksMostlyCyrillic $Text) { return $Text }
    $pref = 'es|ru'
    if ($Text -match '[¿¡ñáéíóúüÑÁÉÍÓÚÜ]') { $pref = 'es|ru' }
    elseif ($Text -match '[ãõçÃÕÇ]') { $pref = 'pt|ru' }
    elseif ($Text -match '\b(the|and|is|you|for|with)\b') { $pref = 'en|ru' }
    $lines = $Text -split "`r?`n", -1
    $sb = New-Object System.Text.StringBuilder
    $first = $true
    foreach ($ln in $lines) {
        if (-not $first) { [void]$sb.AppendLine() }
        $first = $false
        $rest = $ln
        while (-not [string]::IsNullOrWhiteSpace($rest)) {
            $take = [Math]::Min(460, $rest.Length)
            $piece = $rest.Substring(0, $take)
            $rest = if ($rest.Length -gt $take) { $rest.Substring($take) } else { '' }
            [void]$sb.Append((Hub-ChatTranslateChunkMyMemory -Text $piece -PreferredPair $pref))
            if ($rest.Length -gt 0) { Start-Sleep -Milliseconds 30 }
        }
    }
    return $sb.ToString()
}

function Hub-ChatCloneRowsWithRussianBodies {
    param($Rows)
    $out = New-Object System.Collections.Generic.List[object]
    foreach ($row in @($Rows)) {
        if ($null -eq $row) { continue }
        $isRaw = $false
        try { $isRaw = [bool]$row.IsRaw } catch { try { $isRaw = [bool]$row['IsRaw'] } catch { $isRaw = $false } }
        $body = ''
        try { $body = [string]$row.Body } catch { try { $body = [string]$row['Body'] } catch { $body = '' } }
        if (-not $isRaw) {
            $body = Hub-ChatTranslateBodyMyMemory $body
        }
        $isCl = $false
        try { $isCl = [bool]$row.IsClient } catch { try { $isCl = [bool]$row['IsClient'] } catch { $isCl = $false } }
        $who = ''; try { $who = [string]$row.Who } catch { try { $who = [string]$row['Who'] } catch { } }
        $when = ''; try { $when = [string]$row.When } catch { try { $when = [string]$row['When'] } catch { } }
        [void]$out.Add(@{ IsClient = $isCl; Who = $who; When = $when; Body = $body; IsRaw = $isRaw })
    }
    return $out
}

function Hub-WebitelBuildQueryString {
    param([System.Collections.IDictionary]$Query)
    $parts = New-Object System.Collections.Generic.List[string]
    foreach ($ent in $Query.GetEnumerator()) {
        $ek = [string]$ent.Key
        $ev = $ent.Value
        if ($null -eq $ev) { continue }
        if ($ev -is [System.Collections.IList] -and -not ($ev -is [string]) -and -not ($ev -is [char[]])) {
            foreach ($x in $ev) {
                if ($null -eq $x) { continue }
                [void]$parts.Add(("{0}={1}" -f [uri]::EscapeDataString($ek), [uri]::EscapeDataString([string]$x)))
            }
        } else {
            [void]$parts.Add(("{0}={1}" -f [uri]::EscapeDataString($ek), [uri]::EscapeDataString([string]$ev)))
        }
    }
    if ($parts.Count -eq 0) { return '' }
    return '?' + [string]::Join('&', $parts)
}

function Hub-WebitelNormalizeEngineRestHost {
    <# Корень Engine для REST: без пути админки (/system/...), без дублирующего /api в конце (иначе /api/api/... → HTML). #>
    param([string]$HostRaw)
    if ([string]::IsNullOrWhiteSpace($HostRaw)) { return '' }
    $u = $HostRaw.Trim().TrimEnd('/')
    if ($u -notmatch '^https?://') { $u = 'https://' + $u.TrimStart('/') }
    try {
        $uri = [Uri]$u
        $p = ($uri.AbsolutePath -replace '/$', '')
        if ($p.Length -gt 0 -and $p -ne '/') {
            if ($p -notmatch '(?i)^/api(/|$)') {
                $u = ($uri.Scheme + '://' + $uri.Authority).TrimEnd('/')
            }
        }
    } catch { }
    $u = $u.Trim().TrimEnd('/')
    while ($true) {
        $u2 = $u -replace '(?i)/engine/api/v2$', ''
        if ($u2 -ne $u) { $u = $u2.TrimEnd('/'); continue }
        $u2 = $u -replace '(?i)/engine/api$', ''
        if ($u2 -ne $u) { $u = $u2.TrimEnd('/'); continue }
        $u2 = $u -replace '(?i)/api/v2$', ''
        if ($u2 -ne $u) { $u = $u2.TrimEnd('/'); continue }
        $u2 = $u -replace '(?i)/api$', ''
        if ($u2 -ne $u) { $u = $u2.TrimEnd('/'); continue }
        break
    }
    return $u.TrimEnd('/')
}

function Hub-WebitelRestGet {
    param(
        [Parameter(Mandatory)][string]$WebitelHost,
        [Parameter(Mandatory)][string]$AccessToken,
        [Parameter(Mandatory)][string]$RelativeApiPath,
        [System.Collections.IDictionary]$Query = @{}
    )
    $hb = (Hub-WebitelNormalizeEngineRestHost $WebitelHost).TrimEnd('/')
    if ($RelativeApiPath -notmatch '^/') { $RelativeApiPath = '/' + $RelativeApiPath }
    $qs = Hub-WebitelBuildQueryString $Query
    $url = $hb + '/api' + $RelativeApiPath + $qs
    $hdr = @{ 'X-Webitel-Access' = [string]$AccessToken }
    try {
        # Без ContentType на GET: на части хостов Invoke-RestMethod давал сбои привязки типов.
        $r = Invoke-WebRequest -Uri $url -Headers $hdr -Method Get -TimeoutSec 120 -UseBasicParsing -ErrorAction Stop
        $txt = [string]$r.Content
        try {
            if (($r | Get-Member -Name RawContentStream -ErrorAction SilentlyContinue) -and $null -ne $r.RawContentStream) {
                $stm = $r.RawContentStream
                if ($stm.CanSeek) { $stm.Position = 0 }
                $ms = New-Object System.IO.MemoryStream
                try {
                    $stm.CopyTo($ms)
                    $bin = $ms.ToArray()
                    if ($bin.Length -gt 0) { $txt = [System.Text.Encoding]::UTF8.GetString($bin) }
                } finally {
                    $ms.Dispose()
                }
            }
        } catch { }
        if ([string]::IsNullOrWhiteSpace($txt)) { return $null }
        return ($txt | ConvertFrom-Json)
    } catch {
        $msg = $_.Exception.Message
        if ($_.ErrorDetails -and $_.ErrorDetails.Message) {
            $msg = $msg + [Environment]::NewLine + [string]$_.ErrorDetails.Message
        }
        throw $msg
    }
}

function Hub-WebitelCurlGetJson {
    <# GET JSON через curl.exe: URL не нормализует %2F в пути (в отличие от Uri+Invoke-WebRequest). #>
    param(
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][string]$AccessToken
    )
    $curlExe = Join-Path $env:WINDIR 'System32\curl.exe'
    if (-not (Test-Path -LiteralPath $curlExe)) {
        $which = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($null -eq $which) { throw 'Не найден curl.exe (нужен для корректного %2F в пути к dictionaries). Установите Windows curl или обновите ОС.' }
        $curlExe = [string]$which.Source
    }
    $tmpOut = [System.IO.Path]::GetTempFileName()
    $tmpErr = [System.IO.Path]::GetTempFileName()
    try {
        & $curlExe @(
            '-sS', '-f', '-g', '--http1.1', '--compressed',
            '--url', $Url,
            '-H', ('X-Webitel-Access: ' + $AccessToken),
            '-H', 'Accept: application/json',
            '-o', $tmpOut
        ) 2>$tmpErr
        if ($LASTEXITCODE -ne 0) {
            $err = ''
            try { $err = ([System.IO.File]::ReadAllText($tmpErr, [System.Text.UTF8Encoding]::new($false))).Trim() } catch { }
            if ([string]::IsNullOrWhiteSpace($err)) {
                try {
                    $bodyErr = ([System.IO.File]::ReadAllText($tmpOut, [System.Text.UTF8Encoding]::new($false))).Trim()
                    if (-not [string]::IsNullOrWhiteSpace($bodyErr)) { $err = $bodyErr }
                } catch { }
            }
            if ([string]::IsNullOrWhiteSpace($err)) { $err = ('curl HTTP error, exit ' + [string]$LASTEXITCODE) }
            throw $err
        }
        $txt = [System.IO.File]::ReadAllText($tmpOut, [System.Text.UTF8Encoding]::new($false))
        if ([string]::IsNullOrWhiteSpace($txt)) { return $null }
        $txt = $txt.Trim()
        if ($txt.Length -ge 1 -and $txt[0] -eq [char]0xFEFF) { $txt = $txt.TrimStart([char]0xFEFF).Trim() }
        if ([string]::IsNullOrWhiteSpace($txt)) { return $null }
        $lead = $txt.TrimStart()
        if ($lead.Length -ge 1 -and $lead[0] -eq '<') {
            $sn = if ($txt.Length -gt 160) { $txt.Substring(0, 160) + '…' } else { $txt }
            throw ('Ответ не JSON (похоже на HTML/XML). Проверьте webitel_host и токен. Фрагмент: ' + $sn)
        }
        try {
            return ($txt | ConvertFrom-Json)
        } catch {
            $sn = if ($txt.Length -gt 200) { $txt.Substring(0, 200) + '…' } else { $txt }
            throw ('Парсинг JSON: ' + $_.Exception.Message + ' | Фрагмент тела: ' + $sn)
        }
    } finally {
        Remove-Item -LiteralPath $tmpOut -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $tmpErr -Force -ErrorAction SilentlyContinue
    }
}

function Hub-WebitelGlobalVariablesProbeLooksLikePagedList {
    <# Ответ похож на список сущностей Engine (очереди, записи словаря): items/data/list; пустой items — валидно. #>
    param($Obj)
    if ($null -eq $Obj) { return $false }
    if ($Obj -is [string] -or $Obj -is [bool] -or $Obj -is [int] -or $Obj -is [long] -or $Obj -is [double] -or $Obj -is [decimal]) { return $false }
    if ($Obj -is [System.Collections.IList] -and -not ($Obj -is [string]) -and -not ($Obj -is [char[]])) {
        if ($Obj.Count -eq 0) { return $true }
        $e0 = $Obj[0]
        return ($e0 -is [pscustomobject] -or $e0 -is [hashtable])
    }
    if (-not ($Obj -is [pscustomobject])) { return $false }
    if ($Obj.PSObject.Properties['items']) { return $true }
    if ($Obj.PSObject.Properties['data'] -and $null -ne $Obj.data) {
        $d = $Obj.data
        if ($d -is [System.Collections.IList]) { return $true }
        if ($d -is [pscustomobject] -and $d.PSObject.Properties['items']) { return $true }
    }
    foreach ($n in @('list', 'result', '_embedded')) {
        if ($Obj.PSObject.Properties[$n]) { return $true }
    }
    return $false
}

function Hub-WebitelDetectEngineRestApiPrefix {
    <# Какой префикс даёт JSON для call_center/queues — тот же нужен для dictionaries (на части облаков /api отдаёт SPA, а /api/v2 — API). #>
    param(
        [Parameter(Mandatory)][string]$WebitelHost,
        [Parameter(Mandatory)][string]$AccessToken
    )
    $hb = (Hub-WebitelNormalizeEngineRestHost $WebitelHost).TrimEnd('/')
    if ([string]::IsNullOrWhiteSpace($hb)) { return '/api' }
    foreach ($px in @('/api/v2', '/api', '/engine/api/v2', '/engine/api')) {
        $apiPx = $px.Trim().TrimEnd('/')
        if ($apiPx -notmatch '^/') { $apiPx = '/' + $apiPx }
        $u = $hb + $apiPx + '/call_center/queues?page=1&size=1'
        try {
            $j = Hub-WebitelCurlGetJson -Url $u -AccessToken $AccessToken
            if ($null -eq $j) { continue }
            if (Hub-WebitelGlobalVariablesProbeLooksLikePagedList $j) { return $apiPx }
        } catch { }
    }
    return '/api'
}

function Hub-WebitelGlobalVariablesApiPrefixCandidates {
    <# База пути к REST; первым идёт префикс, на котором уже отвечает JSON /call_center/queues. #>
    param(
        [Parameter(Mandatory)][string]$WebitelHost,
        [string]$PreferredPrefix = ''
    )
    $hb = $WebitelHost.TrimEnd('/')
    $order = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($PreferredPrefix)) {
        $pf = $PreferredPrefix.Trim().TrimEnd('/')
        if ($pf -notmatch '^/') { $pf = '/' + $pf }
        [void]$order.Add($pf)
    }
    if ($hb -match '(?i)/engine$') {
        foreach ($x in @('/api', '/api/v2')) { [void]$order.Add($x) }
    } else {
        foreach ($x in @('/api/v2', '/api', '/engine/api/v2', '/engine/api')) { [void]$order.Add($x) }
    }
    $seen = @{}
    $out = New-Object System.Collections.Generic.List[string]
    foreach ($x in $order) {
        if ([string]::IsNullOrWhiteSpace($x)) { continue }
        $n = $x.Trim().TrimEnd('/')
        if ($n -notmatch '^/') { $n = '/' + $n }
        if ($seen.ContainsKey($n)) { continue }
        $seen[$n] = $true
        [void]$out.Add($n)
    }
    return @($out.ToArray())
}

function Hub-WebitelResolveGlobalVariablesApiPath {
    <# Подбирает рабочий префикс (/api или /engine/api) и путь .../dictionaries/... для списка глобальных переменных. #>
    param(
        [Parameter(Mandatory)][string]$WebitelHost,
        [Parameter(Mandatory)][string]$AccessToken
    )
    $hb = (Hub-WebitelNormalizeEngineRestHost $WebitelHost).TrimEnd('/')
    if ([string]::IsNullOrWhiteSpace($hb)) {
        throw 'Пустой webitel_host после нормализации (нужен корень вида https://домен без пути /system/...).'
    }
    $preferredPx = Hub-WebitelDetectEngineRestApiPrefix -WebitelHost $WebitelHost -AccessToken $AccessToken
    $apiPrefixes = @(Hub-WebitelGlobalVariablesApiPrefixCandidates -WebitelHost $WebitelHost -PreferredPrefix $preferredPx)
    $enc = [uri]::EscapeDataString($script:WebitelGlobalVariablesDatasetId)
    $probeQs = Hub-WebitelBuildQueryString @{ page = 1; size = 1; sort = 'name' }
    $candidates = @(
        ('/dictionaries/' + $enc),
        '/dictionaries/system/globalVariables',
        ('/storage/dictionaries/' + $enc),
        '/storage/dictionaries/system/globalVariables',
        ('/custom/dictionaries/' + $enc),
        '/custom/dictionaries/system/globalVariables'
    )
    $lastErr = ''
    foreach ($apiPx in $apiPrefixes) {
        if ($apiPx -notmatch '^/') { $apiPx = '/' + $apiPx }
        $apiPx = $apiPx.TrimEnd('/')
        foreach ($rel in $candidates) {
            if ($rel -notmatch '^/') { $rel = '/' + $rel }
            $u = $hb + $apiPx + $rel + $probeQs
            try {
                $probe = Hub-WebitelCurlGetJson -Url $u -AccessToken $AccessToken
                if ($null -eq $probe) { continue }
                if (-not (Hub-WebitelGlobalVariablesProbeLooksLikePagedList $probe)) {
                    $lastErr = ('Ответ не похож на список словаря для URL: ' + $u)
                    continue
                }
                return [pscustomobject]@{ ApiPrefix = $apiPx; Path = $rel; FlatQuery = $null }
            } catch {
                $lastErr = [string]$_.Exception.Message
            }
        }
    }
    $flatTries = @(
        @{ path = $script:WebitelGlobalVariablesDatasetId },
        @{ id = $script:WebitelGlobalVariablesDatasetId },
        @{ dictionaryPath = $script:WebitelGlobalVariablesDatasetId },
        @{ dictionary_id = $script:WebitelGlobalVariablesDatasetId },
        @{ repository = 'system'; name = 'globalVariables' }
    )
    foreach ($apiPx in $apiPrefixes) {
        if ($apiPx -notmatch '^/') { $apiPx = '/' + $apiPx }
        $apiPx = $apiPx.TrimEnd('/')
        foreach ($fq in $flatTries) {
            $q = [ordered]@{ page = 1; size = 1; sort = 'name' }
            foreach ($k in $fq.Keys) { $q[$k] = $fq[$k] }
            $uFlat = $hb + $apiPx + '/dictionaries' + (Hub-WebitelBuildQueryString $q)
            try {
                $probe = Hub-WebitelCurlGetJson -Url $uFlat -AccessToken $AccessToken
                if ($null -eq $probe) { continue }
                if (-not (Hub-WebitelGlobalVariablesProbeLooksLikePagedList $probe)) {
                    $lastErr = ('Ответ не похож на список словаря для URL: ' + $uFlat)
                    continue
                }
                return [pscustomobject]@{ ApiPrefix = $apiPx; Path = '/dictionaries'; FlatQuery = $fq }
            } catch {
                $lastErr = [string]$_.Exception.Message
            }
        }
    }
    throw ('Не удалось подобрать URL глобальных переменных Webitel. Последняя ошибка: ' + $lastErr)
}

function Hub-SanitizeWebitelGlobalVariableKey {
    param([string]$Raw)
    if ([string]::IsNullOrWhiteSpace($Raw)) { return 'unnamed' }
    $s = ($Raw.Trim() -replace '[^a-zA-Z0-9_]', '_')
    if ([string]::IsNullOrWhiteSpace($s)) { return 'unnamed' }
    return $s
}

function Hub-WebitelGlobalVariablesExtractItems {
    param($Resp)
    if ($null -eq $Resp) { return @() }
    if ($Resp.PSObject.Properties['items'] -and $null -ne $Resp.items) { return @($Resp.items) }
    if ($Resp.PSObject.Properties['data'] -and $null -ne $Resp.data) {
        $d = $Resp.data
        if ($d.PSObject.Properties['items'] -and $null -ne $d.items) { return @($d.items) }
        if ($d -is [System.Collections.IList]) { return @($d) }
    }
    return @()
}

function Hub-WebitelGlobalVariableItemName {
    param($It)
    if ($null -eq $It) { return '' }
    foreach ($prop in @('name', 'key', 'variable')) {
        if ($It.PSObject.Properties[$prop] -and $null -ne $It.$prop) {
            $s = ([string]$It.$prop).Trim()
            if (-not [string]::IsNullOrWhiteSpace($s)) { return $s }
        }
    }
    return ''
}

function Hub-WebitelGlobalVariableItemEncrypt {
    param($It)
    if ($null -eq $It) { return $false }
    foreach ($prop in @('encrypt', 'encrypted', 'isEncrypted')) {
        if (-not ($It.PSObject.Properties[$prop])) { continue }
        $v = $It.$prop
        if ($v -is [bool]) { return $v }
        $t = ([string]$v).Trim().ToLowerInvariant()
        if ($t -eq 'true' -or $t -eq '1' -or $t -eq 'yes') { return $true }
    }
    return $false
}

function Hub-FetchWebitelGlobalVariablesAll {
    <# GET списка глобальных переменных: curl + подбор пути (system%2FglobalVariables или вложенный /system/globalVariables). #>
    param(
        [Parameter(Mandatory)][string]$WebitelHost,
        [Parameter(Mandatory)][string]$AccessToken
    )
    $hb = (Hub-WebitelNormalizeEngineRestHost $WebitelHost).TrimEnd('/')
    $resolved = Hub-WebitelResolveGlobalVariablesApiPath -WebitelHost $WebitelHost -AccessToken $AccessToken
    $apiPx = '/api'
    if ($resolved.PSObject.Properties['ApiPrefix'] -and -not [string]::IsNullOrWhiteSpace([string]$resolved.ApiPrefix)) {
        $apiPx = [string]$resolved.ApiPrefix
    }
    if ($null -ne $script:TxtLog) {
        Append-Log ('Webitel globals API: prefix «{0}» path «{1}»{2}' -f $apiPx, $resolved.Path, $(if ($null -ne $resolved.FlatQuery) { ' (query ' + ($resolved.FlatQuery | ConvertTo-Json -Compress) + ')' } else { '' }))
    }
    $all = New-Object System.Collections.ArrayList
    $page = 1
    $size = 200
    while ($page -le 200) {
        $q = [ordered]@{ page = $page; size = $size; sort = 'name' }
        if ($null -ne $resolved.FlatQuery) {
            foreach ($k in $resolved.FlatQuery.Keys) { $q[$k] = $resolved.FlatQuery[$k] }
        }
        $qs = Hub-WebitelBuildQueryString $q
        $u = $hb + $apiPx + $resolved.Path + $qs
        $resp = Hub-WebitelCurlGetJson -Url $u -AccessToken $AccessToken
        $chunk = @(Hub-WebitelGlobalVariablesExtractItems $resp)
        foreach ($it in $chunk) { if ($null -ne $it) { [void]$all.Add($it) } }
        $hasNext = $false
        if ($null -ne $resp -and $resp.PSObject.Properties['next'] -and $resp.next) { $hasNext = $true }
        if ($null -ne $resp -and $resp.PSObject.Properties['data']) {
            $dN = $resp.data
            if ($null -ne $dN -and $dN.PSObject.Properties['next'] -and $dN.next) { $hasNext = $true }
        }
        if (-not $hasNext -and $chunk.Count -lt $size) { break }
        if ($chunk.Count -eq 0) { break }
        $page++
    }
    return @($all.ToArray())
}

function Hub-LoadWebitelGlobalVariablesIntoCatalog {
    if ([string]::IsNullOrWhiteSpace($script:CatalogEditorPath)) {
        [void][System.Windows.Forms.MessageBox]::Show('Сначала нажмите «Загрузить» для справочника компании.', $script:HubAppTitle)
        return
    }
    if ($null -eq $script:CatalogRootObject) {
        [void][System.Windows.Forms.MessageBox]::Show('Нет загруженных данных справочника.', $script:HubAppTitle)
        return
    }
    $key = Hub-GetCatalogCompanyKeyFromTree
    if ([string]::IsNullOrWhiteSpace($key)) {
        [void][System.Windows.Forms.MessageBox]::Show(
            'Выберите в дереве компанию с привязанным catalog.json (как для «Загрузить»).',
            $script:HubAppTitle)
        return
    }
    $script:CatalogContextCompanyKey = $key
    $c = $script:Companies.$key
    if (-not $c) {
        [void][System.Windows.Forms.MessageBox]::Show("Нет конфигурации компании: $key", $script:HubAppTitle)
        return
    }
    $hostB = [string]$c.webitel_host
    $tok = [string]$c.access_token
    if ([string]::IsNullOrWhiteSpace($hostB) -or $hostB -match '^PASTE_') {
        [void][System.Windows.Forms.MessageBox]::Show('У компании не задан webitel_host.', $script:HubAppTitle)
        return
    }
    if ([string]::IsNullOrWhiteSpace($tok) -or $tok -match '^PASTE_') {
        [void][System.Windows.Forms.MessageBox]::Show('У компании не задан access_token.', $script:HubAppTitle)
        return
    }
    $hostApi = Hub-WebitelNormalizeEngineRestHost $hostB
    if ([string]::IsNullOrWhiteSpace($hostApi)) {
        [void][System.Windows.Forms.MessageBox]::Show('Не удалось разобрать webitel_host как URL.', $script:HubAppTitle)
        return
    }
    $prevCur = $null
    try {
        if ($null -ne $form) {
            $prevCur = $form.Cursor
            $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
        }
        $items = Hub-FetchWebitelGlobalVariablesAll -WebitelHost $hostApi -AccessToken $tok
        $bucket = [ordered]@{}
        foreach ($it in $items) {
            $rawName = Hub-WebitelGlobalVariableItemName $it
            if ([string]::IsNullOrWhiteSpace($rawName)) {
                if ($it.PSObject.Properties['id'] -and $null -ne $it.id) {
                    $rawName = 'id_' + [string]$it.id
                } else {
                    continue
                }
            }
            $baseK = Hub-SanitizeWebitelGlobalVariableKey $rawName
            $k = $baseK
            $suffix = 1
            while ($bucket.Contains($k)) {
                $k = $baseK + '_' + [string]$suffix
                $suffix++
            }
            $enc = Hub-WebitelGlobalVariableItemEncrypt $it
            $idStr = ''
            if ($it.PSObject.Properties['id'] -and $null -ne $it.id) { $idStr = [string]$it.id }
            $valStr = ''
            if (-not $enc -and $it.PSObject.Properties['value'] -and $null -ne $it.value) {
                $valStr = [string]$it.value
            }
            $bucket[$k] = [pscustomobject]@{ id = $idStr; value = $valStr; encrypt = [bool]$enc }
        }
        $gvObj = [pscustomobject]$bucket
        $script:CatalogRootObject | Add-Member -MemberType NoteProperty -Name 'webitel_global_variables' -Value $gvObj -Force
        Hub-FillCatalogGrid
        foreach ($ctl in $script:FlpCatalogPills.Controls) {
            if ($ctl -isnot [System.Windows.Forms.Button]) { continue }
            if ([string]$ctl.Tag -eq $script:CatalogGroupGlobalVars) {
                Hub-CatalogPillClick -Sender ([System.Windows.Forms.Button]$ctl)
                break
            }
        }
        if ($null -ne $script:TxtLog) {
            Append-Log ("Глобальные переменные Webitel: загружено {0} шт. с {1} (компания {2})." -f $bucket.Keys.Count, $hostApi, $key)
        }
        [void][System.Windows.Forms.MessageBox]::Show(
            ("Загружено глобальных переменных: {0}.`nAPI: {1}`nСохраните справочник, если нужно записать в catalog.json." -f $bucket.Keys.Count, $hostApi),
            $script:HubAppTitle, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Information)
    } catch {
        [void][System.Windows.Forms.MessageBox]::Show(
            ("Не удалось загрузить глобальные переменные:`n{0}" -f $_.Exception.Message),
            $script:HubAppTitle, [System.Windows.Forms.MessageBoxButtons]::OK, [System.Windows.Forms.MessageBoxIcon]::Error)
    } finally {
        if ($null -ne $form -and $null -ne $prevCur) { $form.Cursor = $prevCur }
    }
}

function Hub-CatalogUpdateGlobalLoadButtonVisibility {
    $pnl = $script:PnlCatalogGlobalActions
    if ($null -eq $pnl) { return }
    $pnl.Visible = ($script:CatalogActiveGroupName -eq $script:CatalogGroupGlobalVars)
}

function Hub-ChatUtcToUnixMs {
    param([datetime]$UtcMoment)
    $epochTicks = [long]621355968000000000
    $u = $UtcMoment
    if ($u.Kind -eq [DateTimeKind]::Unspecified) {
        $u = [datetime]::SpecifyKind($u, [DateTimeKind]::Utc)
    } elseif ($u.Kind -eq [DateTimeKind]::Local) {
        $u = $u.ToUniversalTime()
    }
    return [long](($u.Ticks - $epochTicks) / 10000L)
}

function Hub-ChatPeriodModeChanged {
    if ($null -eq $script:RbChatDays) { return }
    $d = $script:RbChatDays.Checked
    if ($null -ne $script:NumChatDays) { $script:NumChatDays.Enabled = $d }
    if ($null -ne $script:DtpChatFrom) { $script:DtpChatFrom.Enabled = -not $d }
    if ($null -ne $script:DtpChatTo) { $script:DtpChatTo.Enabled = -not $d }
    if ($null -ne $script:TabMain -and $script:TabMain.SelectedTab -eq $script:TpChats) {
        Hub-ChatRefreshChatsSectionFromArchive
    }
}

function Hub-ChatRefreshChatsSectionFromArchive {
    if ($null -eq $script:TabMain -or $script:TabMain.SelectedTab -ne $script:TpChats) { return }
    $key = Hub-GetFirstSelectedCompanyKey
    if (-not $key) {
        $script:ChatQueuesLoaded = $false
        $script:ChatCompanyKey = $null
        if ($null -ne $script:LblChatCompany) {
            $script:LblChatCompany.Text = 'Компания: в дереве слева выберите или отметьте бота (лист), чтобы видеть чаты из архива по этой компании.'
        }
        $script:ChatDialogsRawCache = @()
        $script:ChatDialogsCache = @()
        if ($null -ne $script:DgvChatDialogs) { $script:DgvChatDialogs.Rows.Clear() }
        Hub-ChatClearTranscriptUi
        return
    }
    $prevCur = $null
    try {
        if ($null -ne $form) {
            $prevCur = $form.Cursor
            $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
        }
        if (-not ($script:ChatQueuesLoaded -and $script:ChatCompanyKey -eq $key)) {
            [void](Hub-ChatLoadQueuesForCompanyKey -Key $key -Quiet)
        }
        $store = Hub-ChatArchiveLoadStore -Key $key
        $all = @()
        if ($null -ne $store -and $store.PSObject.Properties['dialogs'] -and $null -ne $store.dialogs) {
            $all = @($store.dialogs)
        }
        $dr = Hub-ChatComputeDateRangeMs
        $sinceMs = [long]$dr.SinceMs
        $untilMs = [long]$dr.UntilMs
        $filtered = New-Object System.Collections.ArrayList
        foreach ($dlg in $all) {
            if ($null -eq $dlg) { continue }
            $dtu = Hub-ChatTryParseDialogDateUtc $dlg
            $include = $false
            if ($null -eq $dtu) {
                $include = $true
            } else {
                try {
                    $ms = Hub-ChatUtcToUnixMs $dtu
                    if ($ms -ge $sinceMs -and $ms -le $untilMs) { $include = $true }
                } catch { $include = $true }
            }
            if ($include) { [void]$filtered.Add($dlg) }
        }
        $merged = @(
            $filtered.ToArray() | Sort-Object -Property @{
                Expression = {
                    $u = Hub-ChatTryParseDialogDateUtc $_
                    if ($null -eq $u) { return [long]0 }
                    try { return [long](Hub-ChatUtcToUnixMs $u) } catch { return [long]0 }
                }
            } -Descending
        )
        # Список /chat/dialogs часто без member.communications — догружаем карточку GET /chat/dialogs/{id} (лимит запросов).
        $enriched = $merged
        if (@($merged).Count -gt 0) {
            try {
                $c0 = $script:Companies.$key
                if ($null -ne $c0) {
                    $hB0 = [string]$c0.webitel_host
                    $tk0 = [string]$c0.access_token
                    if (-not [string]::IsNullOrWhiteSpace($hB0) -and $hB0 -notmatch '^PASTE_' -and
                        -not [string]::IsNullOrWhiteSpace($tk0) -and $tk0 -notmatch '^PASTE_') {
                        $uiCap = [Math]::Min(120, [Math]::Max(1, @($merged).Count))
                        $enriched = @(Hub-ChatEnrichDialogsWithDetailIfMissingPhone -Dialogs $merged -WebitelHost $hB0 -AccessToken $tk0 -MaxDetails $uiCap)
                    }
                }
            } catch {
                if ($null -ne $script:TxtLog) { Append-Log ('Чаты: догрузка номеров (GET dialog): ' + $_.Exception.Message) }
            }
        }
        $script:ChatDialogsRawCache = @($enriched)
        if ($script:ChatLastEnrichDetailCalls -gt 0) {
            try {
                Hub-ChatArchiveUpsertDialogsFromEnriched -Key $key -Enriched $enriched
            } catch {
                if ($null -ne $script:TxtLog) { Append-Log ('Чаты: запись обогащённых диалогов в архив: ' + $_.Exception.Message) }
            }
        }
        $script:ChatDialogsCache = @(Hub-ChatFilterDialogsByQueueSelection -Dialogs $script:ChatDialogsRawCache)
        Hub-ChatPopulateDialogsGrid
        if ($null -ne $script:TxtLog) {
            $rawN = @($script:ChatDialogsRawCache).Count
            $fltN = @($script:ChatDialogsCache).Count
            Append-Log ("Чаты: архив всего диалогов в файле: " + $all.Count + "; за период (дата): " + $rawN + "; после фильтра очередей: " + $fltN + ".")
            if ($rawN -gt 0 -and $fltN -eq 0) {
                Append-Log 'Чаты: за период есть диалоги, но фильтр по отмеченным очередям никого не пропустил (сверьте queue_id в JSON архива с id очередей).'
            }
        }
    } catch {
        if ($null -ne $script:TxtLog) { Append-Log ("Чаты (архив): " + $_.Exception.Message) }
    } finally {
        if ($null -ne $form -and $null -ne $prevCur) {
            $form.Cursor = $prevCur
        } elseif ($null -ne $form) {
            $form.Cursor = [System.Windows.Forms.Cursors]::Default
        }
    }
}

function Hub-HubSidebarRefreshClick {
    if ($null -eq $form) { return }
    $prevCur = $form.Cursor
    try {
        $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
        Hub-ReloadDeployConfig
        Hub-RefreshCompanyTree
        $script:ChatQueuesLoaded = $false
        try { Hub-ChatPrefetchQueuesAllCompaniesOnStartup } catch {
            if ($null -ne $script:TxtLog) { Append-Log ('Чаты (обновление): ' + $_.Exception.Message) }
        }
        try { Hub-ChatArchiveSyncAllCompaniesOnStartup } catch {
            if ($null -ne $script:TxtLog) { Append-Log ('Чаты-архив (обновление): ' + $_.Exception.Message) }
        }
        if ($null -ne $script:TabMain -and $script:TabMain.SelectedTab -eq $script:TpChats) {
            Hub-ChatRefreshChatsSectionFromArchive
        }
        try { Hub-IntegrityRefreshGrid } catch {
            if ($null -ne $script:TxtLog) { try { Append-Log ('Целостность после обновления: ' + [string]$_.Exception.Message) } catch { } }
        }
        if ($null -ne $script:TxtLog) { Append-Log 'Обновление: deploy-config, дерево, проверка очередей, синхронизация архива диалогов.' }
    } catch {
        if ($null -ne $script:TxtLog) { Append-Log ('Обновление: ошибка — ' + $_.Exception.Message) }
        [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, $script:HubAppTitle)
    } finally {
        $form.Cursor = $prevCur
    }
}

function Hub-ChatNormalizeQueueId {
    <# Сравнение id очереди из API/JSON: int, decimal, "82", "82.0" → одна строка. #>
    param($Raw)
    if ($null -eq $Raw) { return '' }
    if ($Raw -is [byte] -or $Raw -is [int] -or $Raw -is [long] -or $Raw -is [decimal] -or $Raw -is [double] -or $Raw -is [float]) {
        try { return [string]([long]([decimal]($Raw))) } catch { return ([string]$Raw).Trim() }
    }
    $s = ([string]$Raw).Trim()
    if ($s.Length -eq 0) { return '' }
    $d = 0.0
    $ci = [cultureinfo]::InvariantCulture
    if ([double]::TryParse($s, [System.Globalization.NumberStyles]::Any, $ci, [ref]$d)) {
        try { return [string]([long]$d) } catch { }
    }
    return $s
}

function Hub-ChatComputeDateRangeMs {
    [long]$sinceMs = 0
    [long]$untilMs = 0
    if ($script:RbChatDays.Checked) {
        $days = [int][decimal]$script:NumChatDays.Value
        $untilMs = Hub-ChatUtcToUnixMs ([datetime]::UtcNow)
        $sinceMs = Hub-ChatUtcToUnixMs ([datetime]::UtcNow.AddDays(-$days))
    } else {
        $d0 = $script:DtpChatFrom.Value.Date.ToUniversalTime()
        $d1 = $script:DtpChatTo.Value.Date.AddDays(1).AddMilliseconds(-1).ToUniversalTime()
        $sinceMs = Hub-ChatUtcToUnixMs $d0
        $untilMs = Hub-ChatUtcToUnixMs $d1
    }
    return @{ SinceMs = $sinceMs; UntilMs = $untilMs }
}

function Hub-ChatQueueIdFromNode {
    param($Node)
    if ($null -eq $Node) { return $null }
    if ($Node.PSObject.Properties['id'] -and $null -ne $Node.id) {
        $n = Hub-ChatNormalizeQueueId $Node.id
        if ($n.Length -gt 0) { return $n }
    }
    if ($Node -is [string] -or $Node -is [int] -or $Node -is [long] -or $Node -is [decimal] -or $Node -is [double]) {
        $n = Hub-ChatNormalizeQueueId $Node
        if ($n.Length -gt 0) { return $n }
    }
    return $null
}

function Hub-ChatExtractDialogItems {
    param($Resp)
    if ($null -eq $Resp) { return @() }
    if ($Resp -is [System.Array]) { return @($Resp) }
    if ($Resp.PSObject.Properties['items'] -and $null -ne $Resp.items) { return @($Resp.items) }
    if ($Resp.PSObject.Properties['data']) {
        $d = $Resp.data
        if ($null -eq $d) { return @() }
        if ($d -is [System.Array]) { return @($d) }
        if ($d.PSObject.Properties['items'] -and $null -ne $d.items) { return @($d.items) }
    }
    foreach ($alt in @('results', 'dialogs', 'list')) {
        if ($Resp.PSObject.Properties[$alt] -and $null -ne $Resp.$alt) {
            $v = $Resp.$alt
            if ($v -is [System.Array]) { return @($v) }
        }
    }
    return @()
}

function Hub-ChatTryParseDialogDateUtc {
    param($Dialog)
    if ($null -eq $Dialog) { return $null }
    foreach ($prop in @('date', 'created_at', 'started_at', 'updated_at')) {
        if (-not $Dialog.PSObject.Properties[$prop]) { continue }
        $raw = $Dialog.$prop
        if ($null -eq $raw) { continue }
        if ($raw -is [datetime]) {
            $dt = $raw
            if ($dt.Kind -eq [DateTimeKind]::Unspecified) { return [datetime]::SpecifyKind($dt, [DateTimeKind]::Utc) }
            return $dt.ToUniversalTime()
        }
        $s = [string]$raw
        if ([string]::IsNullOrWhiteSpace($s)) { continue }
        if ($s -match '^\d{10,16}$') {
            [long]$n = $s
            if ($s.Length -le 11) { $n = $n * 1000 }
            $epoch = [datetime]::SpecifyKind([datetime]'1970-01-01 00:00:00', [DateTimeKind]::Utc)
            return $epoch.AddMilliseconds([double]$n)
        }
        try {
            return [datetime]::Parse($s, [cultureinfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
        } catch { }
    }
    return $null
}

function Hub-ChatPhoneMatchesLikeFilter {
    param([string]$PhoneDisplay, [string]$FilterRaw)
    if ([string]::IsNullOrWhiteSpace($FilterRaw)) { return $true }
    $f = $FilterRaw.Trim()
    if ($f.Length -eq 0) { return $true }
    $hay = [string]$PhoneDisplay
    if ($null -eq $hay) { $hay = '' }
    $fd = ($f -replace '\D', '')
    $hd = ($hay -replace '\D', '')
    if ($fd.Length -gt 0) {
        return ($hd -like ('*' + $fd + '*'))
    }
    try {
        return ($hay -match ('(?i).*' + [regex]::Escape($f) + '.*'))
    } catch {
        return $false
    }
}

function Hub-ChatTryPhoneFromObject {
    param($o)
    if ($null -eq $o) { return $null }
    # В схеме чата Webitel поле user часто — сам номер (строка) или скаляр id
    if ($o -is [string]) {
        $s = $o.Trim()
        if ($s.Length -gt 0 -and $s -match '\d') { return $s }
        return $null
    }
    if ($o -is [datetime]) { return $null }
    if ($o -is [ValueType]) {
        $s = [string]$o
        if ($s -match '\d' -and $s.Length -ge 8) { return $s }
        return $null
    }
    foreach ($k in @('destination', 'phone', 'phone_number', 'phoneNumber', 'number', 'msisdn', 'mobile', 'mobile_phone', 'tel', 'e164', 'external_id', 'login', 'address', 'display', 'connection', 'username', 'sip', 'uri')) {
        if ($o.PSObject.Properties[$k] -and -not [string]::IsNullOrWhiteSpace([string]$o.$k)) {
            $v = [string]$o.$k
            if ($v -match '\d') { return $v }
        }
    }
    if ($o.PSObject.Properties['id'] -and $null -ne $o.id) {
        $vid = [string]$o.id
        if ($vid -match '^\+?\d{8,20}$') { return $vid }
    }
    # Webitel Member / участник: номер в communications[].destination (см. документацию Member API)
    if ($o.PSObject.Properties['communications'] -and $null -ne $o.communications) {
        foreach ($cm in @($o.communications)) {
            if ($null -eq $cm) { continue }
            foreach ($ck in @('destination', 'phone', 'number', 'display', 'address', 'msisdn')) {
                if (-not $cm.PSObject.Properties[$ck]) { continue }
                $cv = [string]$cm.$ck
                if (-not [string]::IsNullOrWhiteSpace($cv) -and $cv -match '\d') { return $cv }
            }
        }
    }
    return $null
}

function Hub-ChatTryPhoneFromVariablesBag {
    param($bag)
    if ($null -eq $bag) { return $null }
    foreach ($key in @('user', 'phone', 'client_phone', 'clientPhone', 'contact_number', 'contactNumber', 'msisdn', 'destination', 'to', 'from', 'wa_id', 'whatsapp', 'number', 'mobile', 'contact_phone', 'caller_id', 'callerId')) {
        try {
            if ($bag.PSObject.Properties[$key] -and $null -ne $bag.$key) {
                $v = [string]$bag.$key
                if (-not [string]::IsNullOrWhiteSpace($v) -and $v -match '\d') { return $v }
            }
        } catch { }
    }
    if ($bag -is [System.Collections.IDictionary]) {
        foreach ($ent in $bag.GetEnumerator()) {
            $ek = [string]$ent.Key
            if ($ek -notmatch '(?i)phone|dest|msisdn|mobile|wa|whatsapp|number|contact|tel|^user$') { continue }
            $v = [string]$ent.Value
            if (-not [string]::IsNullOrWhiteSpace($v) -and $v -match '\d') { return $v }
        }
    }
    return $null
}

function Hub-ChatDialogClientPhone {
    param($Dialog)
    if ($null -eq $Dialog) { return '' }
    foreach ($dk in @('contact_number', 'from_number', 'to_number', 'client_phone', 'caller_number', 'caller_id', 'callerId', 'cli', 'ani', 'destination', 'externalNumber', 'phone', 'phone_number', 'phoneNumber', 'msisdn', 'sender_number', 'senderNumber', 'customer_phone', 'customerPhone')) {
        if (-not $Dialog.PSObject.Properties[$dk]) { continue }
        $t = Hub-ChatTryPhoneFromObject $Dialog.$dk
        if (-not [string]::IsNullOrWhiteSpace($t)) { return $t }
    }
    foreach ($node in @($Dialog.user, $Dialog.member, $Dialog.customer, $Dialog.contact, $Dialog.client, $Dialog.from_user, $Dialog.author, $Dialog.sender, $Dialog.originator, $Dialog.from, $Dialog.to)) {
        $t = Hub-ChatTryPhoneFromObject $node
        if (-not [string]::IsNullOrWhiteSpace($t)) { return $t }
    }
    foreach ($coll in @('participants', 'attendees', 'visitors', 'customers')) {
        if (-not $Dialog.PSObject.Properties[$coll]) { continue }
        foreach ($a in @($Dialog.$coll)) {
            if ($null -eq $a) { continue }
            $t = Hub-ChatTryPhoneFromObject $a
            if (-not [string]::IsNullOrWhiteSpace($t)) { return $t }
        }
    }
    if ($Dialog.PSObject.Properties['peer'] -and $Dialog.peer) {
        $p = $Dialog.peer
        $t = Hub-ChatTryPhoneFromObject $p
        if (-not [string]::IsNullOrWhiteSpace($t)) { return $t }
        if ($p.PSObject.Properties['id'] -and -not [string]::IsNullOrWhiteSpace([string]$p.id)) { return [string]$p.id }
    }
    foreach ($vk in @('variables', 'metadata', 'props', 'properties', 'context')) {
        if (-not $Dialog.PSObject.Properties[$vk]) { continue }
        $t = Hub-ChatTryPhoneFromVariablesBag $Dialog.$vk
        if (-not [string]::IsNullOrWhiteSpace($t)) { return $t }
    }
    if ($Dialog.PSObject.Properties['member'] -and $Dialog.member -and $Dialog.member.PSObject.Properties['communications']) {
        foreach ($cm in @($Dialog.member.communications)) {
            if ($null -eq $cm) { continue }
            $t = Hub-ChatTryPhoneFromObject $cm
            if (-not [string]::IsNullOrWhiteSpace($t)) { return $t }
        }
    }
    try {
        $j = $Dialog | ConvertTo-Json -Depth 25 -Compress -ErrorAction Stop
        $m = [regex]::Match($j, '"destination"\s*:\s*"([^"]+)"')
        if ($m.Success -and $m.Groups[1].Value -match '\d') { return $m.Groups[1].Value }
        $m2 = [regex]::Match($j, '"phone"\s*:\s*"([^"]+)"')
        if ($m2.Success -and $m2.Groups[1].Value -match '\d') { return $m2.Groups[1].Value }
        $mus = [regex]::Match($j, '"user"\s*:\s*"([^"]+)"')
        if ($mus.Success -and $mus.Groups[1].Value -match '\d') { return $mus.Groups[1].Value.Trim() }
        $mu = [regex]::Match($j, '"user"\s*:\s*\{[^}]{0,800}"id"\s*:\s*"([^"]+)"')
        if ($mu.Success -and $mu.Groups[1].Value -match '\d') { return $mu.Groups[1].Value }
        $mu2 = [regex]::Match($j, '"user"\s*:\s*\{[^}]{0,800}"id"\s*:\s*(\d{8,20})')
        if ($mu2.Success) { return $mu2.Groups[1].Value }
        $mun = [regex]::Match($j, '"user"\s*:\s*\{[^}]{0,1200}"id"\s*:\s*(-?\d+\.?\d*)')
        if ($mun.Success -and $mun.Groups[1].Value -match '^\d{8,20}$') { return $mun.Groups[1].Value.Trim() }
    } catch { }
    return ''
}

function Hub-ChatExtractNameFromParty {
    param($o)
    if ($null -eq $o) { return $null }
    $bits = New-Object System.Collections.Generic.List[string]
    foreach ($k in @('name', 'display_name', 'full_name', 'username')) {
        if ($o.PSObject.Properties[$k] -and -not [string]::IsNullOrWhiteSpace([string]$o.$k)) { [void]$bits.Add([string]$o.$k) }
    }
    $fn = $null; $ln = $null
    foreach ($k in @('first_name', 'firstname', 'given_name')) {
        if ($o.PSObject.Properties[$k] -and -not [string]::IsNullOrWhiteSpace([string]$o.$k)) { $fn = [string]$o.$k; break }
    }
    foreach ($k in @('last_name', 'lastname', 'family_name')) {
        if ($o.PSObject.Properties[$k] -and -not [string]::IsNullOrWhiteSpace([string]$o.$k)) { $ln = [string]$o.$k; break }
    }
    if ($fn -or $ln) { return (("$fn $ln").Trim()) }
    if ($bits.Count -gt 0) { return [string]::Join(' ', $bits.ToArray()) }
    return $null
}

function Hub-ChatDialogPrimaryQueueId {
    param($Dialog)
    if ($null -eq $Dialog) { return $null }
    if ($Dialog.PSObject.Properties['queue'] -and $null -ne $Dialog.queue) {
        $x = Hub-ChatQueueIdFromNode $Dialog.queue
        if ($x) { return $x }
    }
    foreach ($pk in @('queue_id', 'queueId')) {
        if ($Dialog.PSObject.Properties[$pk] -and $null -ne $Dialog.$pk) {
            $n = Hub-ChatNormalizeQueueId $Dialog.$pk
            if ($n.Length -gt 0) { return $n }
        }
    }
    if ($Dialog.PSObject.Properties['member'] -and $Dialog.member) {
        $m = $Dialog.member
        if ($m.PSObject.Properties['queue'] -and $null -ne $m.queue) {
            $x = Hub-ChatQueueIdFromNode $m.queue
            if ($x) { return $x }
        }
        foreach ($pk in @('queue_id', 'queueId')) {
            if ($m.PSObject.Properties[$pk] -and $null -ne $m.$pk) {
                $n = Hub-ChatNormalizeQueueId $m.$pk
                if ($n.Length -gt 0) { return $n }
            }
        }
    }
    if ($Dialog.PSObject.Properties['conversation'] -and $Dialog.conversation) {
        $cv = $Dialog.conversation
        foreach ($pk in @('queue_id', 'queueId', 'queue')) {
            if ($cv.PSObject.Properties[$pk] -and $null -ne $cv.$pk) {
                $x = Hub-ChatQueueIdFromNode $cv.$pk
                if ($x) { return $x }
            }
        }
    }
    return $null
}

function Hub-ChatDialogHasQueueMetadata {
    <# Есть ли в объекте диалога поля очереди (для фильтра по чекбоксам). Архивы без queue* — false. #>
    param($Dialog)
    if ($null -eq $Dialog) { return $false }
    if (-not [string]::IsNullOrWhiteSpace((Hub-ChatDialogPrimaryQueueId $Dialog))) { return $true }
    if ($Dialog.PSObject.Properties['queue'] -and $null -ne $Dialog.queue) { return $true }
    foreach ($pk in @('queue_id', 'queueId')) {
        if ($Dialog.PSObject.Properties[$pk] -and $null -ne $Dialog.$pk) { return $true }
    }
    if ($Dialog.PSObject.Properties['member'] -and $Dialog.member) {
        $m = $Dialog.member
        if ($m.PSObject.Properties['queue'] -and $null -ne $m.queue) { return $true }
        foreach ($pk in @('queue_id', 'queueId')) {
            if ($m.PSObject.Properties[$pk] -and $null -ne $m.$pk) { return $true }
        }
    }
    if ($Dialog.PSObject.Properties['conversation'] -and $Dialog.conversation) {
        $cv = $Dialog.conversation
        foreach ($pk in @('queue_id', 'queueId', 'queue')) {
            if ($cv.PSObject.Properties[$pk] -and $null -ne $cv.$pk) { return $true }
        }
    }
    return $false
}

function Hub-ChatExtractSkillGroupNameFromQueueItem {
    <# Имя skill-группы у чат-очереди (Engine): объект, массив или строка. #>
    param($It)
    if ($null -eq $It) { return '' }
    foreach ($key in @('skill_group', 'skillGroup', 'skill_groups', 'skills', 'group')) {
        if (-not $It.PSObject.Properties[$key]) { continue }
        $sg = $It.$key
        if ($null -eq $sg) { continue }
        if ($sg -is [string]) {
            $t = [string]$sg
            if (-not [string]::IsNullOrWhiteSpace($t)) { return $t }
            continue
        }
        if ($sg -is [System.Collections.IEnumerable] -and $sg -isnot [string]) {
            foreach ($el in @($sg)) {
                if ($null -eq $el) { continue }
                foreach ($nk in @('name', 'display_name', 'title')) {
                    if ($el.PSObject.Properties[$nk] -and -not [string]::IsNullOrWhiteSpace([string]$el.$nk)) {
                        return [string]$el.$nk
                    }
                }
            }
            continue
        }
        foreach ($nk in @('name', 'display_name', 'title')) {
            if ($sg.PSObject.Properties[$nk] -and -not [string]::IsNullOrWhiteSpace([string]$sg.$nk)) {
                return [string]$sg.$nk
            }
        }
    }
    return ''
}

function Hub-ChatDepartmentFromQueueName {
    <# Типизация «Отдел» по названию очереди Webitel: Collection → Collection; CC → Call Center; иначе Не определен. #>
    param([string]$QueueName)
    if ([string]::IsNullOrWhiteSpace($QueueName)) { return 'Не определен' }
    if ($QueueName -match '(?i)Collection') { return 'Collection' }
    if ($QueueName -match '(?i)CC') { return 'Call Center' }
    return 'Не определен'
}

function Hub-ChatQueueSkillGroupLabel {
    <# Колонка «Отдел»: по имени очереди из метаданных (см. Hub-ChatDepartmentFromQueueName). #>
    param($Dialog)
    $qid = Hub-ChatDialogPrimaryQueueId $Dialog
    if ([string]::IsNullOrWhiteSpace($qid)) { return 'Не определен' }
    if ($null -eq $script:ChatQueueMeta) { return 'Не определен' }
    $qNorm = Hub-ChatNormalizeQueueId $qid
    foreach ($lbl in @($script:ChatQueueMeta.Keys)) {
        $meta = $script:ChatQueueMeta[$lbl]
        if (-not $meta -or $meta.Outside) { continue }
        $mid = ''
        if ($meta -is [hashtable]) {
            if ($meta.ContainsKey('Id')) { $mid = Hub-ChatNormalizeQueueId ([string]$meta['Id']) }
        }
        elseif ($meta.PSObject.Properties['Id'] -and $null -ne $meta.Id) {
            $mid = Hub-ChatNormalizeQueueId ([string]$meta.Id)
        }
        if ($mid -ne $qNorm) { continue }
        $qnm = ''
        if ($meta -is [hashtable]) {
            if ($meta.ContainsKey('Name')) { $qnm = [string]$meta['Name'] }
        }
        elseif ($meta.PSObject.Properties['Name'] -and $null -ne $meta.Name) {
            $qnm = [string]$meta.Name
        }
        return (Hub-ChatDepartmentFromQueueName $qnm)
    }
    return 'Не определен'
}

function Hub-ChatDialogClientName {
    param($Dialog)
    $undef = 'Не определен'
    if ($null -eq $Dialog) { return $undef }
    foreach ($node in @($Dialog.user, $Dialog.member, $Dialog.customer, $Dialog.peer)) {
        $n = Hub-ChatExtractNameFromParty $node
        if (-not [string]::IsNullOrWhiteSpace($n)) { return $n }
    }
    return $undef
}

function Hub-ChatDialogSourceKind {
    param($Dialog)
    # 'agent' — живой оператор; 'bot' — схема / до подключения агента; 'unknown' — редко (см. добивку в Populate)
    if ($null -eq $Dialog) { return 'unknown' }
    foreach ($hint in @('answered_at', 'answeredAt', 'joined_at', 'joinedAt', 'picked_at', 'pickedAt')) {
        if (-not $Dialog.PSObject.Properties[$hint]) { continue }
        $z = $Dialog.$hint
        if ($null -eq $z) { continue }
        if ($z -is [string] -and [string]::IsNullOrWhiteSpace($z)) { continue }
        if ($z -is [string] -and $z -match '^(0|false|null|none|undefined)$') { continue }
        if (($z -is [long] -or $z -is [int] -or $z -is [double] -or $z -is [decimal]) -and ([decimal]$z) -le 0) { continue }
        if ($z -is [datetime]) {
            if ($z.Year -ge 2000) { return 'agent' }
            continue
        }
        if ($z -is [bool] -and [bool]$z) { return 'agent' }
        if ($z -is [string]) {
            try {
                $dt = [datetime]::Parse($z, [cultureinfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::RoundtripKind)
                if ($dt.Year -ge 2000) { return 'agent' }
            } catch { }
        }
        if (($z -is [long] -or $z -is [int]) -and [long]$z -gt 946684800000) { return 'agent' }
    }
    if ($Dialog.PSObject.Properties['agent'] -and $null -ne $Dialog.agent) {
        $ag = $Dialog.agent
        if ($ag.PSObject.Properties['internal'] -and [bool]$ag.internal) { return 'bot' }
        if ($ag.PSObject.Properties['type'] -and ([string]$ag.type -match '(?i)bot|flow|system|schema')) { return 'bot' }
        if ($ag.PSObject.Properties['id'] -and $null -ne $ag.id) {
            try {
                if ([long]$ag.id -gt 0) { return 'agent' }
            } catch { }
        }
        if ($ag.PSObject.Properties['name'] -and -not [string]::IsNullOrWhiteSpace([string]$ag.name)) { return 'agent' }
    }
    if ($Dialog.PSObject.Properties['user'] -and $Dialog.user) {
        $u = $Dialog.user
        if ($u.PSObject.Properties['internal'] -and [bool]$u.internal) { return 'bot' }
        if ($u.PSObject.Properties['type'] -and ([string]$u.type -match '(?i)bot|flow|system|schema')) { return 'bot' }
    }
    if ($Dialog.PSObject.Properties['member'] -and $Dialog.member) {
        $m = $Dialog.member
        if ($m.PSObject.Properties['internal'] -and ([bool]$m.internal -eq $true)) { return 'bot' }
        if ($m.PSObject.Properties['type'] -and ([string]$m.type -match '(?i)^(flow|bot|system|internal|schema)$')) { return 'bot' }
    }
    foreach ($collName in @('attendees', 'participants', 'users', 'agents')) {
        if (-not $Dialog.PSObject.Properties[$collName]) { continue }
        foreach ($a in @($Dialog.($collName))) {
            if ($null -eq $a) { continue }
            if (-not $a.PSObject.Properties['type']) { continue }
            if ([string]$a.type -notmatch '(?i)user|agent') { continue }
            $internal = $false
            if ($a.PSObject.Properties['internal'] -and $null -ne $a.internal) { $internal = [bool]$a.internal }
            if (-not $internal) { return 'agent' }
        }
    }
    try {
        $j = $Dialog | ConvertTo-Json -Depth 18 -Compress -ErrorAction Stop
        if ($j -match '(?i)"(agent|operator|assignee)"\s*:\s*\{[^}]{0,400}"id"\s*:\s*[1-9][0-9]*') { return 'agent' }
        if ($j -match '(?i)"(schema_id|schemaId|flow_id|flowId)"\s*:\s*[1-9]') { return 'bot' }
    } catch { }
    return 'unknown'
}

function Hub-ChatGetCacheIndexFromDisplayRow {
    <# Tag строки грида = индекс в ChatDialogsCache (не Row.Index). #>
    param([int]$DisplayRowIndex)
    if ($null -eq $script:DgvChatDialogs) { return -1 }
    if ($DisplayRowIndex -lt 0 -or $DisplayRowIndex -ge $script:DgvChatDialogs.Rows.Count) { return -1 }
    $row = $script:DgvChatDialogs.Rows[$DisplayRowIndex]
    if ($null -eq $row -or $row.IsNewRow) { return -1 }
    $tag = $row.Tag
    if ($null -eq $tag) { return -1 }
    try { return [int]$tag } catch { return -1 }
}

function Hub-ChatDialogGridCurrentCacheIndex {
    <# Индекс в ChatDialogsCache: приоритет CurrentCell (после стабилизации UI), иначе минимальный Index среди SelectedRows. #>
    if ($null -eq $script:DgvChatDialogs) { return -1 }
    $g = $script:DgvChatDialogs
    if ($null -ne $g.CurrentCell -and $g.CurrentCell.RowIndex -ge 0) {
        $ix = Hub-ChatGetCacheIndexFromDisplayRow -DisplayRowIndex $g.CurrentCell.RowIndex
        if ($ix -ge 0) { return $ix }
    }
    $row = $null
    if ($g.SelectedRows.Count -gt 0) {
        $minRi = [int]::MaxValue
        foreach ($sr in $g.SelectedRows) {
            try {
                if ($null -eq $sr) { continue }
                if ($sr.Index -ge 0 -and $sr.Index -lt $minRi) { $minRi = $sr.Index; $row = $sr }
            } catch { }
        }
    }
    if ($null -eq $row) { $row = $g.CurrentRow }
    if ($null -eq $row -or $row.Index -lt 0) { return -1 }
    $tag = $row.Tag
    if ($null -eq $tag) { return -1 }
    try { return [int]$tag } catch { return -1 }
}

function Hub-ChatScheduleTranscriptLoad {
    <# DisplayRowIndex >= 0 — явная строка грида (CellClick); иначе — из CurrentCell/SelectedRows. Без BeginInvoke: PS + [System.Action] ломал захват $seq и транскрипт не открывался. #>
    param([int]$DisplayRowIndex = -1)
    if ($script:ChatGridSuppressSelectionEvent) { return }
    $script:ChatTranscriptPendingDisplayRow = $DisplayRowIndex
    Hub-ChatDialogSelectedChangedRun
}

function Hub-ChatPopulateDialogsGrid {
    if ($null -eq $script:DgvChatDialogs) { return }
    $g = $script:DgvChatDialogs
    $script:ChatGridSuppressSelectionEvent = $true
    $g.SuspendLayout()
    try {
        $g.Rows.Clear()
        $cache = @($script:ChatDialogsCache)
        $mode = 'all'
        if ($null -ne $script:RbChatSrcBot -and $script:RbChatSrcBot.Checked) { $mode = 'bot' }
        elseif ($null -ne $script:RbChatSrcAgent -and $script:RbChatSrcAgent.Checked) { $mode = 'agent' }
        for ($i = 0; $i -lt $cache.Count; $i++) {
            $d = $cache[$i]
            if ($null -eq $d) { continue }
            $kindRaw = Hub-ChatDialogSourceKind $d
            # «Только бот»: всё кроме явного агента (в т.ч. unknown). «Только агент»: только явный агент.
            if ($mode -eq 'bot' -and $kindRaw -eq 'agent') { continue }
            if ($mode -eq 'agent' -and $kindRaw -ne 'agent') { continue }
            $dtu = Hub-ChatTryParseDialogDateUtc $d
            $dateS = ''
            $timeS = ''
            if ($null -ne $dtu) {
                $dateS = $dtu.ToString('dd.MM.yyyy', [cultureinfo]::InvariantCulture)
                $timeS = $dtu.ToString('HH:mm:ss', [cultureinfo]::InvariantCulture)
            }
            $phone = Hub-ChatDialogClientPhone $d
            $custName = Hub-ChatDialogClientName $d
            $phonePat = ''
            if ($null -ne $script:TxtChatPhoneFilter) { $phonePat = [string]$script:TxtChatPhoneFilter.Text }
            if (-not (Hub-ChatPhoneMatchesLikeFilter $phone $phonePat)) { continue }
            $skillLab = Hub-ChatQueueSkillGroupLabel $d
            [void]$g.Rows.Add($dateS, $timeS, $phone, $custName, $skillLab)
            $g.Rows[$g.Rows.Count - 1].Tag = [int]$i
        }
        if ($g.Rows.Count -gt 0) {
            $g.ClearSelection()
            $g.Rows[0].Selected = $true
            $g.CurrentCell = $g.Rows[0].Cells[0]
        }
    } finally {
        $g.ResumeLayout()
        $script:ChatGridSuppressSelectionEvent = $false
    }
    if ($g.Rows.Count -gt 0) { Hub-ChatScheduleTranscriptLoad -DisplayRowIndex 0 }
}

function Hub-ChatDialogBelongsToQueues {
    param($Dialog, [string[]]$QueueIdStrings)
    if ($null -eq $Dialog -or $QueueIdStrings.Count -eq 0) { return $false }
    $normSids = New-Object System.Collections.Generic.List[string]
    foreach ($s in $QueueIdStrings) {
        $ns = Hub-ChatNormalizeQueueId $s
        if ($ns.Length -gt 0) { [void]$normSids.Add($ns) }
    }
    if ($normSids.Count -eq 0) { return $false }
    foreach ($sid in $normSids) {
        if ($Dialog.PSObject.Properties['queue'] -and $null -ne $Dialog.queue) {
            $quId = Hub-ChatQueueIdFromNode $Dialog.queue
            if ($quId -and ($quId -eq $sid)) { return $true }
        }
        if ($Dialog.PSObject.Properties['queue_id'] -and $null -ne $Dialog.queue_id) {
            if ((Hub-ChatNormalizeQueueId $Dialog.queue_id) -eq $sid) { return $true }
        }
        if ($Dialog.PSObject.Properties['queueId'] -and $null -ne $Dialog.queueId) {
            if ((Hub-ChatNormalizeQueueId $Dialog.queueId) -eq $sid) { return $true }
        }
        if ($Dialog.PSObject.Properties['member'] -and $Dialog.member) {
            $m = $Dialog.member
            if ($m.PSObject.Properties['queue'] -and $null -ne $m.queue) {
                $mqId = Hub-ChatQueueIdFromNode $m.queue
                if ($mqId -and ($mqId -eq $sid)) { return $true }
            }
            if ($m.PSObject.Properties['queue_id'] -and $null -ne $m.queue_id) {
                if ((Hub-ChatNormalizeQueueId $m.queue_id) -eq $sid) { return $true }
            }
            if ($m.PSObject.Properties['queueId'] -and $null -ne $m.queueId) {
                if ((Hub-ChatNormalizeQueueId $m.queueId) -eq $sid) { return $true }
            }
        }
        if ($Dialog.PSObject.Properties['conversation'] -and $Dialog.conversation) {
            $cv = $Dialog.conversation
            foreach ($pk in @('queue_id', 'queueId', 'queue')) {
                if ($cv.PSObject.Properties[$pk] -and $null -ne $cv.$pk) {
                    $cq = Hub-ChatQueueIdFromNode $cv.$pk
                    if ($cq -and ($cq -eq $sid)) { return $true }
                    if ((Hub-ChatNormalizeQueueId $cv.$pk) -eq $sid) { return $true }
                }
            }
        }
    }
    $pq = Hub-ChatDialogPrimaryQueueId $Dialog
    if (-not [string]::IsNullOrWhiteSpace($pq)) {
        $pqn = Hub-ChatNormalizeQueueId $pq
        foreach ($sid in $normSids) {
            if ($pqn -eq $sid) { return $true }
        }
    }
    try {
        $j = $Dialog | ConvertTo-Json -Depth 40 -Compress -ErrorAction Stop
        foreach ($sid in $normSids) {
            $esc = [regex]::Escape($sid)
            if ($j -match ('"queue_id"\s*:\s*"?'+$esc+'"?')) { return $true }
            if ($j -match ('"queueId"\s*:\s*"?'+$esc+'"?')) { return $true }
            if ($j -match ('"queue"\s*:\s*\{[^}]{0,400}"id"\s*:\s*"?'+$esc+'"?')) { return $true }
        }
    } catch { }
    return $false
}

function Hub-ChatGetSelectedQueueIds {
    if ($null -eq $script:ClbChatQueues) { return @() }
    $ids = New-Object System.Collections.Generic.List[string]
    for ($i = 0; $i -lt $script:ClbChatQueues.Items.Count; $i++) {
        if (-not $script:ClbChatQueues.GetItemChecked($i)) { continue }
        $lbl = [string]$script:ClbChatQueues.Items[$i]
        $m = $script:ChatQueueMeta[$lbl]
        if (-not $m) { continue }
        if ($m.Outside -or [string]$m.Id -eq '__OUTSIDE__') { continue }
        $nid = Hub-ChatNormalizeQueueId $m.Id
        if ($nid.Length -gt 0) { [void]$ids.Add($nid) }
    }
    return $ids.ToArray()
}

function Hub-ChatIsOutsideQueuesChecked {
    if ($null -eq $script:ClbChatQueues) { return $false }
    for ($i = 0; $i -lt $script:ClbChatQueues.Items.Count; $i++) {
        if (-not $script:ClbChatQueues.GetItemChecked($i)) { continue }
        $lbl = [string]$script:ClbChatQueues.Items[$i]
        $m = $script:ChatQueueMeta[$lbl]
        if ($m -and $m.Outside) { return $true }
    }
    return $false
}

function Hub-ChatFilterDialogsByQueueSelection {
    param($Dialogs)
    if ($null -eq $script:ClbChatQueues) { return @($Dialogs) }
    $outside = Hub-ChatIsOutsideQueuesChecked
    $qids = @(Hub-ChatGetSelectedQueueIds)
    if ($qids.Count -eq 0 -and -not $outside) { return @() }
    $dlgArr = @($Dialogs)
    if ($dlgArr.Count -gt 0) {
        $anyQueueMeta = $false
        foreach ($d in $dlgArr) {
            if (Hub-ChatDialogHasQueueMetadata $d) { $anyQueueMeta = $true; break }
        }
        if (-not $anyQueueMeta) {
            return $dlgArr
        }
    }
    $allInboundArr = @($script:ChatInboundQueueAllIds | ForEach-Object { [string]$_ })
    $out = New-Object System.Collections.Generic.List[object]
    foreach ($it in $dlgArr) {
        if ($null -eq $it) { continue }
        $inQ = $false
        if ($qids.Count -gt 0) {
            $inQ = Hub-ChatDialogBelongsToQueues -Dialog $it -QueueIdStrings $qids
        }
        $take = $false
        if ($qids.Count -gt 0) {
            if ($inQ) { $take = $true }
            elseif ($outside) { $take = -not $inQ }
        }
        elseif ($outside) {
            if ($allInboundArr.Count -gt 0) {
                $take = -not (Hub-ChatDialogBelongsToQueues -Dialog $it -QueueIdStrings $allInboundArr)
            }
            else { $take = $true }
        }
        if ($take) { [void]$out.Add($it) }
    }
    return $out.ToArray()
}

function Hub-ChatApplyQueueFilterAndPopulate {
    if ($null -eq $script:ChatDialogsRawCache) { $script:ChatDialogsRawCache = @() }
    $script:ChatDialogsCache = @(Hub-ChatFilterDialogsByQueueSelection -Dialogs $script:ChatDialogsRawCache)
    Hub-ChatPopulateDialogsGrid
}

function Hub-ChatPeerDisplay {
    param($Dialog)
    $p = $Dialog.peer
    if (-not $p -and $Dialog.PSObject.Properties['customer']) { $p = $Dialog.customer }
    if (-not $p -and $Dialog.PSObject.Properties['member']) {
        $m = $Dialog.member
        if ($m -and $m.PSObject.Properties['destination']) { return [string]$m.destination }
        if ($m -and $m.PSObject.Properties['name']) { return [string]$m.name }
    }
    if (-not $p) { return '?' }
    $nm = [string]$p.name
    if ([string]::IsNullOrWhiteSpace($nm)) { $nm = [string]$p.id }
    $typ = [string]$p.type
    if (-not [string]::IsNullOrWhiteSpace($typ)) { return ($typ + ': ' + $nm) }
    return $nm
}

function Hub-ChatFormatDialogLine {
    param($Dialog)
    $id = [string]$Dialog.id
    $peer = Hub-ChatPeerDisplay $Dialog
    $ts = ''
    if ($Dialog.PSObject.Properties['date'] -and $null -ne $Dialog.date) {
        $ts = [string]$Dialog.date
    }
    return ($id + ' — ' + $peer + ' — ' + $ts)
}

function Hub-ChatFormatMessagesText {
    param($Hist)
    if ($null -eq $Hist) { return '(пусто)' }
    $arr = @()
    if ($Hist.PSObject.Properties['items'] -and $Hist.items) { $arr = @($Hist.items) }
    elseif ($Hist.PSObject.Properties['messages'] -and $Hist.messages) { $arr = @($Hist.messages) }
    if ($arr.Count -eq 0) { return ($Hist | ConvertTo-Json -Depth 15) }
    $sb = New-Object System.Text.StringBuilder
    foreach ($m in $arr) {
        $who = '?'
        if ($m.sender) {
            if ($m.sender.name) { $who = [string]$m.sender.name }
            elseif ($m.sender.id) { $who = [string]$m.sender.id }
        }
        $when = ''
        if ($m.PSObject.Properties['date'] -and $null -ne $m.date) { $when = [string]$m.date }
        elseif ($m.PSObject.Properties['created_at'] -and $null -ne $m.created_at) { $when = [string]$m.created_at }
        $txt = $m.text
        if (-not $txt -and $m.message) {
            if ($m.message.text) { $txt = [string]$m.message.text }
        }
        if (-not $txt) { $txt = '[нет текста]' }
        [void]$sb.AppendLine(('[' + $when + '] ' + $who + ':'))
        [void]$sb.AppendLine($txt)
        [void]$sb.AppendLine('')
    }
    return $sb.ToString()
}

function Hub-ChatNormalizeIdDigits {
    param([string]$s)
    if ([string]::IsNullOrWhiteSpace($s)) { return '' }
    return ($s.Trim() -replace '\D', '')
}

function Hub-ChatCollectDialogPartyNames {
    param($Dialog)
    $out = New-Object System.Collections.Generic.List[string]
    if ($null -eq $Dialog) { return @() }
    foreach ($node in @($Dialog.peer, $Dialog.customer, $Dialog.member, $Dialog.user)) {
        if ($null -eq $node) { continue }
        foreach ($nk in @('name', 'display_name', 'full_name', 'username')) {
            if (-not $node.PSObject.Properties[$nk]) { continue }
            $t = ([string]$node.$nk).Trim()
            if ($t.Length -gt 0) { [void]$out.Add($t) }
        }
    }
    return @($out | Select-Object -Unique)
}

function Hub-ChatMessageSenderLooksLikeClient {
    <# Сопоставление sender сообщения с peer/member/телефоном диалога (Webitel часто не заполняет sender.type). #>
    param($Message, $Dialog)
    if ($null -eq $Message -or $null -eq $Dialog -or $null -eq $Message.sender) { return $false }
    $snd = $Message.sender
    $sidRaw = ''
    if ($snd.PSObject.Properties['id'] -and $null -ne $snd.id) { $sidRaw = [string]$snd.id }
    $sid = Hub-ChatNormalizeIdDigits $sidRaw
    $ph = Hub-ChatDialogClientPhone $Dialog
    $phd = Hub-ChatNormalizeIdDigits $ph
    if ($phd.Length -ge 8 -and $sid.Length -ge 6) {
        if ($phd.EndsWith($sid) -or $sid.EndsWith($phd) -or $phd.Contains($sid) -or $sid.Contains($phd)) { return $true }
    }
    foreach ($node in @($Dialog.peer, $Dialog.customer, $Dialog.member)) {
        if ($null -eq $node) { continue }
        if ($node.PSObject.Properties['id'] -and $null -ne $node.id) {
            $nid = Hub-ChatNormalizeIdDigits ([string]$node.id)
            if ($nid.Length -ge 6 -and $sid.Length -ge 6 -and ($nid -eq $sid -or $nid.Contains($sid) -or $sid.Contains($nid))) { return $true }
            if (-not [string]::IsNullOrWhiteSpace($sidRaw) -and ([string]$node.id) -eq $sidRaw) { return $true }
        }
        if ($node.PSObject.Properties['destination'] -and $null -ne $node.destination) {
            $dest = Hub-ChatNormalizeIdDigits ([string]$node.destination)
            if ($dest.Length -ge 8 -and $sid.Length -ge 8 -and ($dest -eq $sid -or $dest.Contains($sid) -or $sid.Contains($dest))) { return $true }
        }
    }
    $whoDisp = ''
    if ($snd.PSObject.Properties['name'] -and $null -ne $snd.name) { $whoDisp = ([string]$snd.name).Trim() }
    foreach ($pn in @(Hub-ChatCollectDialogPartyNames $Dialog)) {
        if ($whoDisp.Length -eq 0 -or $pn.Length -eq 0) { continue }
        if ($whoDisp -eq $pn) { return $true }
        if ($whoDisp.Length -ge 4 -and $pn.Length -ge 4 -and ($whoDisp -like ('*' + $pn + '*') -or $pn -like ('*' + $whoDisp + '*'))) { return $true }
    }
    return $false
}

function Hub-ChatGetMessageRowsFromHist {
    param($Hist, $Dialog = $null)
    $rows = New-Object System.Collections.Generic.List[hashtable]
    if ($null -eq $Hist) { return $rows }
    $arr = @()
    if ($Hist.PSObject.Properties['items'] -and $Hist.items) { $arr = @($Hist.items) }
    elseif ($Hist.PSObject.Properties['messages'] -and $Hist.messages) { $arr = @($Hist.messages) }
    if ($arr.Count -eq 0) {
        try {
            $j = $Hist | ConvertTo-Json -Depth 12 -Compress -ErrorAction Stop
            [void]$rows.Add(@{ IsClient = $false; Who = 'JSON'; When = ''; Body = $j; IsRaw = $true })
        } catch {
            [void]$rows.Add(@{ IsClient = $false; Who = '—'; When = ''; Body = '(пусто)'; IsRaw = $false })
        }
        return $rows
    }
    foreach ($m in $arr) {
        $who = '?'
        $internal = $false
        $st = ''
        if ($m.sender) {
            if ($m.sender.name) { $who = [string]$m.sender.name }
            elseif ($m.sender.id) { $who = [string]$m.sender.id }
            if ($m.sender.PSObject.Properties['internal'] -and $null -ne $m.sender.internal) {
                try { $internal = [bool]$m.sender.internal } catch { $internal = $false }
            }
            if ($m.sender.PSObject.Properties['type'] -and $null -ne $m.sender.type) { $st = [string]$m.sender.type }
        }
        $when = ''
        if ($m.PSObject.Properties['date'] -and $null -ne $m.date) { $when = [string]$m.date }
        elseif ($m.PSObject.Properties['created_at'] -and $null -ne $m.created_at) { $when = [string]$m.created_at }
        $txt = $m.text
        if (-not $txt -and $m.message) {
            if ($m.message.text) { $txt = [string]$m.message.text }
        }
        if (-not $txt) { $txt = '[нет текста]' }
        $isClient = $false
        if ($internal) {
            $isClient = $false
        } elseif ($st -match '(?i)^(user|guest|customer|contact|member|client)$') {
            $isClient = $true
        } elseif ($st -match '(?i)agent|skill|queue|group|operator|flow|bot|system|schema|supervisor|engine|ivr') {
            $isClient = $false
        } elseif ($null -ne $Dialog -and (Hub-ChatMessageSenderLooksLikeClient -Message $m -Dialog $Dialog)) {
            $isClient = $true
        } elseif ($who -match '^\+?\d{9,16}$' -or $who -match '^\d{10,11}$') {
            $isClient = $true
        } elseif ($who -match '^\d{12,24}$') {
            $isClient = $false
        } elseif ($who -match '^\d{8,11}$') {
            $isClient = $false
        } elseif ($st -eq '' -and -not $internal -and $null -eq $Dialog) {
            $isClient = $true
        } elseif ($st -eq '' -and -not $internal) {
            $isClient = $false
        }
        [void]$rows.Add(@{ IsClient = $isClient; Who = $who; When = $when; Body = $txt; IsRaw = $false })
    }
    return $rows
}

function Hub-ChatClearTranscriptUi {
    if ($null -ne $script:FlpChatTranscript) {
        $script:FlpChatTranscript.Controls.Clear()
    }
    if ($null -ne $script:FlpChatTranscriptRu) {
        $script:FlpChatTranscriptRu.Controls.Clear()
    }
    if ($null -ne $script:LblChatTranscriptMeta) {
        $script:LblChatTranscriptMeta.Text = ''
    }
}

function Hub-ChatReflowTranscriptBubblesFor {
    param([System.Windows.Forms.FlowLayoutPanel]$Flp)
    if ($null -eq $Flp) { return }
    $rw = [Math]::Max(160, $Flp.ClientSize.Width - 8)
    foreach ($p in $Flp.Controls) {
        if ($p -isnot [System.Windows.Forms.Panel]) { continue }
        $p.Width = $rw
        $isCl = $true
        if ($null -ne $p.Tag -and $null -ne $p.Tag['IsClientRow']) {
            try { $isCl = [bool]$p.Tag['IsClientRow'] } catch { $isCl = $true }
        }
        $bubble = $p.Controls['Bubble']
        if ($null -eq $bubble) { continue }
        $maxB = [int]([Math]::Min(420, [Math]::Max(160, $rw * 0.78)))
        $bubble.MaximumSize = New-Object System.Drawing.Size($maxB, 0)
        if ($isCl) {
            $bubble.Left = 0
        }
        else {
            $bubble.Left = [Math]::Max(0, $p.ClientSize.Width - $bubble.Width - 6)
        }
        foreach ($c in $p.Controls) {
            if ($c -eq $bubble) { continue }
            if ($c -is [System.Windows.Forms.Label]) {
                if ($isCl) { $c.Left = 0 }
                else { $c.Left = [Math]::Max(0, $p.ClientSize.Width - $c.PreferredWidth - 2) }
            }
        }
        $p.Height = $bubble.Bottom + 8
    }
}

function Hub-ChatReflowTranscriptBubbles {
    Hub-ChatReflowTranscriptBubblesFor -Flp $script:FlpChatTranscript
    Hub-ChatReflowTranscriptBubblesFor -Flp $script:FlpChatTranscriptRu
}

function Hub-ChatAddTranscriptBubbleRow {
    param(
        [Parameter(Mandatory)][System.Windows.Forms.FlowLayoutPanel]$Flp,
        [int]$AvailWidth,
        [bool]$IsClient,
        [string]$Who,
        [string]$When,
        [string]$Body
    )
    $rowW = [Math]::Max(200, $AvailWidth - 8)
    $maxBubble = [int]([Math]::Min(440, $rowW * 0.82))
    $p = New-Object System.Windows.Forms.Panel
    $p.Margin = New-Object System.Windows.Forms.Padding(4, 0, 4, 10)
    $p.AutoSize = $false
    $p.Width = $rowW
    $p.MinimumSize = New-Object System.Drawing.Size($rowW, 1)
    $p.BackColor = [System.Drawing.Color]::Transparent
    $p.Tag = @{ IsClientRow = $IsClient }
    $cap = New-Object System.Windows.Forms.Label
    $cap.AutoSize = $true
    $cap.Font = New-Object System.Drawing.Font('Segoe UI', 7.5, [System.Drawing.FontStyle]::Regular)
    $cap.ForeColor = $script:HubUiMuted
    $cap.Text = ($(if (-not [string]::IsNullOrWhiteSpace($When)) { $When + ' · ' }) + $Who)
    $cap.Location = New-Object System.Drawing.Point(0, 0)
    $bubble = New-Object System.Windows.Forms.Label
    $bubble.Name = 'Bubble'
    $bubble.AutoSize = $true
    $bubble.MaximumSize = New-Object System.Drawing.Size($maxBubble, 0)
    $bubble.Text = $Body
    $bubble.Font = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Regular)
    $bubble.Padding = New-Object System.Windows.Forms.Padding(14, 11, 14, 11)
    $bubble.UseMnemonic = $false
    if ($IsClient) {
        $bubble.BackColor = [System.Drawing.Color]::FromArgb(255, 255, 255)
        $bubble.ForeColor = $script:HubUiInk
    } else {
        $bubble.BackColor = [System.Drawing.Color]::FromArgb(219, 234, 254)
        $bubble.ForeColor = $script:HubUiInk
    }
    [void]$p.Controls.Add($cap)
    [void]$p.Controls.Add($bubble)
    $bubble.Top = $cap.Bottom + 4
    $p.PerformLayout()
    $bubble.Left = if ($IsClient) { 0 } else { [Math]::Max(0, $p.ClientSize.Width - $bubble.Width - 4) }
    if (-not $IsClient) {
        $cap.Left = [Math]::Max(0, $p.ClientSize.Width - $cap.PreferredWidth)
    }
    $p.Height = $bubble.Bottom + 8
    [void]$Flp.Controls.Add($p)
}

function Hub-ChatRenderTranscriptFromHist {
    param(
        $Dlg,
        $Hist,
        [string]$SkillLabel,
        [string]$ResponderRu,
        [string]$ErrorText
    )
    Hub-ChatClearTranscriptUi
    if ($null -eq $script:FlpChatTranscript -or $null -eq $script:LblChatTranscriptMeta) { return }
    if (-not [string]::IsNullOrWhiteSpace($ErrorText)) {
        $script:LblChatTranscriptMeta.Text = 'Ошибка загрузки сообщений'
        $script:LblChatTranscriptMeta.ForeColor = [System.Drawing.Color]::FromArgb(185, 28, 28)
        $err = New-Object System.Windows.Forms.Label
        $err.AutoSize = $true
        $err.MaximumSize = New-Object System.Drawing.Size(([Math]::Max(200, $script:FlpChatTranscript.ClientSize.Width - 32)), 0)
        $err.Margin = New-Object System.Windows.Forms.Padding(8, 12, 8, 8)
        $err.Font = New-Object System.Drawing.Font('Segoe UI', 9.5, [System.Drawing.FontStyle]::Regular)
        $err.ForeColor = [System.Drawing.Color]::FromArgb(127, 29, 29)
        $err.Text = $ErrorText
        [void]$script:FlpChatTranscript.Controls.Add($err)
        return
    }
    $script:LblChatTranscriptMeta.ForeColor = $script:HubUiMuted
    $script:LblChatTranscriptMeta.Text = (
        'Отдел: ' + $SkillLabel + [Environment]::NewLine +
        'Ответчик: ' + $ResponderRu + [Environment]::NewLine +
        'Слева — оригинал (клиент слева, ответы справа); справа — автоперевод на русский (api.mymemory.translated.net).')
    $rows = Hub-ChatGetMessageRowsFromHist -Hist $Hist -Dialog $Dlg
    $rowsRu = @(Hub-ChatCloneRowsWithRussianBodies -Rows $rows)
    $awL = [Math]::Max(180, $script:FlpChatTranscript.ClientSize.Width - 8)
    $awR = if ($null -ne $script:FlpChatTranscriptRu) {
        [Math]::Max(180, $script:FlpChatTranscriptRu.ClientSize.Width - 8)
    } else { $awL }
    foreach ($row in $rows) {
        if ($row.IsRaw) {
            Hub-ChatAddTranscriptBubbleRow -Flp $script:FlpChatTranscript -AvailWidth $awL -IsClient $false -Who $row.Who -When $row.When -Body $row.Body
        } else {
            Hub-ChatAddTranscriptBubbleRow -Flp $script:FlpChatTranscript -AvailWidth $awL -IsClient ([bool]$row.IsClient) -Who $row.Who -When $row.When -Body $row.Body
        }
    }
    if ($null -ne $script:FlpChatTranscriptRu) {
        foreach ($row in $rowsRu) {
            if ($row.IsRaw) {
                Hub-ChatAddTranscriptBubbleRow -Flp $script:FlpChatTranscriptRu -AvailWidth $awR -IsClient $false -Who $row.Who -When $row.When -Body $row.Body
            } else {
                Hub-ChatAddTranscriptBubbleRow -Flp $script:FlpChatTranscriptRu -AvailWidth $awR -IsClient ([bool]$row.IsClient) -Who $row.Who -When $row.When -Body $row.Body
            }
        }
    }
    Hub-ChatReflowTranscriptBubbles
    if ($script:FlpChatTranscript.Controls.Count -gt 0) {
        $last = $script:FlpChatTranscript.Controls[$script:FlpChatTranscript.Controls.Count - 1]
        $script:FlpChatTranscript.ScrollControlIntoView($last)
    }
    if ($null -ne $script:FlpChatTranscriptRu -and $script:FlpChatTranscriptRu.Controls.Count -gt 0) {
        $lastR = $script:FlpChatTranscriptRu.Controls[$script:FlpChatTranscriptRu.Controls.Count - 1]
        $script:FlpChatTranscriptRu.ScrollControlIntoView($lastR)
    }
}

function Hub-ChatFetchChatQueuesForCompanyKey {
    <# GET /call_center/queues (тип чат-входящие). Пытаемся запросить skill_group для колонки «Отдел». #>
    param([Parameter(Mandatory)][string]$Key)
    $c = $script:Companies.$Key
    if (-not $c) { throw "Нет данных компании: $Key" }
    $hostB = [string]$c.webitel_host
    $tok = [string]$c.access_token
    if ([string]::IsNullOrWhiteSpace($hostB) -or $hostB -match '^PASTE_') { throw 'У компании не задан webitel_host в конфиге.' }
    if ([string]::IsNullOrWhiteSpace($tok) -or $tok -match '^PASTE_') { throw 'У компании не задан access_token.' }
    $base = @{
        page = 1
        size = 500
        type = @($script:WebitelQueueTypeChatInbound)
        sort = @('name')
    }
    $resp = $null
    try {
        $resp = Hub-WebitelRestGet -WebitelHost $hostB -AccessToken $tok -RelativeApiPath '/call_center/queues' -Query ($base + @{
                fields = @('id', 'name', 'type', 'enabled', 'skill_group', 'skill_groups')
            })
    } catch {
        $resp = Hub-WebitelRestGet -WebitelHost $hostB -AccessToken $tok -RelativeApiPath '/call_center/queues' -Query ($base + @{
                fields = @('id', 'name', 'type', 'enabled')
            })
    }
    if ($null -eq $resp) { return @() }
    return @($resp.items)
}

function Hub-QueueControlGetTypeFilterDefinitions {
    <# Числовые типы — как model.QueueType в github.com/webitel/call_center/model/queue.go (iota). #>
    return @(
        @{ Tid = $null; Text = 'Все типы (Webitel)' }
        @{ Tid = 0; Text = '0 — Offline (callbacks)' }
        @{ Tid = 1; Text = '1 — Inbound (звонок)' }
        @{ Tid = 2; Text = '2 — Outbound IVR' }
        @{ Tid = 3; Text = '3 — Preview dialer' }
        @{ Tid = 4; Text = '4 — Progressive dialer' }
        @{ Tid = 5; Text = '5 — Predictive dialer' }
        @{ Tid = 6; Text = '6 — Inbound chat' }
        @{ Tid = 7; Text = '7 — Inbound task (Agent task)' }
        @{ Tid = 8; Text = '8 — Outbound task' }
        @{ Tid = 9; Text = '9 — Inbound IM' }
        @{ Tid = 10; Text = '10 — Outbound call' }
    )
}

function Hub-QueueControlGetSelectedTypeFilterId {
    if ($null -eq $script:CmbQueuesTypeFilter) { return $null }
    $ix = [int]$script:CmbQueuesTypeFilter.SelectedIndex
    if ($ix -lt 0) { return $null }
    $defs = @(Hub-QueueControlGetTypeFilterDefinitions)
    if ($ix -ge $defs.Count) { return $null }
    return $defs[$ix].Tid
}

function Hub-QueueControlWebitelTypeLabel {
    param($TypeVal)
    $n = $null
    try {
        if ($null -eq $TypeVal) { return '—' }
        if ($TypeVal -is [int] -or $TypeVal -is [long]) { $n = [int]$TypeVal }
        elseif ($TypeVal -is [double] -or $TypeVal -is [decimal]) { $n = [int][double]$TypeVal }
        else {
            $s = ([string]$TypeVal).Trim()
            if ($s -match '^-?\d+$') { $n = [int]$s } else { return $s }
        }
    } catch { return ([string]$TypeVal) }
    switch ($n) {
        0 { return 'Offline (callbacks)' }
        1 { return 'Inbound (звонок)' }
        2 { return 'Outbound IVR' }
        3 { return 'Preview dialer' }
        4 { return 'Progressive dialer' }
        5 { return 'Predictive dialer' }
        6 { return 'Inbound chat' }
        7 { return 'Inbound task (Agent task)' }
        8 { return 'Outbound task' }
        9 { return 'Inbound IM' }
        10 { return 'Outbound call' }
        default { return ('Неизвестный тип (' + [string]$n + ')') }
    }
}

function Hub-QueueControlExtractQueueTypeId {
    param($It)
    if ($null -eq $It) { return $null }
    if (-not ($It.PSObject.Properties['type'])) { return $null }
    $t = $It.type
    if ($null -eq $t) { return $null }
    if ($t -is [int] -or $t -is [long] -or $t -is [double] -or $t -is [decimal]) {
        try { return [int]$t } catch { return $null }
    }
    if ($t -is [string]) {
        $s = $t.Trim()
        if ($s -match '^-?\d+$') { try { return [int]$s } catch { return $null } }
        return $null
    }
    if ($t.PSObject.Properties['id'] -and $null -ne $t.id) {
        try { return [int]$t.id } catch { return $null }
    }
    return $null
}

function Hub-QueueControlQueueEnabledText {
    param($It)
    if ($null -eq $It) { return '—' }
    foreach ($p in @('enabled', 'active')) {
        if (-not ($It.PSObject.Properties[$p])) { continue }
        $v = $It.$p
        if ($v -is [bool]) { return $(if ($v) { 'Включена' } else { 'Выключена' }) }
        $s = ([string]$v).Trim().ToLowerInvariant()
        if ($s -eq 'true' -or $s -eq '1') { return 'Включена' }
        if ($s -eq 'false' -or $s -eq '0') { return 'Выключена' }
        if (-not [string]::IsNullOrWhiteSpace($s)) { return [string]$v }
    }
    return '—'
}

function Hub-QueueControlExtractTeamLabel {
    <# Команда (Team), привязанная к очереди в Engine: team / teams и т.п. #>
    param($It)
    if ($null -eq $It) { return '' }
    foreach ($key in @('team', 'teams', 'queue_team', 'acl_team', 'team_id')) {
        if (-not ($It.PSObject.Properties[$key])) { continue }
        $tg = $It.$key
        if ($null -eq $tg) { continue }
        if ($key -eq 'team_id' -and ($tg -is [int] -or $tg -is [long] -or $tg -is [double] -or $tg -is [decimal])) {
            return ('team_id: ' + [string]$tg)
        }
        if ($tg -is [string]) {
            $s = [string]$tg
            if (-not [string]::IsNullOrWhiteSpace($s)) { return $s }
            continue
        }
        if ($tg -is [System.Collections.IEnumerable] -and $tg -isnot [string]) {
            foreach ($el in @($tg)) {
                if ($null -eq $el) { continue }
                foreach ($nk in @('name', 'display_name', 'title')) {
                    if ($el.PSObject.Properties[$nk] -and -not [string]::IsNullOrWhiteSpace([string]$el.$nk)) {
                        return [string]$el.$nk
                    }
                }
                if ($el.PSObject.Properties['id'] -and $null -ne $el.id) {
                    $sid = ([string]$el.id).Trim()
                    if (-not [string]::IsNullOrWhiteSpace($sid)) { return ('id: ' + $sid) }
                }
            }
            continue
        }
        foreach ($nk in @('name', 'display_name', 'title')) {
            if ($tg.PSObject.Properties[$nk] -and -not [string]::IsNullOrWhiteSpace([string]$tg.$nk)) {
                return [string]$tg.$nk
            }
        }
        if ($tg.PSObject.Properties['id'] -and $null -ne $tg.id) {
            $sid = ([string]$tg.id).Trim()
            if (-not [string]::IsNullOrWhiteSpace($sid)) { return ('id: ' + $sid) }
        }
    }
    return ''
}

function Hub-QueueControlExtractCalendarLabel {
    <# Подключённый календарь очереди (Engine / UI): calendar, calendars, time_calendar и т.п. #>
    param($It)
    if ($null -eq $It) { return '' }
    foreach ($key in @('calendar', 'Calendar', 'calendars', 'Calendars', 'time_calendar', 'TimeCalendar', 'working_calendar', 'WorkingCalendar', 'schedule_calendar', 'calendar_id', 'CalendarId')) {
        if (-not ($It.PSObject.Properties[$key])) { continue }
        $tg = $It.$key
        if ($null -eq $tg) { continue }
        if (($key -eq 'calendar_id' -or $key -eq 'CalendarId') -and ($tg -is [int] -or $tg -is [long] -or $tg -is [double] -or $tg -is [decimal])) {
            return ('id: ' + [string]$tg)
        }
        if ($tg -is [string]) {
            $s = [string]$tg
            if (-not [string]::IsNullOrWhiteSpace($s)) { return $s }
            continue
        }
        if ($tg -is [System.Collections.IEnumerable] -and $tg -isnot [string]) {
            $parts = New-Object System.Collections.Generic.List[string]
            foreach ($el in @($tg)) {
                if ($null -eq $el) { continue }
                foreach ($nk in @('name', 'display_name', 'title')) {
                    if ($el.PSObject.Properties[$nk] -and -not [string]::IsNullOrWhiteSpace([string]$el.$nk)) {
                        [void]$parts.Add([string]$el.$nk)
                        break
                    }
                }
            }
            if ($parts.Count -gt 0) { return [string]::Join('; ', @($parts.ToArray())) }
            continue
        }
        foreach ($nk in @('name', 'display_name', 'title')) {
            if ($tg.PSObject.Properties[$nk] -and -not [string]::IsNullOrWhiteSpace([string]$tg.$nk)) {
                return [string]$tg.$nk
            }
        }
        if ($tg.PSObject.Properties['id'] -and $null -ne $tg.id) {
            $sid = ([string]$tg.id).Trim()
            if (-not [string]::IsNullOrWhiteSpace($sid)) { return ('id: ' + $sid) }
        }
    }
    return ''
}

function Hub-QueueControlCanonicalCalendarIdString {
    param($V)
    if ($null -eq $V) { return '' }
    if ($V -is [int] -or $V -is [long] -or $V -is [double] -or $V -is [decimal]) {
        return ([string][int64]$V)
    }
    $s = ([string]$V).Trim()
    if ($s -match '^[0-9]+$') { return $s }
    return ''
}

function Hub-QueueControlExtractCalendarId {
    <# Числовой id календаря для UI /lookups/calendars/{id}/general #>
    param($It)
    if ($null -eq $It) { return '' }
    foreach ($key in @('calendar_id', 'time_calendar_id', 'schedule_calendar_id')) {
        if (-not ($It.PSObject.Properties[$key])) { continue }
        $sid = Hub-QueueControlCanonicalCalendarIdString $It.$key
        if (-not [string]::IsNullOrWhiteSpace($sid)) { return $sid }
    }
    foreach ($key in @('calendar', 'Calendar', 'time_calendar', 'TimeCalendar', 'working_calendar', 'WorkingCalendar', 'schedule_calendar')) {
        if (-not ($It.PSObject.Properties[$key])) { continue }
        $tg = $It.$key
        if ($null -eq $tg) { continue }
        $sid = Hub-QueueControlCanonicalCalendarIdString $tg
        if (-not [string]::IsNullOrWhiteSpace($sid)) { return $sid }
        if ($tg.PSObject.Properties['id'] -and $null -ne $tg.id) {
            $sid = Hub-QueueControlCanonicalCalendarIdString $tg.id
            if (-not [string]::IsNullOrWhiteSpace($sid)) { return $sid }
        }
    }
    foreach ($arrKey in @('calendars', 'Calendars')) {
        if (-not ($It.PSObject.Properties[$arrKey]) -or $null -eq $It.$arrKey) { continue }
        foreach ($el in @($It.$arrKey)) {
            if ($null -eq $el) { continue }
            if ($el.PSObject.Properties['id'] -and $null -ne $el.id) {
                $sid = Hub-QueueControlCanonicalCalendarIdString $el.id
                if (-not [string]::IsNullOrWhiteSpace($sid)) { return $sid }
            }
        }
    }
    return ''
}

function Hub-QueueControlNormalizeWebitelUiBaseUrl {
    param([string]$HostRaw)
    $u = $HostRaw.Trim().TrimEnd('/')
    if ([string]::IsNullOrWhiteSpace($u)) { return '' }
    if ($u -notmatch '^https?://') { $u = 'https://' + $u.TrimStart('/') }
    if ($u -match '/api/?$') { $u = $u -replace '/api/?$', '' }
    return $u
}

function Hub-QueueControlOpenQueueParametersInBrowser {
    param($RowTag)
    if ($null -eq $RowTag) { return }
    $qk = ''
    $qid = ''
    try { $qk = [string]$RowTag.CompanyKey } catch { }
    try { $qid = ([string]$RowTag.QueueId).Trim() } catch { }
    if ([string]::IsNullOrWhiteSpace($qk) -or [string]::IsNullOrWhiteSpace($qid)) { return }
    $c = $script:Companies.$qk
    if (-not $c) { return }
    $base = Hub-QueueControlNormalizeWebitelUiBaseUrl -HostRaw ([string]$c.webitel_host)
    if ([string]::IsNullOrWhiteSpace($base)) { return }
    $url = ($base + '/contact-center/queues/' + $qid + '/parameters')
    try {
        Start-Process -FilePath $url
    } catch {
        if ($null -ne $script:TxtLog) { Append-Log ('Очередь: не удалось открыть URL: ' + [string]$_.Exception.Message) }
    }
}

function Hub-QueueControlOpenCalendarLookupInBrowser {
    param($RowTag)
    if ($null -eq $RowTag) { return }
    $qk = ''
    $cid = ''
    try { $qk = [string]$RowTag.CompanyKey } catch { }
    try { $cid = ([string]$RowTag.CalendarId).Trim() } catch { }
    if ([string]::IsNullOrWhiteSpace($qk) -or [string]::IsNullOrWhiteSpace($cid)) { return }
    $c = $script:Companies.$qk
    if (-not $c) { return }
    $base = Hub-QueueControlNormalizeWebitelUiBaseUrl -HostRaw ([string]$c.webitel_host)
    if ([string]::IsNullOrWhiteSpace($base)) { return }
    $url = ($base + '/lookups/calendars/' + $cid + '/general')
    try {
        Start-Process -FilePath $url
    } catch {
        if ($null -ne $script:TxtLog) { Append-Log ('Календарь: не удалось открыть URL: ' + [string]$_.Exception.Message) }
    }
}

function Hub-QueueControlParseSchemaFieldValue {
    <# Из поля очереди (id, объект с id/name или строка-имя) — id для /flow/{id}/chat и подпись для ячейки. #>
    param($V)
    $empty = @{ Id = ''; Label = '' }
    if ($null -eq $V) { return $empty }
    $id = Hub-QueueControlCanonicalCalendarIdString $V
    if (-not [string]::IsNullOrWhiteSpace($id)) { return @{ Id = $id; Label = $id } }
    if ($V -is [string]) {
        $s = $V.Trim()
        if ([string]::IsNullOrWhiteSpace($s)) { return $empty }
        if ($s -match '^[0-9]+$') { return @{ Id = $s; Label = $s } }
        return @{ Id = ''; Label = $s }
    }
    if ($V.PSObject.Properties['id'] -and $null -ne $V.id) {
        $id2 = Hub-QueueControlCanonicalCalendarIdString $V.id
        $lb = ''
        foreach ($nk in @('name', 'display_name', 'title')) {
            if ($V.PSObject.Properties[$nk] -and -not [string]::IsNullOrWhiteSpace([string]$V.$nk)) {
                $lb = ([string]$V.$nk).Trim()
                break
            }
        }
        if ([string]::IsNullOrWhiteSpace($lb)) { $lb = $id2 }
        return @{ Id = $id2; Label = $lb }
    }
    foreach ($nk in @('name', 'display_name', 'title')) {
        if ($V.PSObject.Properties[$nk] -and -not [string]::IsNullOrWhiteSpace([string]$V.$nk)) {
            return @{ Id = ''; Label = ([string]$V.$nk).Trim() }
        }
    }
    return $empty
}

function Hub-QueueControlExtractSchemaSlot {
    <# Pre-executive / основной Flow / After-executive — разные поля в model.Queue (Webitel Engine). #>
    param(
        $It,
        [Parameter(Mandatory)][ValidateSet('Pre', 'Flow', 'After')][string]$Slot
    )
    $empty = @{ Id = ''; Label = '' }
    if ($null -eq $It) { return $empty }
    $preKeys = @(
        'do_schema',
        'pre_executive_schema', 'pre_executive_flow', 'pre_schema', 'pre_flow', 'pre_flow_id',
        'before_executive_schema', 'before_flow', 'pre_processing_schema', 'pre_call_flow'
    )
    $flowKeys = @(
        'schema',
        'flow_schema', 'processing_flow', 'main_schema', 'flow', 'chat_flow',
        'flow_id', 'schema_id', 'diagram_id', 'chat_flow_id', 'acr_schema', 'routing_flow', 'processing_flow_id'
    )
    $afterKeys = @(
        'after_schema',
        'after_executive_schema', 'after_executive_flow', 'post_schema', 'post_flow',
        'after_flow', 'after_flow_id', 'post_executive_schema', 'time_acw_schema', 'no_answer_flow_id', 'post_call_flow',
        'drop_schema'
    )
    $keys = switch ($Slot) {
        'Pre' { $preKeys }
        'Flow' { $flowKeys }
        'After' { $afterKeys }
    }
    foreach ($key in $keys) {
        if (-not ($It.PSObject.Properties[$key])) { continue }
        $parsed = Hub-QueueControlParseSchemaFieldValue $It.$key
        if (-not [string]::IsNullOrWhiteSpace($parsed.Id) -or -not [string]::IsNullOrWhiteSpace($parsed.Label)) {
            return $parsed
        }
    }
    return $empty
}

function Hub-QueueControlOpenFlowSchemaInBrowser {
    <# Редактор схемы: {webitel_host}/flow/{schemaId}/chat (нужен числовой id). #>
    param(
        [string]$CompanyKey,
        [string]$SchemaId
    )
    $qk = $CompanyKey.Trim()
    $fid = $SchemaId.Trim()
    if ([string]::IsNullOrWhiteSpace($qk) -or [string]::IsNullOrWhiteSpace($fid)) { return }
    $c = $script:Companies.$qk
    if (-not $c) { return }
    $base = Hub-QueueControlNormalizeWebitelUiBaseUrl -HostRaw ([string]$c.webitel_host)
    if ([string]::IsNullOrWhiteSpace($base)) { return }
    $url = ($base.TrimEnd('/') + '/flow/' + $fid + '/chat')
    try {
        Start-Process -FilePath $url
    } catch {
        if ($null -ne $script:TxtLog) { Append-Log ('Схема (flow): не удалось открыть URL: ' + [string]$_.Exception.Message) }
    }
}

function Hub-QueueControlFetchPagedQueuesForCompanyKey {
    <# GET /call_center/queues без фильтра по type (все очереди), с пагинацией. При ошибке — перебор по типам 0…10 (model.QueueType) и слияние. #>
    param([Parameter(Mandatory)][string]$Key)
    $c = $script:Companies.$Key
    if (-not $c) { throw "Нет данных компании: $Key" }
    $hostB = [string]$c.webitel_host
    $tok = [string]$c.access_token
    if ([string]::IsNullOrWhiteSpace($hostB) -or $hostB -match '^PASTE_') { throw 'У компании не задан webitel_host в конфиге.' }
    if ([string]::IsNullOrWhiteSpace($tok) -or $tok -match '^PASTE_') { throw 'У компании не задан access_token.' }
    $size = 300
    <# Поля только из model.Queue.AllowFields (webitel/engine). Левые имена в fields → 400 → падение на минимальный набор без schema/do_schema/after_schema. #>
    $tryFields = @(
        @('id', 'name', 'type', 'enabled', 'team', 'calendar', 'schema', 'do_schema', 'after_schema', 'count', 'waiting', 'active', 'tags', 'resource_groups', 'resources', 'description'),
        @('id', 'name', 'type', 'enabled', 'team', 'calendar', 'schema', 'do_schema', 'after_schema', 'count', 'waiting', 'active'),
        @('id', 'name', 'type', 'enabled', 'team', 'calendar', 'schema', 'do_schema', 'after_schema'),
        @('id', 'name', 'type', 'enabled', 'team', 'calendar', 'calendars'),
        @('id', 'name', 'type', 'enabled', 'team', 'teams', 'team_id', 'calendar', 'calendars'),
        @('id', 'name', 'type', 'enabled', 'team', 'teams', 'team_id'),
        @('id', 'name', 'type', 'enabled', 'team_id'),
        @('id', 'name', 'type', 'enabled')
    )
    $all = New-Object System.Collections.Generic.List[object]
    $page = 1
    $gotAny = $false
    while ($page -le 40) {
        $base = @{ page = $page; size = $size; sort = @('name') }
        $resp = $null
        <# Без fields Engine отдаёт DefaultFields без calendar/schema — колонки пустые. Только явный fields. #>
        foreach ($fld in $tryFields) {
            try {
                $resp = Hub-WebitelRestGet -WebitelHost $hostB -AccessToken $tok -RelativeApiPath '/call_center/queues' -Query ($base + @{ fields = $fld })
                break
            } catch { $resp = $null }
        }
        if ($null -eq $resp) { break }
        $items = @()
        if ($resp.PSObject.Properties['items'] -and $null -ne $resp.items) { $items = @($resp.items) }
        if ($items.Count -eq 0) { break }
        $gotAny = $true
        foreach ($it in $items) { if ($null -ne $it) { [void]$all.Add($it) } }
        if ($items.Count -lt $size) { break }
        $page++
    }
    if ($gotAny) { return @($all.ToArray()) }
    $merged = New-Object System.Collections.Generic.List[object]
    $seen = @{}
    foreach ($tid in @(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10)) {
        $page = 1
        while ($page -le 20) {
            $base = @{ page = $page; size = $size; sort = @('name'); type = @($tid) }
            $resp = $null
            foreach ($fld in $tryFields) {
                try {
                    $resp = Hub-WebitelRestGet -WebitelHost $hostB -AccessToken $tok -RelativeApiPath '/call_center/queues' -Query ($base + @{ fields = $fld })
                    break
                } catch { $resp = $null }
            }
            if ($null -eq $resp) { break }
            $items = @()
            if ($resp.PSObject.Properties['items'] -and $null -ne $resp.items) { $items = @($resp.items) }
            if ($items.Count -eq 0) { break }
            foreach ($it in $items) {
                if ($null -eq $it) { continue }
                $qid = ''
                if ($it.PSObject.Properties['id']) { $qid = ([string]$it.id).Trim() }
                $uk = ($tid.ToString() + '|' + $qid)
                if ([string]::IsNullOrWhiteSpace($qid)) { $uk = ($tid.ToString() + '|' + [Guid]::NewGuid().ToString('N')) }
                if ($seen.ContainsKey($uk)) { continue }
                $seen[$uk] = $true
                [void]$merged.Add($it)
            }
            if ($items.Count -lt $size) { break }
            $page++
        }
    }
    return @($merged.ToArray())
}

function Hub-IntegrityNormalizeQueueNameForMatch {
    <# Маска на Engine может быть с пробелами («Collection G2 Main») — приводим к виду collection_g2_main для сравнения с эталоном collection_g1_main. #>
    param([string]$Name)
    if ([string]::IsNullOrWhiteSpace($Name)) { return '' }
    $s = ([string]$Name).Trim() -replace '\s+', ' '
    $s = $s -replace '\s', '_'
    while ($s.Contains('__')) { $s = $s.Replace('__', '_') }
    return $s.Trim('_').ToLowerInvariant()
}

function Hub-IntegrityQueueNameMatchesExpected {
    param([string]$QueueName, [string]$ExpectedCanonical)
    $qn = Hub-IntegrityNormalizeQueueNameForMatch $QueueName
    $ex = Hub-IntegrityNormalizeQueueNameForMatch $ExpectedCanonical
    if ([string]::IsNullOrWhiteSpace($ex)) { return $false }
    return [string]::Equals($qn, $ex, [StringComparison]::Ordinal)
}

function Hub-IntegrityGetExpectedCollectionQueueNames {
    <# Эталонные имена коллекшен-очередей: Collection_G{1|2|3}_{Main|APTP|BPTP} (отдел Collection, группа G*, тип для обзвона). #>
    $list = New-Object System.Collections.Generic.List[string]
    foreach ($g in @('G1', 'G2', 'G3')) {
        foreach ($t in @('Main', 'APTP', 'BPTP')) {
            [void]$list.Add(('Collection_{0}_{1}' -f $g, $t))
        }
    }
    return @($list.ToArray())
}

function Hub-IntegrityGetExpectedCalendarNames {
    return @('Collection_agent', 'Collection_voicebot', 'Collection_chatbot', 'Collection_24/7')
}

function Hub-IntegrityAddNamesFromCalendarObject {
    param($Obj, [System.Collections.Generic.HashSet[string]]$Set)
    if ($null -eq $Obj -or $null -eq $Set) { return }
    if ($Obj -is [string]) {
        $s = ([string]$Obj).Trim()
        if (-not [string]::IsNullOrWhiteSpace($s)) { [void]$Set.Add($s) }
        return
    }
    if ($Obj -is [System.Collections.IEnumerable] -and $Obj -isnot [string]) {
        foreach ($el in @($Obj)) { Hub-IntegrityAddNamesFromCalendarObject -Obj $el -Set $Set }
        return
    }
    if ($Obj.PSObject.Properties) {
        foreach ($nk in @('name', 'display_name', 'title')) {
            if ($Obj.PSObject.Properties[$nk] -and -not [string]::IsNullOrWhiteSpace([string]$Obj.$nk)) {
                [void]$Set.Add([string]$Obj.$nk.Trim())
                return
            }
        }
    }
}

function Hub-IntegrityHarvestCalendarNamesFromQueues {
    param([object[]]$Queues)
    $set = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($q in @($Queues)) {
        if ($null -eq $q) { continue }
        $lab = Hub-QueueControlExtractCalendarLabel $q
        foreach ($part in ($lab -split ';')) {
            $p = $part.Trim()
            if ($p -match '^\s*id:') { continue }
            if (-not [string]::IsNullOrWhiteSpace($p)) { [void]$set.Add($p) }
        }
        foreach ($key in @('calendar', 'calendars', 'time_calendar', 'working_calendar')) {
            if ($q.PSObject.Properties[$key] -and $null -ne $q.$key) {
                Hub-IntegrityAddNamesFromCalendarObject -Obj $q.$key -Set $set
            }
        }
    }
    return $set
}

function Hub-IntegrityFetchCalendarNamesFromLookups {
    <# Список календарей из Engine (lookups / call_center); имена объединяются с привязками из очередей. #>
    param([Parameter(Mandatory)][string]$Key)
    $c = $script:Companies.$Key
    if (-not $c) { return [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase) }
    $hostB = [string]$c.webitel_host
    $tok = [string]$c.access_token
    $merged = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    if ([string]::IsNullOrWhiteSpace($hostB) -or $hostB -match '^PASTE_') { return $merged }
    if ([string]::IsNullOrWhiteSpace($tok) -or $tok -match '^PASTE_') { return $merged }
    $size = 300
    $tryFields = @(
        @('id', 'name'),
        @('id', 'title', 'name'),
        @('name')
    )
    foreach ($rel in @('/lookups/calendars', '/call_center/calendars')) {
        $page = 1
        while ($page -le 40) {
            $base = @{ page = $page; size = $size; sort = @('name') }
            $resp = $null
            foreach ($fld in $tryFields) {
                try {
                    $resp = Hub-WebitelRestGet -WebitelHost $hostB -AccessToken $tok -RelativeApiPath $rel -Query ($base + @{ fields = $fld })
                    break
                } catch { $resp = $null }
            }
            if ($null -eq $resp) { break }
            $items = Hub-QueueControlExtractPagedItems $resp
            if ($items.Count -eq 0) { break }
            foreach ($it in $items) {
                foreach ($nk in @('name', 'title', 'display_name')) {
                    if ($it.PSObject.Properties[$nk] -and -not [string]::IsNullOrWhiteSpace([string]$it.$nk)) {
                        [void]$merged.Add([string]$it.$nk.Trim())
                        break
                    }
                }
            }
            if ($items.Count -lt $size) { break }
            $page++
        }
    }
    return $merged
}

function Hub-IntegrityMergeCalendarNameSets {
    <# Имена параметров не -A/-B: в вызовах вида «-A $x» PowerShell может воспринимать -A иначе. #>
    param(
        [System.Collections.Generic.HashSet[string]]$SetA,
        [System.Collections.Generic.HashSet[string]]$SetB
    )
    $out = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    if ($null -ne $SetA) { foreach ($x in $SetA) { if (-not [string]::IsNullOrWhiteSpace([string]$x)) { [void]$out.Add([string]$x) } } }
    if ($null -ne $SetB) { foreach ($x in $SetB) { if (-not [string]::IsNullOrWhiteSpace([string]$x)) { [void]$out.Add([string]$x) } } }
    return $out
}

function Hub-IntegrityQueueIsPredictiveDialer {
    <# Сопоставление эталонных Collection_* — только с очередями Webitel model.QueueType = Predictive dialer (5). #>
    param($QueueItem)
    if ($null -eq $QueueItem) { return $false }
    try {
        $tid = Hub-QueueControlExtractQueueTypeId $QueueItem
        if ($null -eq $tid) { return $false }
        return ([int]$tid -eq [int]$script:WebitelQueueTypePredictiveDialer)
    } catch { return $false }
}

function Hub-IntegrityFindQueueDisplayOnEngine {
    <# Если среди очередей типа Predictive dialer есть имя, совпадающее с эталоном (в т.ч. с пробелами вместо подчёркиваний) — возвращаем имя из API; иначе пусто. Очереди других типов не рассматриваются. #>
    param(
        [object[]]$Queues,
        [string]$Expected
    )
    if ([string]::IsNullOrWhiteSpace($Expected)) { return '' }
    foreach ($it in @($Queues)) {
        if ($null -eq $it) { continue }
        if (-not (Hub-IntegrityQueueIsPredictiveDialer $it)) { continue }
        if (-not ($it.PSObject.Properties['name']) -or $null -eq $it.name) { continue }
        $n = ([string]$it.name).Trim()
        if (Hub-IntegrityQueueNameMatchesExpected -QueueName $n -Expected $Expected) { return $n }
    }
    return ''
}

function Hub-IntegrityDisplayCalendarIfPresent {
    param([System.Collections.Generic.HashSet[string]]$CalSet, [string]$Expected)
    if ($null -eq $CalSet -or [string]::IsNullOrWhiteSpace($Expected)) { return '' }
    if (-not $CalSet.Contains($Expected)) { return '' }
    return $Expected
}

function Hub-IntegrityAddChecklistRow {
    param(
        [Parameter(Mandatory)]$Dgv,
        [Parameter(Mandatory)][string]$Company,
        [Parameter(Mandatory)][string]$Kind,
        [Parameter(Mandatory)][string]$Expected,
        [Parameter(Mandatory)][string]$OnEngine,
        [Parameter(Mandatory)][bool]$Present,
        [string]$Note = ''
    )
    $dot = [string][char]0x25CF
    $sta = ''
    if ($Kind -eq 'Очередь' -or $Kind -eq 'Календарь') { $sta = $dot }
    $ix = $Dgv.Rows.Add($Company, $Kind, $Expected, $OnEngine, $sta, $Note)
    $row = $Dgv.Rows[$ix]
    $green = [System.Drawing.Color]::FromArgb(22, 163, 74)
    $red = [System.Drawing.Color]::FromArgb(220, 38, 38)
    try {
        $cSta = $row.Cells['ColIntStatus']
        if ($Kind -eq 'Очередь' -or $Kind -eq 'Календарь') {
            $fc = $(if ($Present) { $green } else { $red })
            $cSta.Style.ForeColor = $fc
            $cSta.Style.SelectionForeColor = $fc
            $cSta.Style.Font = New-Object System.Drawing.Font('Segoe UI', 12, [System.Drawing.FontStyle]::Bold)
        }
    } catch { }
    return $ix
}

function Hub-IntegrityRefreshGrid {
    if ($null -eq $script:DgvIntegrity) { return }
    $dgv = $script:DgvIntegrity
    $fm = $null
    try { $fm = $dgv.FindForm() } catch { }
    $prevCur = $null
    try {
        if ($null -ne $script:BtnIntegrityRun) { $script:BtnIntegrityRun.Enabled = $false }
        if ($null -ne $fm) {
            $prevCur = $fm.Cursor
            $fm.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
        }
        $dgv.SuspendLayout()
        try { $dgv.Rows.Clear() } catch { }
        $expC = @(Hub-IntegrityGetExpectedCalendarNames)
        $keys = @(Hub-GetQueueControlCompanyKeysFromTree)
        if ($keys.Count -eq 0) {
            [void](Hub-IntegrityAddChecklistRow -Dgv $dgv -Company '—' -Kind '—' -Expected 'Некого проверить' -OnEngine '' -Present $false -Note 'Отметьте галочкой компанию или тип бота в дереве слева (или выделите узел компании/бота).')
        }
        foreach ($k in $keys) {
            if ([string]::IsNullOrWhiteSpace([string]$k)) { continue }
            try {
                $compLab = Hub-FormatCompanyRootLabel $k
                $queues = $null
                $fetchErr = ''
                try {
                    $queues = @(Hub-QueueControlFetchPagedQueuesForCompanyKey -Key $k)
                } catch {
                    $fetchErr = [string]$_.Exception.Message
                }
                if ($fetchErr.Length -gt 0) {
                    [void](Hub-IntegrityAddChecklistRow -Dgv $dgv -Company $compLab -Kind '—' -Expected 'загрузка очередей' -OnEngine '' -Present $false -Note $fetchErr)
                    continue
                }
                $expQ = @(Hub-IntegrityGetExpectedCollectionQueueNames)
                foreach ($e in $expQ) {
                    $on = Hub-IntegrityFindQueueDisplayOnEngine -Queues $queues -Expected $e
                    $ok = (-not [string]::IsNullOrWhiteSpace($on))
                    [void](Hub-IntegrityAddChecklistRow -Dgv $dgv -Company $compLab -Kind 'Очередь' -Expected $e -OnEngine $on -Present $ok -Note '')
                }
                $lk = Hub-IntegrityFetchCalendarNamesFromLookups -Key $k
                $hv = Hub-IntegrityHarvestCalendarNamesFromQueues -Queues $queues
                $calSet = Hub-IntegrityMergeCalendarNameSets -SetA $lk -SetB $hv
                $calNote = ''
                if ($lk.Count -eq 0 -and $hv.Count -gt 0) {
                    $calNote = 'Календари: справочник API пуст; учтены только имена из очередей.'
                }
                $ci = 0
                foreach ($e in $expC) {
                    $onC = Hub-IntegrityDisplayCalendarIfPresent -CalSet $calSet -Expected $e
                    $okC = (-not [string]::IsNullOrWhiteSpace($onC))
                    $noteRow = ''
                    if ($ci -eq 0 -and $calNote.Length -gt 0) { $noteRow = $calNote }
                    [void](Hub-IntegrityAddChecklistRow -Dgv $dgv -Company $compLab -Kind 'Календарь' -Expected $e -OnEngine $onC -Present $okC -Note $noteRow)
                    $ci++
                }
            } catch {
                $compFail = [string]$k
                try { $compFail = Hub-FormatCompanyRootLabel $k } catch { }
                [void](Hub-IntegrityAddChecklistRow -Dgv $dgv -Company $compFail -Kind '—' -Expected 'строка чек-листа' -OnEngine '' -Present $false -Note ([string]$_.Exception.Message))
                if ($null -ne $script:TxtLog) {
                    try { Append-Log ('Целостность ' + [string]$k + ': ' + [string]$_.Exception.Message) } catch { }
                }
            }
        }
        try { $dgv.PerformLayout() } catch { }
        try { $dgv.Refresh() } catch { }
    } catch {
        try {
            [void](Hub-IntegrityAddChecklistRow -Dgv $dgv -Company '—' -Kind '—' -Expected 'Сбой чек-листа' -OnEngine '' -Present $false -Note ([string]$_.Exception.Message))
        } catch { }
        if ($null -ne $script:TxtLog) {
            try { Append-Log ('Целостность (общая ошибка): ' + [string]$_.Exception.Message) } catch { }
        }
    } finally {
        try { $dgv.ResumeLayout() } catch { }
        if ($null -ne $fm -and $null -ne $prevCur) { $fm.Cursor = $prevCur }
        elseif ($null -ne $fm) { $fm.Cursor = [System.Windows.Forms.Cursors]::Default }
        if ($null -ne $script:BtnIntegrityRun) { $script:BtnIntegrityRun.Enabled = $true }
    }
}

function Hub-QueueControlExtractPagedItems {
    param($Resp)
    if ($null -eq $Resp) { return @() }
    if ($Resp.PSObject.Properties['items'] -and $null -ne $Resp.items) { return @($Resp.items) }
    if ($Resp.PSObject.Properties['data']) {
        $d = $Resp.data
        if ($null -ne $d -and $d.PSObject.Properties['items'] -and $null -ne $d.items) { return @($d.items) }
    }
    return @()
}

function Hub-QueueControlMemberStateKey {
    param($It)
    if ($null -eq $It) { return '' }
    $s = ''
    foreach ($p in @('state', 'call_state', 'status')) {
        if ($It.PSObject.Properties[$p] -and $null -ne $It.$p) {
            $s = ([string]$It.$p).Trim()
            break
        }
    }
    if ([string]::IsNullOrWhiteSpace($s) -and $It.PSObject.Properties['attempt'] -and $null -ne $It.attempt) {
        $a = $It.attempt
        if ($null -ne $a -and $a.PSObject.Properties['state'] -and $null -ne $a.state) { $s = ([string]$a.state).Trim() }
    }
    if ($s -match '^[0-9]+$') { return '' }
    return $s.ToLowerInvariant()
}

function Hub-QueueControlCountMembersActiveWaiting {
    param([System.Collections.IList]$Items)
    $activeStates = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($x in @('active', 'offering', 'bridged', 'processing')) { [void]$activeStates.Add($x) }
    $waitStates = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($x in @('waiting', 'joined', 'wait_agent')) { [void]$waitStates.Add($x) }
    $a = 0; $w = 0
    foreach ($it in @($Items)) {
        if ($null -eq $it) { continue }
        $sk = Hub-QueueControlMemberStateKey -It $it
        if ([string]::IsNullOrWhiteSpace($sk)) { continue }
        if ($activeStates.Contains($sk)) { $a++ }
        elseif ($waitStates.Contains($sk)) { $w++ }
    }
    return @{ Active = $a; Waiting = $w }
}

function Hub-QueueControlFetchMembersForQueue {
    <# GET /call_center/members с фильтром по queue_id (Webitel Engine). Состояния — model.MemberState* в call_center. #>
    param(
        [Parameter(Mandatory)][string]$Key,
        [Parameter(Mandatory)][string]$QueueId
    )
    $c = $script:Companies.$Key
    if (-not $c) { throw "Нет данных компании: $Key" }
    $hostB = [string]$c.webitel_host
    $tok = [string]$c.access_token
    if ([string]::IsNullOrWhiteSpace($hostB) -or $hostB -match '^PASTE_') { throw 'У компании не задан webitel_host в конфиге.' }
    if ([string]::IsNullOrWhiteSpace($tok) -or $tok -match '^PASTE_') { throw 'У компании не задан access_token.' }
    $qidNum = 0
    if (-not [int]::TryParse(([string]$QueueId).Trim(), [ref]$qidNum)) { throw 'Некорректный Id очереди.' }
    $size = 250
    $all = New-Object System.Collections.Generic.List[object]
    $page = 1
    $queryBases = @(
        @{ page = $page; size = $size; sort = @('id'); queue_id = $qidNum },
        @{ page = $page; size = $size; sort = @('id'); queueId = $qidNum },
        @{ page = $page; size = $size; queue_id = $qidNum },
        @{ page = $page; size = $size; queueId = $qidNum }
    )
    $lastErr = ''
    while ($page -le 40) {
        $chunk = $null
        foreach ($qb0 in $queryBases) {
            $qb = [ordered]@{}
            foreach ($k in $qb0.Keys) { $qb[$k] = $qb0[$k] }
            $qb['page'] = $page
            $qb['size'] = $size
            try {
                $resp = Hub-WebitelRestGet -WebitelHost $hostB -AccessToken $tok -RelativeApiPath '/call_center/members' -Query ([hashtable]$qb)
                $chunk = Hub-QueueControlExtractPagedItems -Resp $resp
                $lastErr = ''
                break
            } catch {
                $lastErr = [string]$_.Exception.Message
                $chunk = $null
            }
        }
        if ($null -eq $chunk) {
            if ($page -eq 1 -and -not [string]::IsNullOrWhiteSpace($lastErr)) { throw $lastErr }
            break
        }
        if ($chunk.Count -eq 0) { break }
        foreach ($x in $chunk) { if ($null -ne $x) { [void]$all.Add($x) } }
        if ($chunk.Count -lt $size) { break }
        $page++
    }
    return @($all.ToArray())
}

function Hub-QueueControlIsAgentOnlineFromItem {
    param($It)
    if ($null -eq $It) { return $false }
    foreach ($k in @('online', 'is_online', 'logged_in')) {
        if ($It.PSObject.Properties[$k]) {
            $v = $It.$k
            if ($v -is [bool]) { return [bool]$v }
            $sv = ([string]$v).Trim().ToLowerInvariant()
            if ($sv -in @('true', '1', 'yes')) { return $true }
            if ($sv -in @('false', '0', 'no')) { return $false }
        }
    }
    $st = ''
    foreach ($p in @('status', 'state', 'cc_status', 'presence')) {
        if (-not ($It.PSObject.Properties[$p]) -or $null -eq $It.$p) { continue }
        $raw = $It.$p
        if ($raw -is [string]) { $st = $raw.Trim() }
        elseif ($raw.PSObject.Properties['name'] -and $null -ne $raw.name) { $st = ([string]$raw.name).Trim() }
        elseif ($raw.PSObject.Properties['id'] -and $null -ne $raw.id) { $st = ([string]$raw.id).Trim() }
        if (-not [string]::IsNullOrWhiteSpace($st)) { break }
    }
    $stL = $st.ToLowerInvariant()
    if ($stL -match '^(online|available|idle|ready|free|in_service|logged_in|distribute)') { return $true }
    if ($stL -match '^(offline|logout|not_registered|undefined)$') { return $false }
    return $false
}

function Hub-QueueControlTryAgentCountsFromQueueItem {
    <# Если в объекте очереди уже есть агенты/счётчики — используем без отдельного запроса. #>
    param($It)
    $bad = @{ Total = -1; Online = -1 }
    if ($null -eq $It) { return $bad }
    if ($It.PSObject.Properties['agents'] -and $null -ne $It.agents) {
        $arr = @($It.agents)
        if ($arr.Count -gt 0) {
            $o = 0
            foreach ($a in $arr) { if (Hub-QueueControlIsAgentOnlineFromItem $a) { $o++ } }
            return @{ Total = $arr.Count; Online = $o }
        }
    }
    foreach ($pair in @(
            @{ T = 'agents_count'; O = 'online_agents' }
            @{ T = 'agents_count'; O = 'agents_online' }
            @{ T = 'total_agents'; O = 'logged_agents' }
            @{ T = 'agents_total'; O = 'online_agents' }
        )) {
        if (-not ($It.PSObject.Properties[$pair.T]) -or -not ($It.PSObject.Properties[$pair.O])) { continue }
        try {
            $tv = [int64]$It.($pair.T)
            $ov = [int64]$It.($pair.O)
            if ($tv -ge 0 -and $ov -ge 0 -and $ov -le $tv) { return @{ Total = [int]$tv; Online = [int]$ov } }
        } catch { }
    }
    return $bad
}

function Hub-QueueControlAgentItemBelongsToQueue {
    param($AgentIt, [int]$QueueIdNum)
    if ($null -eq $AgentIt) { return $false }
    foreach ($key in @('queues', 'queue_ids', 'queueIds')) {
        if (-not ($AgentIt.PSObject.Properties[$key]) -or $null -eq $AgentIt.$key) { continue }
        $arr = @($AgentIt.$key)
        if ($arr.Count -eq 0) { continue }
        foreach ($el in $arr) {
            if ($null -eq $el) { continue }
            if ($el -is [int] -or $el -is [long] -or $el -is [double] -or $el -is [decimal]) {
                if ([int64]$el -eq [int64]$QueueIdNum) { return $true }
            }
            elseif ($el -is [string]) {
                $sx = ([string]$el).Trim()
                if ($sx -match '^[0-9]+$' -and [int]$sx -eq $QueueIdNum) { return $true }
            }
            elseif ($el.PSObject.Properties['id'] -and $null -ne $el.id) {
                $sid = Hub-QueueControlCanonicalCalendarIdString $el.id
                $tmp = 0
                if (-not [string]::IsNullOrWhiteSpace($sid) -and [int]::TryParse($sid, [ref]$tmp) -and $tmp -eq $QueueIdNum) { return $true }
            }
            elseif ($el.PSObject.Properties['queue_id'] -and $null -ne $el.queue_id) {
                $sid = Hub-QueueControlCanonicalCalendarIdString $el.queue_id
                $tmp2 = 0
                if (-not [string]::IsNullOrWhiteSpace($sid) -and [int]::TryParse($sid, [ref]$tmp2) -and $tmp2 -eq $QueueIdNum) { return $true }
            }
        }
        return $false
    }
    if ($AgentIt.PSObject.Properties['queue_id'] -and $null -ne $AgentIt.queue_id) {
        $sid = Hub-QueueControlCanonicalCalendarIdString $AgentIt.queue_id
        $tmp3 = 0
        if (-not [string]::IsNullOrWhiteSpace($sid) -and [int]::TryParse($sid, [ref]$tmp3) -and $tmp3 -eq $QueueIdNum) { return $true }
    }
    return $false
}

function Hub-QueueControlFetchAgentsStatsForQueue {
    <# Агенты, привязанные к очереди: GET /call_center/agents с фильтром по queue (варианты имён полей в разных версиях Engine). #>
    param(
        [Parameter(Mandatory)][string]$Key,
        [Parameter(Mandatory)][string]$QueueId
    )
    $out = @{ Total = -1; Online = -1; Ok = $false }
    $c = $script:Companies.$Key
    if (-not $c) { return $out }
    $hostB = [string]$c.webitel_host
    $tok = [string]$c.access_token
    if ([string]::IsNullOrWhiteSpace($hostB) -or $hostB -match '^PASTE_') { return $out }
    if ([string]::IsNullOrWhiteSpace($tok) -or $tok -match '^PASTE_') { return $out }
    $qidNum = 0
    if (-not [int]::TryParse(([string]$QueueId).Trim(), [ref]$qidNum)) { return $out }
    $size = 300
    $rel = '/call_center/agents'
    $queryVariants = @(
        @{ page = 1; size = $size; queue_id = $qidNum },
        @{ page = 1; size = $size; queueId = $qidNum },
        @{ page = 1; size = $size; queue_id = @($qidNum) },
        @{ page = 1; size = $size; 'queues[]' = @($qidNum) }
    )
    foreach ($qb0 in $queryVariants) {
        $page = 1
        $allAgents = New-Object System.Collections.Generic.List[object]
        $gotAnyPage = $false
        while ($page -le 25) {
            $qb = [ordered]@{}
            foreach ($k in $qb0.Keys) { $qb[$k] = $qb0[$k] }
            $qb['page'] = $page
            $qb['size'] = $size
            $resp = $null
            try {
                $resp = Hub-WebitelRestGet -WebitelHost $hostB -AccessToken $tok -RelativeApiPath $rel -Query ([hashtable]$qb)
            } catch {
                $resp = $null
                break
            }
            if ($null -eq $resp) { break }
            $chunk = Hub-QueueControlExtractPagedItems -Resp $resp
            $gotAnyPage = $true
            if ($chunk.Count -eq 0) { break }
            foreach ($x in $chunk) { if ($null -ne $x) { [void]$allAgents.Add($x) } }
            if ($chunk.Count -lt $size) { break }
            $page++
        }
        if (-not $gotAnyPage) { continue }
        $tot = 0
        $onl = 0
        foreach ($ag in $allAgents) {
            if (-not (Hub-QueueControlAgentItemBelongsToQueue -AgentIt $ag -QueueIdNum $qidNum)) { continue }
            $tot++
            if (Hub-QueueControlIsAgentOnlineFromItem $ag) { $onl++ }
        }
        if ($allAgents.Count -gt 0 -and $tot -eq 0) { continue }
        if ($allAgents.Count -eq 0) {
            $out.Total = 0
            $out.Online = 0
            $out.Ok = $true
            return $out
        }
        $out.Total = $tot
        $out.Online = $onl
        $out.Ok = $true
        return $out
    }
    return $out
}

function Hub-QueueControlGetQueueGridBindingKey {
    param($Binding)
    if ($null -eq $Binding) { return '' }
    $ck = ''
    $qid = ''
    try { $ck = ([string]$Binding.CompanyKey).Trim() } catch { }
    try { $qid = ([string]$Binding.QueueId).Trim() } catch { }
    if ([string]::IsNullOrWhiteSpace($qid)) { return '' }
    return ($ck + '|' + $qid)
}

function Hub-QueueControlGetCurrentQueueGridBinding {
    $dgv = $script:DgvQueues
    if ($null -eq $dgv -or $dgv.SelectedRows.Count -eq 0) { return $null }
    $row = $dgv.SelectedRows[0]
    $tag = $row.Tag
    if ($null -eq $tag) { return $null }
    $qk = ''; $qid = ''
    try { $qk = [string]$tag.CompanyKey } catch { }
    try { $qid = [string]$tag.QueueId } catch { }
    if ([string]::IsNullOrWhiteSpace($qid)) { return $null }
    $qn = ''
    try { $qn = [string]$tag.Name } catch { }
    return @{ CompanyKey = $qk.Trim(); QueueId = $qid.Trim(); Name = $qn.Trim() }
}

function Hub-QueueControlRestoreQueueGridSelection {
    param($Binding)
    $dgv = $script:DgvQueues
    if ($null -eq $dgv -or $null -eq $Binding) { return }
    $ck = [string]$Binding.CompanyKey
    $qid = [string]$Binding.QueueId
    foreach ($r in $dgv.Rows) {
        $t = $r.Tag
        if ($null -eq $t) { continue }
        try {
            if ([string]$t.CompanyKey -eq $ck -and [string]$t.QueueId -eq $qid) {
                $dgv.ClearSelection()
                $r.Selected = $true
                try { $dgv.FirstDisplayedScrollingRowIndex = $r.Index } catch { }
                return
            }
        } catch { }
    }
}

function Hub-QueueControlSetQueueMetricsUi {
    param(
        [string]$Head,
        [int]$Active,
        [int]$Waiting,
        [string]$ErrorText,
        [int]$AgentsTotal = -1,
        [int]$AgentsOnline = -1
    )
    if ($null -eq $script:DgvQueueMetrics) { return }
    $dg = $script:DgvQueueMetrics
    if ($null -ne $script:LblQueuesDetailHead) {
        $script:LblQueuesDetailHead.Text = $(if ([string]::IsNullOrWhiteSpace($Head)) { 'Метрики очереди' } else { $Head })
        $script:LblQueuesDetailHead.ForeColor = $(if ([string]::IsNullOrWhiteSpace($ErrorText)) { $script:HubUiInk } else { [System.Drawing.Color]::FromArgb(185, 28, 28) })
    }
    $dg.SuspendLayout()
    try {
        $dg.Rows.Clear()
        $av = $(if ([string]::IsNullOrWhiteSpace($ErrorText)) { [string]$Active } else { '—' })
        $wv = $(if ([string]::IsNullOrWhiteSpace($ErrorText)) { [string]$Waiting } else { '—' })
        $agT = $(if ([string]::IsNullOrWhiteSpace($ErrorText)) { $(if ($AgentsTotal -ge 0) { [string]$AgentsTotal } else { 'н/д' }) } else { '—' })
        $agO = $(if ([string]::IsNullOrWhiteSpace($ErrorText)) { $(if ($AgentsOnline -ge 0) { [string]$AgentsOnline } else { 'н/д' }) } else { '—' })
        [void]$dg.Rows.Add('Active calls', $av)
        [void]$dg.Rows.Add('Waiting', $wv)
        [void]$dg.Rows.Add('Агентов в очереди', $agT)
        [void]$dg.Rows.Add('Сейчас онлайн', $agO)
        if (-not [string]::IsNullOrWhiteSpace($ErrorText)) {
            [void]$dg.Rows.Add('Ошибка API', $ErrorText)
        }
    } finally {
        $dg.ResumeLayout()
    }
}

function Hub-QueueControlRefreshSelectedQueueMetrics {
    $dgv = $script:DgvQueues
    $bind = Hub-QueueControlGetCurrentQueueGridBinding
    if ($null -eq $bind) {
        Hub-QueueControlSetQueueMetricsUi -Head 'Выберите строку очереди в верхней таблице.' -Active 0 -Waiting 0 -ErrorText '' -AgentsTotal -1 -AgentsOnline -1
        return
    }
    $head = ('Очередь: ' + [string]$bind.Name + '  (id ' + [string]$bind.QueueId + ', ' + [string]$bind.CompanyKey + ')')
    $at = -1
    $ao = -1
    if ($null -ne $dgv -and $dgv.SelectedRows.Count -gt 0) {
        $tg = $dgv.SelectedRows[0].Tag
        if ($null -ne $tg) {
            try {
                if ($tg.PSObject.Properties['AgentTotalHint']) { $at = [int]$tg.AgentTotalHint }
                if ($tg.PSObject.Properties['AgentOnlineHint']) { $ao = [int]$tg.AgentOnlineHint }
            } catch { }
        }
    }
    try {
        $items = Hub-QueueControlFetchMembersForQueue -Key ([string]$bind.CompanyKey) -QueueId ([string]$bind.QueueId)
        $cnt = Hub-QueueControlCountMembersActiveWaiting -Items $items
        if ($at -lt 0 -or $ao -lt 0) {
            try {
                $stAg = Hub-QueueControlFetchAgentsStatsForQueue -Key ([string]$bind.CompanyKey) -QueueId ([string]$bind.QueueId)
                if ($stAg.Ok) {
                    $at = [int]$stAg.Total
                    $ao = [int]$stAg.Online
                }
            } catch { }
        }
        Hub-QueueControlSetQueueMetricsUi -Head $head -Active ([int]$cnt.Active) -Waiting ([int]$cnt.Waiting) -ErrorText '' -AgentsTotal $at -AgentsOnline $ao
    } catch {
        Hub-QueueControlSetQueueMetricsUi -Head $head -Active 0 -Waiting 0 -ErrorText ([string]$_.Exception.Message) -AgentsTotal -1 -AgentsOnline -1
    }
}

function Hub-QueueControlConfigureQueuesAutoTimer {
    if ($null -eq $script:TimerQueuesAuto -or $null -eq $script:CmbQueuesAutoRefresh) { return }
    $ix = [int]$script:CmbQueuesAutoRefresh.SelectedIndex
    $ms = 0
    switch ($ix) {
        1 { $ms = 10000 }
        2 { $ms = 30000 }
        3 { $ms = 60000 }
        4 { $ms = 1800000 }
        5 { $ms = 3600000 }
        6 { $ms = 10800000 }
        Default { $ms = 0 }
    }
    $script:TimerQueuesAuto.Stop()
    if ($ms -gt 0) {
        $script:TimerQueuesAuto.Interval = $ms
        $script:TimerQueuesAuto.Start()
        try {
            Hub-QueueControlRefreshFromTreeSelection -Silent -Async
        } catch { }
    }
}

function Hub-QueueControlBuildRowsForCompany {
    param(
        [Parameter(Mandatory)][string]$Key,
        [System.Collections.IList]$Items,
        [string]$ErrorText
    )
    $rows = New-Object System.Collections.Generic.List[object]
    $c = $script:Companies.$Key
    $nm = if ($c) { [string]$c.name } else { '' }
    $cc = if ($c) { [string]$c.country } else { '' }
    $comp = $Key + $(if ($nm) { ' — ' + $nm } else { '' }) + $(if ($cc) { ' (' + $cc + ')' } else { '' })
    if (-not [string]::IsNullOrWhiteSpace($ErrorText)) {
        [void]$rows.Add([pscustomobject]@{
                CompanyKey = $Key; CompanyLabel = $comp; QueueId = ''; Name = '(ошибка загрузки)'; TypeId = $null
                TypeCaption = '—'; Status = $ErrorText; Team = ''; Calendar = ''; CalendarId = ''
                SchemaPreId = ''; SchemaPreLabel = ''; SchemaFlowId = ''; SchemaFlowLabel = ''; SchemaAfterId = ''; SchemaAfterLabel = ''
                AgentTotalHint = -1; AgentOnlineHint = -1
            })
        return @($rows.ToArray())
    }
    foreach ($it in @($Items)) {
        if ($null -eq $it) { continue }
        $qid = ''
        if ($it.PSObject.Properties['id']) { $qid = ([string]$it.id).Trim() }
        $qn = ''
        if ($it.PSObject.Properties['name']) { $qn = ([string]$it.name).Trim() }
        $tid = Hub-QueueControlExtractQueueTypeId $it
        $tLab = Hub-QueueControlWebitelTypeLabel $tid
        $tCap = if ($null -eq $tid) { $tLab } else { ([string]$tid + ' — ' + $tLab) }
        $pre = Hub-QueueControlExtractSchemaSlot -It $it -Slot Pre
        $fl = Hub-QueueControlExtractSchemaSlot -It $it -Slot Flow
        $aft = Hub-QueueControlExtractSchemaSlot -It $it -Slot After
        $agc = Hub-QueueControlTryAgentCountsFromQueueItem $it
        [void]$rows.Add([pscustomobject]@{
                CompanyKey = $Key; CompanyLabel = $comp; QueueId = $qid; Name = $qn; TypeId = $tid
                TypeCaption = $tCap; Status = (Hub-QueueControlQueueEnabledText $it); Team = (Hub-QueueControlExtractTeamLabel $it)
                Calendar = (Hub-QueueControlExtractCalendarLabel $it); CalendarId = (Hub-QueueControlExtractCalendarId $it)
                SchemaPreId = [string]$pre.Id; SchemaPreLabel = [string]$pre.Label
                SchemaFlowId = [string]$fl.Id; SchemaFlowLabel = [string]$fl.Label
                SchemaAfterId = [string]$aft.Id; SchemaAfterLabel = [string]$aft.Label
                AgentTotalHint = [int]$agc.Total; AgentOnlineHint = [int]$agc.Online
            })
    }
    return @($rows.ToArray())
}

function Hub-QueueControlGetSelectedTeamFilterSpec {
    if ($null -eq $script:CmbQueuesTeamFilter) { return @{ Mode = 'all' } }
    $ix = [int]$script:CmbQueuesTeamFilter.SelectedIndex
    if ($ix -le 0) { return @{ Mode = 'all' } }
    $txt = [string]$script:CmbQueuesTeamFilter.SelectedItem
    if ($txt -eq $script:QueueControlTeamFilterEmptyLabel) { return @{ Mode = 'empty' } }
    return @{ Mode = 'exact'; Text = $txt.Trim() }
}

function Hub-QueueControlRowMatchesFilters {
    param($Row, $TypeIdFilter, $TeamSpec)
    if ($null -eq $Row) { return $false }
    if ($null -ne $TypeIdFilter) {
        $rid = $null
        try { if ($Row.PSObject.Properties['TypeId']) { $rid = $Row.TypeId } } catch { }
        if ($null -eq $rid) { return $false }
        if ([int]$rid -ne [int]$TypeIdFilter) { return $false }
    }
    if ($null -eq $TeamSpec -or -not ($TeamSpec.ContainsKey('Mode')) -or $TeamSpec.Mode -eq 'all') { return $true }
    $tm = ''
    try { $tm = [string]$Row.Team } catch { }
    $tmT = $tm.Trim()
    if ($TeamSpec.Mode -eq 'empty') {
        return [string]::IsNullOrWhiteSpace($tmT)
    }
    if ($TeamSpec.Mode -eq 'exact') {
        return ($tmT -eq [string]$TeamSpec.Text)
    }
    return $true
}

function Hub-QueueControlRebuildTeamFilterCombo {
    if ($null -eq $script:CmbQueuesTeamFilter) { return }
    $prev = ''
    if ($script:CmbQueuesTeamFilter.SelectedIndex -gt 0) {
        try { $prev = [string]$script:CmbQueuesTeamFilter.SelectedItem } catch { }
    }
    $script:CmbQueuesTeamFilter.BeginUpdate()
    try {
        $script:CmbQueuesTeamFilter.Items.Clear()
        [void]$script:CmbQueuesTeamFilter.Items.Add('Все команды (Team)')
        [void]$script:CmbQueuesTeamFilter.Items.Add($script:QueueControlTeamFilterEmptyLabel)
        $set = New-Object 'System.Collections.Generic.HashSet[string]'
        foreach ($r in @($script:QueueControlAllRows)) {
            $t = ''
            try { $t = [string]$r.Team } catch { }
            $t = $t.Trim()
            if ([string]::IsNullOrWhiteSpace($t)) { continue }
            if (-not $set.Contains($t)) { [void]$set.Add($t) }
        }
        foreach ($s in @($set | Sort-Object)) {
            [void]$script:CmbQueuesTeamFilter.Items.Add($s)
        }
        $newIx = 0
        if (-not [string]::IsNullOrWhiteSpace($prev)) {
            for ($i = 0; $i -lt $script:CmbQueuesTeamFilter.Items.Count; $i++) {
                if ([string]$script:CmbQueuesTeamFilter.Items[$i] -eq $prev) { $newIx = $i; break }
            }
        }
        $script:CmbQueuesTeamFilter.SelectedIndex = [Math]::Min($newIx, [Math]::Max(0, $script:CmbQueuesTeamFilter.Items.Count - 1))
    } finally {
        $script:CmbQueuesTeamFilter.EndUpdate()
    }
}

function Hub-QueueControlApplyFiltersToGrid {
    param(
        [hashtable]$PrefetchedMetrics = $null,
        [string]$PrefetchedMetricsBindingKey = ''
    )
    $dgv = $script:DgvQueues
    if ($null -eq $dgv) { return }
    $bindSave = Hub-QueueControlGetCurrentQueueGridBinding
    $typeF = Hub-QueueControlGetSelectedTypeFilterId
    $teamS = Hub-QueueControlGetSelectedTeamFilterSpec
    $script:QueueControlInGridRestore = $true
    try {
        $dgv.SuspendLayout()
        try {
            $dgv.Rows.Clear()
            foreach ($r in @($script:QueueControlAllRows)) {
                if (-not (Hub-QueueControlRowMatchesFilters -Row $r -TypeIdFilter $typeF -TeamSpec $teamS)) { continue }
                $cal = ''
                try { $cal = [string]$r.Calendar } catch { }
                $preTxt = ''; $preId = ''
                try { $preId = ([string]$r.SchemaPreId).Trim() } catch { }
                try { $preTxt = ([string]$r.SchemaPreLabel).Trim() } catch { }
                if ([string]::IsNullOrWhiteSpace($preTxt)) { $preTxt = $preId }
                $flTxt = ''; $flId = ''
                try { $flId = ([string]$r.SchemaFlowId).Trim() } catch { }
                try { $flTxt = ([string]$r.SchemaFlowLabel).Trim() } catch { }
                if ([string]::IsNullOrWhiteSpace($flTxt)) { $flTxt = $flId }
                $aftTxt = ''; $aftId = ''
                try { $aftId = ([string]$r.SchemaAfterId).Trim() } catch { }
                try { $aftTxt = ([string]$r.SchemaAfterLabel).Trim() } catch { }
                if ([string]::IsNullOrWhiteSpace($aftTxt)) { $aftTxt = $aftId }
                $hasAnySchema = (-not [string]::IsNullOrWhiteSpace($preId)) -or (-not [string]::IsNullOrWhiteSpace($flId)) -or (-not [string]::IsNullOrWhiteSpace($aftId)) -or
                    (-not [string]::IsNullOrWhiteSpace($preTxt)) -or (-not [string]::IsNullOrWhiteSpace($flTxt)) -or (-not [string]::IsNullOrWhiteSpace($aftTxt))
                $schemasCellVal = $(if ($hasAnySchema) { 'Schemas' } else { '' })
                [void]$dgv.Rows.Add(
                    [string]$r.CompanyLabel,
                    [string]$r.QueueId,
                    ([string]$r.Name),
                    $cal,
                    $schemasCellVal,
                    [string]$r.TypeCaption,
                    [string]$r.Status,
                    [string]$r.Team)
                try {
                    $nr = $dgv.Rows[$dgv.Rows.Count - 1]
                    $nr.Tag = $r
                    $cid = ''
                    try { $cid = ([string]$r.CalendarId).Trim() } catch { }
                    $cCal = $nr.Cells['ColQCalendar']
                    if ($null -ne $cCal -and $cCal -is [System.Windows.Forms.DataGridViewLinkCell]) {
                        if ([string]::IsNullOrWhiteSpace($cid)) {
                            $cCal.LinkBehavior = [System.Windows.Forms.LinkBehavior]::NeverUnderline
                            $cCal.LinkColor = $script:HubUiInk
                            $cCal.ActiveLinkColor = $script:HubUiInk
                            $cCal.VisitedLinkColor = $script:HubUiInk
                        }
                    }
                    $cSch = $nr.Cells['ColQSchemas']
                    if ($null -ne $cSch -and $cSch -is [System.Windows.Forms.DataGridViewLinkCell]) {
                        if (-not $hasAnySchema) {
                            $cSch.LinkBehavior = [System.Windows.Forms.LinkBehavior]::NeverUnderline
                            $cSch.LinkColor = $script:HubUiInk
                            $cSch.ActiveLinkColor = $script:HubUiInk
                            $cSch.VisitedLinkColor = $script:HubUiInk
                        }
                    }
                } catch { }
            }
        } finally {
            $dgv.ResumeLayout()
        }
        Hub-QueueControlRestoreQueueGridSelection $bindSave
    } finally {
        $script:QueueControlInGridRestore = $false
    }
    try { Hub-QueuesApplyDgvColumnWidths } catch { }
    if ($null -ne $PrefetchedMetrics) {
        $kNow = Hub-QueueControlGetQueueGridBindingKey (Hub-QueueControlGetCurrentQueueGridBinding)
        if (-not [string]::IsNullOrWhiteSpace($PrefetchedMetricsBindingKey) -and $kNow -eq $PrefetchedMetricsBindingKey) {
            try {
                $pAt = -1
                $pAo = -1
                try {
                    if ($PrefetchedMetrics.ContainsKey('AgentsTotal')) { $pAt = [int]$PrefetchedMetrics.AgentsTotal }
                    if ($PrefetchedMetrics.ContainsKey('AgentsOnline')) { $pAo = [int]$PrefetchedMetrics.AgentsOnline }
                } catch { }
                Hub-QueueControlSetQueueMetricsUi `
                    -Head ([string]$PrefetchedMetrics.Head) `
                    -Active ([int]$PrefetchedMetrics.Active) `
                    -Waiting ([int]$PrefetchedMetrics.Waiting) `
                    -ErrorText ([string]$PrefetchedMetrics.ErrorText) `
                    -AgentsTotal $pAt -AgentsOnline $pAo
            } catch { }
        } else {
            try { Hub-QueueControlRefreshSelectedQueueMetrics } catch { }
        }
    } else {
        try { Hub-QueueControlRefreshSelectedQueueMetrics } catch { }
    }
}

function Hub-QueuesApplyDgvColumnWidths {
    $dgv = $script:DgvQueues
    if ($null -eq $dgv) { return }
    $cw = [int]$dgv.ClientSize.Width
    if ($cw -lt 120) { return }
    $c0 = $dgv.Columns['ColQCompany']
    $c1 = $dgv.Columns['ColQId']
    $c2 = $dgv.Columns['ColQName']
    $c2b = $dgv.Columns['ColQCalendar']
    $c2sch = $dgv.Columns['ColQSchemas']
    $c3 = $dgv.Columns['ColQType']
    $c4 = $dgv.Columns['ColQStatus']
    $c5 = $dgv.Columns['ColQTeam']
    if ($null -eq $c0 -or $null -eq $c1 -or $null -eq $c2 -or $null -eq $c2b -or $null -eq $c2sch -or $null -eq $c3 -or $null -eq $c4 -or $null -eq $c5) { return }
    $c2.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::Fill
    $c0.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::None
    $c1.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::None
    $c2b.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::None
    $c2sch.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::None
    $c3.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::None
    $c4.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::None
    $c5.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::None
    $c0.Width = [int]([Math]::Max(96, [Math]::Min(220, [Math]::Floor($cw * 0.15))))
    $c1.Width = [int]([Math]::Max(72, [Math]::Min(110, [Math]::Floor($cw * 0.07))))
    $c2b.Width = [int]([Math]::Max(88, [Math]::Min(160, [Math]::Floor($cw * 0.11))))
    $wSchMerged = [int]([Math]::Max(88, [Math]::Min(200, [Math]::Floor($cw * 0.14))))
    $c2sch.Width = $wSchMerged
    $c3.Width = [int]([Math]::Max(110, [Math]::Min(190, [Math]::Floor($cw * 0.13))))
    $c4.Width = [int]([Math]::Max(80, [Math]::Min(100, [Math]::Floor($cw * 0.08))))
    $c5.Width = [int]([Math]::Max(96, [Math]::Min(170, [Math]::Floor($cw * 0.12))))
}

function Hub-QueueControlRefreshFromTreeSelection {
    param([switch]$Silent, [switch]$Async)
    $keys = @(Hub-GetQueueControlCompanyKeysFromTree)
    if ($keys.Count -eq 0) {
        if (-not $Silent) {
            [void][System.Windows.Forms.MessageBox]::Show(
                'Отметьте галочкой компанию или бота слева — по отмеченным загрузятся очереди. Если ничего не отмечено, выделите строку компании или бота (тогда берётся только выделение).',
                $script:HubAppTitle,
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Information)
        }
        return
    }
    if ($Async) {
        if ($null -eq $script:QueuesRefreshWorker) { return }
        if ($script:QueuesRefreshWorker.IsBusy) { return }
        $bind = Hub-QueueControlGetCurrentQueueGridBinding
        $arg = @{
            Keys       = @($keys)
            Binding    = $bind
            BindingKey = (Hub-QueueControlGetQueueGridBindingKey $bind)
            Silent     = [bool]$Silent
            KeysForLog = ($keys -join ', ')
        }
        $script:QueuesRefreshWorker.RunWorkerAsync($arg)
        return
    }
    $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
    $acc = New-Object System.Collections.Generic.List[object]
    foreach ($k in $keys) {
        try {
            $items = Hub-QueueControlFetchPagedQueuesForCompanyKey -Key $k
            foreach ($row in @(Hub-QueueControlBuildRowsForCompany -Key $k -Items $items -ErrorText '')) {
                [void]$acc.Add($row)
            }
        } catch {
            foreach ($row in @(Hub-QueueControlBuildRowsForCompany -Key $k -Items @() -ErrorText ([string]$_.Exception.Message))) {
                [void]$acc.Add($row)
            }
        }
    }
    $script:QueueControlAllRows = @($acc.ToArray())
    $form.Cursor = [System.Windows.Forms.Cursors]::Default
    Hub-QueueControlRebuildTeamFilterCombo
    Hub-QueueControlApplyFiltersToGrid
    if ($null -ne $script:TxtLog -and -not $Silent) {
        Append-Log ('Очереди: обновлено строк ' + $script:QueueControlAllRows.Count + ' по компаниям: ' + ($keys -join ', ') + '.')
    }
}

function Hub-ChatUnwrapSingleDialogFromApiResponse {
    param($Resp)
    if ($null -eq $Resp) { return $null }
    if ($Resp.PSObject.Properties['data']) {
        $d = $Resp.data
        if ($null -eq $d) { return $null }
        if ($d.PSObject.Properties['items'] -and $null -ne $d.items) {
            $arr = @($d.items)
            if ($arr.Count -gt 0) { return $arr[0] }
        }
        if ($d.PSObject.Properties['id']) { return $d }
        return $d
    }
    if ($Resp.PSObject.Properties['id']) { return $Resp }
    return $Resp
}

function Hub-ChatMergeDialogWithDetail {
    param($Summary, $DetailPayload)
    $det = Hub-ChatUnwrapSingleDialogFromApiResponse $DetailPayload
    if ($null -eq $det) { return $Summary }
    $h = [ordered]@{}
    foreach ($p in $Summary.PSObject.Properties) { $h[$p.Name] = $p.Value }
    foreach ($n in @('member', 'user', 'peer', 'customer', 'contact', 'variables', 'metadata', 'conversation', 'queue', 'queue_id', 'queueId')) {
        if ($det.PSObject.Properties[$n] -and $null -ne $det.$n) {
            $h[$n] = $det.$n
        }
    }
    foreach ($p in $det.PSObject.Properties) {
        if ($h.Contains($p.Name)) { continue }
        $h[$p.Name] = $p.Value
    }
    return ([pscustomobject]$h)
}

function Hub-ChatEnrichDialogsWithDetailIfMissingPhone {
    param(
        [System.Collections.IList]$Dialogs,
        [string]$WebitelHost,
        [string]$AccessToken,
        [int]$MaxDetails = 80
    )
    $script:ChatLastEnrichDetailCalls = 0
    if ($null -eq $Dialogs -or $Dialogs.Count -eq 0) { return @($Dialogs) }
    $calls = 0
    $out = New-Object System.Collections.Generic.List[object]
    foreach ($it in $Dialogs) {
        if ($null -eq $it) {
            [void]$out.Add($it)
            continue
        }
        $ph = Hub-ChatDialogClientPhone $it
        if ((-not [string]::IsNullOrWhiteSpace($ph)) -or $calls -ge $MaxDetails) {
            [void]$out.Add($it)
            continue
        }
        $idKey = [string]$it.id
        if ([string]::IsNullOrWhiteSpace($idKey)) {
            [void]$out.Add($it)
            continue
        }
        try {
            $path = '/chat/dialogs/' + [uri]::EscapeDataString($idKey)
            $raw = Hub-WebitelRestGet -WebitelHost $WebitelHost -AccessToken $AccessToken -RelativeApiPath $path -Query @{}
            $calls++
            [void]$out.Add((Hub-ChatMergeDialogWithDetail -Summary $it -DetailPayload $raw))
        } catch {
            [void]$out.Add($it)
        }
    }
    if ($calls -gt 0 -and $null -ne $script:TxtLog) {
        Append-Log ('Чаты: GET /chat/dialogs/{id} для колонки «Номер»: запросов ' + $calls + ' (в списке /chat/dialogs часто нет member.communications; полная карточка — по документации Member/communications.destination).')
    }
    $script:ChatLastEnrichDetailCalls = $calls
    return $out.ToArray()
}

function Hub-ChatPrefetchQueuesAllCompaniesOnStartup {
    if ($null -eq $script:ProjectKeys -or @($script:ProjectKeys).Count -eq 0) { return }
    $prevCur = $null
    try {
        if ($null -ne $form) {
            $prevCur = $form.Cursor
            $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
        }
        if ($null -ne $script:TxtLog) { Append-Log 'Чаты: автопроверка чат-очередей по всем компаниям…' }
        $ok = 0
        $bad = 0
        foreach ($key in @($script:ProjectKeys)) {
            try {
                $items = Hub-ChatFetchChatQueuesForCompanyKey -Key $key
                $n = @($items).Count
                $ok++
                if ($null -ne $script:TxtLog) { Append-Log ("  [{0}] чат-очередей: {1}" -f $key, $n) }
            } catch {
                $bad++
                if ($null -ne $script:TxtLog) { Append-Log ("  [{0}] ошибка: {1}" -f $key, $_.Exception.Message) }
            }
        }
        if ($null -ne $script:TxtLog) { Append-Log ("Чаты: автопроверка завершена — ОК: {0}, с ошибкой: {1}." -f $ok, $bad) }
    } finally {
        if ($null -ne $form -and $null -ne $prevCur) {
            $form.Cursor = $prevCur
        } elseif ($null -ne $form) {
            $form.Cursor = [System.Windows.Forms.Cursors]::Default
        }
    }
}

function Hub-ChatArchiveSafeFileName {
    param([Parameter(Mandatory)][string]$Key)
    $safe = [regex]::Replace([string]$Key, '[^\w\-\.]+', '_')
    if ([string]::IsNullOrWhiteSpace($safe)) { $safe = 'company' }
    return ($safe + '.json')
}

function Hub-ChatArchiveFilePath {
    param([Parameter(Mandatory)][string]$Key)
    return (Join-Path $script:HubChatsArchiveRoot (Hub-ChatArchiveSafeFileName -Key $Key))
}

function Hub-ChatArchiveLoadStore {
    param([Parameter(Mandatory)][string]$Key)
    Hub-EnsureHubDataDirs
    $p = Hub-ChatArchiveFilePath -Key $Key
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    try {
        $utf8 = New-Object System.Text.UTF8Encoding $false
        $t = [System.IO.File]::ReadAllText($p, $utf8)
        if ([string]::IsNullOrWhiteSpace($t)) { return $null }
        return ($t | ConvertFrom-Json)
    } catch {
        return $null
    }
}

function Hub-ChatArchiveMaxDialogDateMs {
    param($Dialogs)
    [long]$max = 0L
    foreach ($d in @($Dialogs)) {
        if ($null -eq $d) { continue }
        $dtu = Hub-ChatTryParseDialogDateUtc $d
        if ($null -eq $dtu) { continue }
        try {
            $ms = Hub-ChatUtcToUnixMs $dtu
            if ($ms -gt $max) { $max = $ms }
        } catch { }
    }
    return $max
}

function Hub-ChatArchiveMergeDialogsById {
    param($OldDialogs, $NewDialogs)
    $map = @{}
    foreach ($d in @($OldDialogs)) {
        if ($null -eq $d) { continue }
        try {
            $id = [string]$d.id
            if ([string]::IsNullOrWhiteSpace($id)) { continue }
            $map[$id] = $d
        } catch { }
    }
    foreach ($d in @($NewDialogs)) {
        if ($null -eq $d) { continue }
        try {
            $id = [string]$d.id
            if ([string]::IsNullOrWhiteSpace($id)) { continue }
            if (-not $map.ContainsKey($id)) {
                $map[$id] = $d
                continue
            }
            $prior = $map[$id]
            $phN = Hub-ChatDialogClientPhone $d
            $phP = Hub-ChatDialogClientPhone $prior
            if ([string]::IsNullOrWhiteSpace($phN) -and -not [string]::IsNullOrWhiteSpace($phP)) {
                $map[$id] = Hub-ChatMergeDialogWithDetail -Summary $d -DetailPayload $prior
            } else {
                $map[$id] = $d
            }
        } catch { }
    }
    $vals = @($map.Values)
    if ($vals.Count -eq 0) { return @() }
    return @(
        $vals | Sort-Object -Property @{
            Expression = {
                $u = Hub-ChatTryParseDialogDateUtc $_
                if ($null -eq $u) { return [long]0 }
                try { return [long](Hub-ChatUtcToUnixMs $u) } catch { return [long]0 }
            }
        } -Descending
    )
}

function Hub-ChatArchiveUpsertDialogsFromEnriched {
    <# Подмешивает в файл архива обогащённые диалоги (member/communications и т.д.), остальные id не трогает. #>
    param([Parameter(Mandatory)][string]$Key, [object[]]$Enriched)
    if ($null -eq $Enriched -or $Enriched.Count -eq 0) { return }
    $store = Hub-ChatArchiveLoadStore -Key $Key
    if ($null -eq $store) { return }
    $full = @()
    if ($null -ne $store.dialogs) { $full = @($store.dialogs) }
    $patched = Hub-ChatArchiveMergeDialogsById -OldDialogs $full -NewDialogs $Enriched
    [long]$syncUntil = Hub-ChatUtcToUnixMs ([datetime]::UtcNow)
    if ($store.PSObject.Properties['sync_until_ms'] -and $null -ne $store.sync_until_ms) {
        try { $syncUntil = [long][decimal]$store.sync_until_ms } catch { }
    }
    [long]$maxD = Hub-ChatArchiveMaxDialogDateMs $patched
    if ($store.PSObject.Properties['max_dialog_date_ms'] -and $null -ne $store.max_dialog_date_ms) {
        try {
            $m2 = [long][decimal]$store.max_dialog_date_ms
            if ($m2 -gt $maxD) { $maxD = $m2 }
        } catch { }
    }
    Hub-ChatArchiveSaveStore -Key $Key -DialogArray $patched -SyncUntilMs $syncUntil -MaxDialogDateMs $maxD
}

function Hub-ChatArchiveSaveStore {
    param(
        [Parameter(Mandatory)][string]$Key,
        [Parameter(Mandatory)]$DialogArray,
        [long]$SyncUntilMs,
        [long]$MaxDialogDateMs
    )
    Hub-EnsureHubDataDirs
    $p = Hub-ChatArchiveFilePath -Key $Key
    $obj = [ordered]@{
        schema_version      = 1
        company_key         = $Key
        saved_at_utc        = [datetime]::UtcNow.ToString('o', [cultureinfo]::InvariantCulture)
        sync_until_ms       = $SyncUntilMs
        max_dialog_date_ms  = $MaxDialogDateMs
        dialogs             = @($DialogArray)
    }
    $utf8 = New-Object System.Text.UTF8Encoding $false
    $json = ($obj | ConvertTo-Json -Depth 40 -Compress)
    [System.IO.File]::WriteAllText($p, $json, $utf8)
}

function Hub-ChatArchiveSyncCompany {
    <# Инкремент: GET /chat/dialogs с date.since от последнего известного диалога (минус 2 с), до «сейчас». Без фильтра очередей — все чаты компании. #>
    param([Parameter(Mandatory)][string]$Key)
    $c = $script:Companies.$Key
    if (-not $c) { throw "Нет компании $Key" }
    $hostB = [string]$c.webitel_host
    $tok = [string]$c.access_token
    if ([string]::IsNullOrWhiteSpace($hostB) -or $hostB -match '^PASTE_') { throw 'Нет webitel_host' }
    if ([string]::IsNullOrWhiteSpace($tok) -or $tok -match '^PASTE_') { throw 'Нет access_token' }
    $store = Hub-ChatArchiveLoadStore -Key $Key
    $existing = @()
    if ($null -ne $store -and $store.PSObject.Properties['dialogs'] -and $null -ne $store.dialogs) {
        $existing = @($store.dialogs)
    }
    [long]$maxStored = Hub-ChatArchiveMaxDialogDateMs $existing
    if ($null -ne $store -and $store.PSObject.Properties['max_dialog_date_ms'] -and $null -ne $store.max_dialog_date_ms) {
        try {
            $m2 = [long][decimal]$store.max_dialog_date_ms
            if ($m2 -gt $maxStored) { $maxStored = $m2 }
        } catch { }
    }
    [long]$untilMs = Hub-ChatUtcToUnixMs ([datetime]::UtcNow)
    [long]$sinceMs = 0L
    [long]$defaultSpan = 30L * 24L * 3600L * 1000L
    if ($maxStored -gt 0L) {
        $sinceMs = $maxStored - 2000L
        if ($sinceMs -lt 0L) { $sinceMs = 0L }
    } else {
        $sinceMs = $untilMs - $defaultSpan
    }
    if ($sinceMs -ge $untilMs) {
        if ($null -ne $script:TxtLog) { Append-Log ("Чаты-архив [{0}]: пропуск (since>=until, нечего догружать)." -f $Key) }
        return
    }
    $allNew = New-Object System.Collections.ArrayList
    $page = 1
    while ($page -le 50) {
        $qry = @{
            page         = $page
            size         = 80
            'date.since' = [string]$sinceMs
            'date.until' = [string]$untilMs
            sort         = '-date'
        }
        $resp = Hub-WebitelRestGet -WebitelHost $hostB -AccessToken $tok -RelativeApiPath '/chat/dialogs' -Query $qry
        $chunk = Hub-ChatExtractDialogItems $resp
        foreach ($it in $chunk) {
            if ($null -ne $it) { [void]$allNew.Add($it) }
        }
        $hasNext = $false
        if ($null -ne $resp -and $resp.PSObject.Properties['next'] -and $resp.next) { $hasNext = $true }
        if (-not $hasNext -and $null -ne $resp -and $resp.PSObject.Properties['data']) {
            $dN = $resp.data
            if ($null -ne $dN -and $dN.PSObject.Properties['next'] -and $dN.next) { $hasNext = $true }
        }
        if (-not $hasNext) { break }
        if ($chunk.Count -eq 0) { break }
        $page++
    }
    $arrFetched = @($allNew.ToArray())
    if ($arrFetched.Count -gt 0) {
        $detailCap = [Math]::Min(500, [Math]::Max(40, $arrFetched.Count))
        $arrFetched = @(Hub-ChatEnrichDialogsWithDetailIfMissingPhone -Dialogs $arrFetched -WebitelHost $hostB -AccessToken $tok -MaxDetails $detailCap)
    }
    $merged = Hub-ChatArchiveMergeDialogsById -OldDialogs $existing -NewDialogs $arrFetched
    [long]$newMax = Hub-ChatArchiveMaxDialogDateMs $merged
    if ($newMax -lt $maxStored) { $newMax = $maxStored }
    Hub-ChatArchiveSaveStore -Key $Key -DialogArray $merged -SyncUntilMs $untilMs -MaxDialogDateMs $newMax
    if ($null -ne $script:TxtLog) {
        Append-Log ("Чаты-архив [{0}]: окно {1}–{2} мс, получено записей: {3}, в архиве диалогов: {4} → {5}" -f $Key, $sinceMs, $untilMs, $allNew.Count, $existing.Count, $merged.Count)
    }
}

function Hub-ChatArchiveSyncAllCompaniesOnStartup {
    if ($null -eq $script:ProjectKeys -or @($script:ProjectKeys).Count -eq 0) { return }
    $prevCur = $null
    try {
        if ($null -ne $form) {
            $prevCur = $form.Cursor
            $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
        }
        if ($null -ne $script:TxtLog) { Append-Log ('Чаты-архив: папка ' + $script:HubChatsArchiveRoot + ' — инкрементальная выгрузка /chat/dialogs (от последней даты в файле, иначе за 30 суток)…') }
        foreach ($key in @($script:ProjectKeys)) {
            try {
                Hub-ChatArchiveSyncCompany -Key $key
            } catch {
                if ($null -ne $script:TxtLog) { Append-Log ('Чаты-архив [' + $key + ']: ' + $_.Exception.Message) }
            }
        }
        if ($null -ne $script:TxtLog) { Append-Log 'Чаты-архив: цикл выгрузки завершён.' }
    } finally {
        if ($null -ne $form -and $null -ne $prevCur) {
            $form.Cursor = $prevCur
        } elseif ($null -ne $form) {
            $form.Cursor = [System.Windows.Forms.Cursors]::Default
        }
    }
}

function Hub-ChatLoadQueuesForCompanyKey {
    <# Метаданные чат-очередей (имя очереди → колонка «Отдел», фильтр списка). Список диалогов — из архива по периоду. -Quiet: без MessageBox; отмечает все очереди. #>
    param(
        [Parameter(Mandatory)][string]$Key,
        [switch]$Quiet
    )
    $c = $script:Companies.$Key
    if (-not $c) {
        $script:ChatQueuesLoaded = $false
        if ($Quiet) {
            if ($null -ne $script:TxtLog) { Append-Log "Чаты: нет данных компании $Key" }
        } else {
            [void][System.Windows.Forms.MessageBox]::Show("Нет данных компании: $Key", $script:HubAppTitle)
        }
        return $false
    }
    $hostB = [string]$c.webitel_host
    $tok = [string]$c.access_token
    if ([string]::IsNullOrWhiteSpace($hostB) -or $hostB -match '^PASTE_') {
        $script:ChatQueuesLoaded = $false
        if ($Quiet) {
            if ($null -ne $script:TxtLog) { Append-Log "Чаты ($Key): не задан webitel_host" }
        } else {
            [void][System.Windows.Forms.MessageBox]::Show('У компании не задан webitel_host в конфиге.', $script:HubAppTitle)
        }
        return $false
    }
    if ([string]::IsNullOrWhiteSpace($tok) -or $tok -match '^PASTE_') {
        $script:ChatQueuesLoaded = $false
        if ($Quiet) {
            if ($null -ne $script:TxtLog) { Append-Log "Чаты ($Key): не задан access_token" }
        } else {
            [void][System.Windows.Forms.MessageBox]::Show('У компании не задан access_token.', $script:HubAppTitle)
        }
        return $false
    }
    try {
        $script:ChatQueueMeta = @{}
        $script:ChatInboundQueueAllIds.Clear()
        $items = Hub-ChatFetchChatQueuesForCompanyKey -Key $Key
        if ($null -ne $script:ClbChatQueues) {
            try { $script:ClbChatQueues.Items.Clear() } catch { }
        }
        foreach ($it in $items) {
            $id = Hub-ChatNormalizeQueueId $it.id
            if ($id.Length -eq 0) { continue }
            [void]$script:ChatInboundQueueAllIds.Add($id)
            $nm = [string]$it.name
            $en = $it.enabled
            $sgn = Hub-ChatExtractSkillGroupNameFromQueueItem $it
            $lbl = ('[{0}] {1}  (вкл: {2})' -f $id, $nm, $en)
            $script:ChatQueueMeta[$lbl] = @{ Id = $id; Name = $nm; Enabled = $en; SkillGroupName = $sgn }
            if ($null -ne $script:ClbChatQueues) {
                [void]$script:ClbChatQueues.Items.Add($lbl)
            }
        }
        $script:ChatQueueMeta[$script:ChatQueueOutsideListLabel] = @{ Id = '__OUTSIDE__'; Name = 'Вне чат-очереди'; Enabled = $true; Outside = $true }
        if ($null -ne $script:ClbChatQueues) {
            [void]$script:ClbChatQueues.Items.Insert(0, $script:ChatQueueOutsideListLabel)
            if ($Quiet) {
                for ($ix = 1; $ix -lt $script:ClbChatQueues.Items.Count; $ix++) {
                    $script:ClbChatQueues.SetItemChecked($ix, $true)
                }
            }
        }
        $script:ChatQueuesLoaded = $true
        $script:ChatCompanyKey = $Key
        if ($null -ne $script:LblChatCompany) {
            $script:LblChatCompany.Text = ('Компания: ' + $Key + ' — ' + [string]$c.name + '  |  чат-очередей: ' + @($items).Count + '  |  архив + фильтр по отмеченным очередям')
        }
        if ($null -ne $script:TxtLog) { Append-Log ("Чаты: метаданные очередей для $Key, записей: " + @($items).Count) }
        return $true
    } catch {
        $script:ChatQueuesLoaded = $false
        try { $script:ChatInboundQueueAllIds.Clear() } catch { }
        try { if ($null -ne $script:ClbChatQueues) { $script:ClbChatQueues.Items.Clear() } } catch { }
        if ($Quiet) {
            if ($null -ne $script:TxtLog) { Append-Log ("Чаты ($Key): ошибка очередей: " + $_.Exception.Message) }
        } else {
            [void][System.Windows.Forms.MessageBox]::Show('Ошибка загрузки очередей:`n' + $_.Exception.Message, $script:HubAppTitle)
        }
        return $false
    }
}

function Hub-ChatDialogSelectedChanged {
    Hub-ChatScheduleTranscriptLoad -DisplayRowIndex -1
}

function Hub-ChatDialogSelectedChangedRun {
    if ($script:ChatGridSuppressSelectionEvent) { return }
    $ix = -1
    if ($script:ChatTranscriptPendingDisplayRow -ge 0) {
        $ix = Hub-ChatGetCacheIndexFromDisplayRow -DisplayRowIndex $script:ChatTranscriptPendingDisplayRow
        $script:ChatTranscriptPendingDisplayRow = -1
    }
    if ($ix -lt 0) { $ix = Hub-ChatDialogGridCurrentCacheIndex }
    if ($ix -lt 0 -or $ix -ge $script:ChatDialogsCache.Count) { return }
    $dlg = $script:ChatDialogsCache[$ix]
    $key = $script:ChatCompanyKey
    if (-not $key) { return }
    $c = $script:Companies.$key
    $hostB = [string]$c.webitel_host
    $tok = [string]$c.access_token
    $cid = [string]$dlg.id
    $path = '/chat/dialogs/' + [uri]::EscapeDataString($cid) + '/messages'
    $form.Cursor = [System.Windows.Forms.Cursors]::WaitCursor
    try {
        $hist = Hub-WebitelRestGet -WebitelHost $hostB -AccessToken $tok -RelativeApiPath $path -Query @{ limit = 300 }
        $sk = Hub-ChatDialogSourceKind $dlg
        $skDisp = $sk
        if ($sk -eq 'unknown') {
            $hd = $false
            if ($dlg.PSObject.Properties['member'] -and $dlg.member -and $dlg.member.PSObject.Properties['destination']) {
                $hd = -not [string]::IsNullOrWhiteSpace([string]$dlg.member.destination)
            }
            if (-not $hd -and $dlg.PSObject.Properties['peer']) { $hd = $true }
            if ($hd) { $skDisp = 'bot' }
        }
        $skRu = switch ($skDisp) {
            'agent' { 'Агент (живой оператор)' }
            'bot' { 'Бот (схема / очередь)' }
            default { 'Бот / не определён' }
        }
        $sg = Hub-ChatQueueSkillGroupLabel $dlg
        Hub-ChatRenderTranscriptFromHist -Dlg $dlg -Hist $hist -SkillLabel $sg -ResponderRu $skRu -ErrorText ''
    } catch {
        Hub-ChatRenderTranscriptFromHist -Dlg $dlg -Hist $null -SkillLabel '—' -ResponderRu '—' -ErrorText $_.Exception.Message
    } finally {
        $form.Cursor = [System.Windows.Forms.Cursors]::Default
    }
}

function Invoke-HubOperationById {
    <# Операции по отмеченным в дереве ботам (кроме открытия папок, sync CO, импорта тестеров и синка чатов). #>
    param([Parameter(Mandatory)][int]$OpId)
    $keys = @(Get-SelectedProjectKeys)
    switch ($OpId) {
        0 {
            if ($keys.Count -eq 0) { throw 'Отметьте галочкой хотя бы один тип бота (лист дерева) у нужных компаний — команды выполняются по выбранным ботам.' }
            foreach ($k in $keys) { Append-Log ("[$k] " + (Invoke-FetchAndCurrent $k)) }
        }
        1 {
            if ($keys.Count -eq 0) { throw 'Отметьте галочкой типы ботов у компаний в дереве слева.' }
            foreach ($k in $keys) { Append-Log ("[$k] " + (Invoke-Deploy $k)) }
        }
        2 {
            if ($keys.Count -eq 0) { throw 'Отметьте галочкой типы ботов у компаний в дереве слева.' }
            foreach ($k in $keys) { Append-Log ("[$k]`n" + (Invoke-CatalogChecklist $k)) }
        }
        3 {
            if ($keys.Count -eq 0) { throw 'Отметьте галочкой типы ботов у компаний в дереве слева.' }
            foreach ($k in $keys) { Append-Log ("[$k]`n" + (Invoke-ValidateSchema $k)) }
        }
        4 {
            if ($keys.Count -eq 0) { throw 'Отметьте галочкой типы ботов у компаний в дереве слева.' }
            foreach ($k in $keys) { Append-Log ("[$k]`n" + (Invoke-CheckCrm $k)) }
        }
        5 {
            Append-Log (Invoke-SyncCoMapping)
        }
        6 {
            $p = Join-Path $script:SchemasDir 'current'
            Start-Process explorer.exe $p
            Append-Log "Открыта папка: $p"
        }
        7 {
            Hub-EnsureHubDataDirs
            Start-Process explorer.exe $script:HubCatalogsRoot
            Append-Log "Открыта папка: $($script:HubCatalogsRoot)"
        }
        8 {
            Append-Log (Hub-MigrateAllTestersFromCatalogJson)
        }
        9 {
            try { Hub-ChatPrefetchQueuesAllCompaniesOnStartup } catch {
                if ($null -ne $script:TxtLog) { Append-Log ('Чаты: метаданные очередей — ' + $_.Exception.Message) }
            }
            try { Hub-ChatArchiveSyncAllCompaniesOnStartup } catch {
                if ($null -ne $script:TxtLog) { Append-Log ('Чаты: синхронизация архива — ' + $_.Exception.Message) }
            }
            if ($null -ne $script:TabMain -and $script:TabMain.SelectedTab -eq $script:TpChats) {
                Hub-ChatRefreshChatsSectionFromArchive
            }
        }
        default { throw "Неизвестная операция (id $OpId)" }
    }
}

function Hub-ShowAddCompanyDialog {
    $dlg = New-Object System.Windows.Forms.Form
    $dlg.Text = ('Новая компания — ' + [string]$script:HubAppTitle)
    $dlg.ClientSize = New-Object System.Drawing.Size(540, 400)
    $dlg.FormBorderStyle = [System.Windows.Forms.FormBorderStyle]::FixedDialog
    $dlg.MaximizeBox = $false
    $dlg.MinimizeBox = $false
    $dlg.StartPosition = [System.Windows.Forms.FormStartPosition]::CenterParent
    $dlg.ShowInTaskbar = $false
    try { $dlg.Font = New-Object System.Drawing.Font('Segoe UI', 9) } catch { }
    try {
        if ($null -ne $form -and -not $form.IsDisposed) { $dlg.Owner = $form }
    } catch { }

    $pad = New-Object System.Windows.Forms.Padding(8, 4, 8, 4)
    $tlp = New-Object System.Windows.Forms.TableLayoutPanel
    $tlp.Dock = [System.Windows.Forms.DockStyle]::Fill
    $tlp.ColumnCount = 2
    $tlp.RowCount = 7
    $tlp.Padding = New-Object System.Windows.Forms.Padding(12, 12, 12, 10)
    [void]$tlp.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, [float]38.0)))
    [void]$tlp.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, [float]62.0)))
    for ($ri = 0; $ri -lt 7; $ri++) {
        [void]$tlp.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
    }

    $mkLbl = {
        param([string]$t)
        $lb = New-Object System.Windows.Forms.Label
        $lb.AutoSize = $true
        $lb.Margin = $pad
        $lb.Text = $t
        $lb.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
        return $lb
    }
    $mkTxt = {
        $tx = New-Object System.Windows.Forms.TextBox
        $tx.Dock = [System.Windows.Forms.DockStyle]::Fill
        $tx.Margin = $pad
        return $tx
    }

    $txtKey = & $mkTxt
    $txtName = & $mkTxt
    $txtCrm = & $mkTxt
    $txtWebitel = & $mkTxt
    $txtTok = & $mkTxt

    [void]$tlp.Controls.Add((& $mkLbl 'Индекс проекта (ключ, например CO_):'), 0, 0)
    [void]$tlp.Controls.Add($txtKey, 1, 0)
    [void]$tlp.Controls.Add((& $mkLbl 'Название компании:'), 0, 1)
    [void]$tlp.Controls.Add($txtName, 1, 1)
    [void]$tlp.Controls.Add((& $mkLbl 'URL CRM:'), 0, 2)
    [void]$tlp.Controls.Add($txtCrm, 1, 2)
    [void]$tlp.Controls.Add((& $mkLbl 'URL Webitel (Engine):'), 0, 3)
    [void]$tlp.Controls.Add($txtWebitel, 1, 3)
    [void]$tlp.Controls.Add((& $mkLbl 'Токен админа Webitel:'), 0, 4)
    [void]$tlp.Controls.Add($txtTok, 1, 4)

    $hint = New-Object System.Windows.Forms.Label
    $hint.AutoSize = $false
    $hint.Dock = [System.Windows.Forms.DockStyle]::Fill
    $hint.Margin = $pad
    $hint.Height = 48
    $hint.ForeColor = $script:HubUiMuted
    $hint.Text = 'Ключ: только A–Z, 0–9 и _, в конце символ _. Запись — в data\companies.json. В справочнике (вкладка «Справочники») блок «О компании» покажет эти поля для текущей компании.'
    $tlp.SetColumnSpan($hint, 2)
    [void]$tlp.Controls.Add($hint, 0, 5)

    $flp = New-Object System.Windows.Forms.FlowLayoutPanel
    $flp.Dock = [System.Windows.Forms.DockStyle]::Fill
    $flp.FlowDirection = [System.Windows.Forms.FlowDirection]::RightToLeft
    $flp.Padding = New-Object System.Windows.Forms.Padding(0, 10, 0, 0)
    $flp.Margin = New-Object System.Windows.Forms.Padding(8, 4, 8, 4)
    $tlp.SetColumnSpan($flp, 2)
    $btnOk = New-Object System.Windows.Forms.Button
    $btnOk.Text = 'Сохранить'
    $btnOk.AutoSize = $true
    $btnOk.Margin = New-Object System.Windows.Forms.Padding(8, 4, 0, 4)
    $btnCancel = New-Object System.Windows.Forms.Button
    $btnCancel.Text = 'Отмена'
    $btnCancel.AutoSize = $true
    $btnCancel.DialogResult = [System.Windows.Forms.DialogResult]::Cancel
    $btnCancel.Margin = New-Object System.Windows.Forms.Padding(8, 4, 0, 4)
    [void]$flp.Controls.Add($btnOk)
    [void]$flp.Controls.Add($btnCancel)
    [void]$tlp.Controls.Add($flp, 0, 6)

    $dlg.Controls.Add($tlp)
    $dlg.CancelButton = $btnCancel
    $dlg.AcceptButton = $btnOk

    $btnOk.Add_Click({
            $k = $txtKey.Text.Trim()
            if ($k -notmatch '^[A-Z0-9_]+_$') {
                [void][System.Windows.Forms.MessageBox]::Show(
                    'Индекс проекта: только A–Z, 0–9, _; строка должна оканчиваться на _ (например CO_, AR_).',
                    $script:HubAppTitle)
                return
            }
            if ($null -ne $script:Companies -and $script:Companies.PSObject.Properties[$k]) {
                [void][System.Windows.Forms.MessageBox]::Show("Такой ключ уже есть: $k", $script:HubAppTitle)
                return
            }
            $nm = $txtName.Text.Trim()
            if ([string]::IsNullOrWhiteSpace($nm)) { $nm = $k.TrimEnd('_') }
            $wh = $txtWebitel.Text.Trim()
            if ([string]::IsNullOrWhiteSpace($wh)) {
                [void][System.Windows.Forms.MessageBox]::Show('Укажите URL Webitel (Engine).', $script:HubAppTitle)
                return
            }
            $tk = $txtTok.Text.Trim()
            if ([string]::IsNullOrWhiteSpace($tk)) {
                [void][System.Windows.Forms.MessageBox]::Show('Укажите токен админа Webitel.', $script:HubAppTitle)
                return
            }
            $dlg.Tag = @{
                Key         = $k
                DisplayName = $nm
                CrmUrl      = $txtCrm.Text.Trim()
                WebitelHost = $wh
                AccessToken = $tk
            }
            $dlg.DialogResult = [System.Windows.Forms.DialogResult]::OK
            $dlg.Close()
        })

    $dr = $dlg.ShowDialog()
    if ($dr -ne [System.Windows.Forms.DialogResult]::OK) { return $null }
    return $dlg.Tag
}

function Hub-AddCompany {
    $d = Hub-ShowAddCompanyDialog
    if ($null -eq $d) { return }
    $key = [string]$d.Key
    if ([string]::IsNullOrWhiteSpace($key)) { return }
    if ($key -notmatch '^[A-Z0-9_]+_$') {
        [void][System.Windows.Forms.MessageBox]::Show(
            'Ключ: допустимы A–Z, 0–9, _; строка должна оканчиваться символом _ (например CO_, CO2_, MX_).',
            $script:HubAppTitle)
        return
    }
    if ($script:Companies.PSObject.Properties[$key]) {
        [void][System.Windows.Forms.MessageBox]::Show("Ключ уже есть: $key", $script:HubAppTitle)
        return
    }
    $disp = [string]$d.DisplayName
    if ([string]::IsNullOrWhiteSpace($disp)) { $disp = $key.TrimEnd('_') }
    $newCo = [pscustomobject]@{
        name           = $disp
        country        = ''
        project_index  = $key
        crm_url        = [string]$d.CrmUrl
        webitel_host   = [string]$d.WebitelHost
        access_token   = [string]$d.AccessToken
        schema_id      = 0
        schema_name    = ''
    }
    $script:CfgRoot.companies | Add-Member -MemberType NoteProperty -Name $key -Value $newCo -Force
    $script:Companies = $script:CfgRoot.companies
    $script:ProjectKeys = @($script:Companies.PSObject.Properties.Name | Where-Object { $_ -notmatch '^_' } | Sort-Object)
    try {
        Hub-SaveDeployConfigToDisk
        $reg = Hub-GetRegistryRoot
        $verDefault = Get-Date -Format 'yyyy-MM-dd'
        if (-not $reg) {
            $reg = [pscustomobject]@{ _comment = 'Активная версия каталогов по компании.' }
        }
        $reg | Add-Member -NotePropertyName $key -NotePropertyValue ([pscustomobject]@{
                active_version   = $verDefault
                catalog_bot_id   = 'whatsapp_infobip'
            }) -Force
        Hub-SaveRegistryRoot $reg
    } catch {
        [void]$script:CfgRoot.companies.PSObject.Properties.Remove($key)
        $script:Companies = $script:CfgRoot.companies
        $script:ProjectKeys = @($script:Companies.PSObject.Properties.Name | Where-Object { $_ -notmatch '^_' } | Sort-Object)
        [void][System.Windows.Forms.MessageBox]::Show("Ошибка при записи:`n$($_.Exception.Message)", $script:HubAppTitle)
        return
    }
    Hub-ReloadDeployConfig
    [void][System.Windows.Forms.MessageBox]::Show(
        ("Компания $key добавлена. В registry активная версия: " + $verDefault + ". При необходимости создайте папку и catalog.json в data\catalogs\$key\$verDefault."),
        $script:HubAppTitle)
    if ($null -ne $script:TxtLog) { Append-Log "Добавлена компания: $key, registry $verDefault" }
}

function Hub-RemoveCompany {
    $key = Hub-GetCompanyKeyForRemoveAction
    if ([string]::IsNullOrWhiteSpace($key)) {
        [void][System.Windows.Forms.MessageBox]::Show(
            'Выберите в дереве компанию (корень) или тип бота — удаляется вся компания по ключу проекта.',
            $script:HubAppTitle)
        return
    }
    $r = [System.Windows.Forms.MessageBox]::Show(
        "Удалить ключ $key из companies (хаб), deploy-config.json и registry?",
        $script:HubAppTitle,
        [System.Windows.Forms.MessageBoxButtons]::YesNo,
        [System.Windows.Forms.MessageBoxIcon]::Warning)
    if ($r -ne [System.Windows.Forms.DialogResult]::Yes) { return }
    if (-not ($script:CfgRoot.companies.PSObject.Properties[$key])) { return }

    try {
        [void]$script:CfgRoot.companies.PSObject.Properties.Remove($key)
        Hub-SaveDeployConfigToDisk
        $rg = Hub-GetRegistryRoot
        if ($rg -and $rg.PSObject.Properties[$key]) {
            [void]$rg.PSObject.Properties.Remove($key)
            Hub-SaveRegistryRoot $rg
        }
    } catch {
        [void][System.Windows.Forms.MessageBox]::Show("Не удалось сохранить:`n$($_.Exception.Message)", $script:HubAppTitle)
        return
    }
    $script:Companies = $script:CfgRoot.companies
    $script:ProjectKeys = @($script:Companies.PSObject.Properties.Name | Where-Object { $_ -notmatch '^_' } | Sort-Object)
    Hub-ReloadDeployConfig
    $script:CatalogEditorPath = $null
    $script:CatalogRootObject = $null
    if ($null -ne $script:DgvCatalog) { Hub-FillCatalogGrid }
    if ($null -ne $script:TxtLog) { Append-Log "Удалена компания: $key" }
}

function Hub-SetControlRoundedRegion {
    param(
        [Parameter(Mandatory)][System.Windows.Forms.Control]$Ctrl,
        [int]$Radius = 10
    )
    if ($null -eq $Ctrl) { return }
    if ($Ctrl.Width -lt 8 -or $Ctrl.Height -lt 8) {
        $Ctrl.Region = $null
        return
    }
    $r = [Math]::Min($Radius, [Math]::Min([int]($Ctrl.Width / 2), [int]($Ctrl.Height / 2)))
    if ($r -lt 2) { $r = 2 }
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    try {
        $w = [float]$Ctrl.Width
        $h = [float]$Ctrl.Height
        $d = [float]($r * 2)
        $z = [float]0
        $a180 = [float]180
        $a270 = [float]270
        $a90 = [float]90
        [void]$path.AddArc($z, $z, $d, $d, $a180, $a90)
        [void]$path.AddArc($w - $d, $z, $d, $d, $a270, $a90)
        [void]$path.AddArc($w - $d, $h - $d, $d, $d, $z, $a90)
        [void]$path.AddArc($z, $h - $d, $d, $d, $a90, $a90)
        $path.CloseFigure()
        $Ctrl.Region = New-Object System.Drawing.Region -ArgumentList $path
    } finally {
        $path.Dispose()
    }
}

function Hub-CreateRoundedRectPath {
    param(
        [Parameter(Mandatory)][System.Drawing.RectangleF]$Rect,
        [float]$Radius
    )
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $mn = [Math]::Min([float]$Rect.Width, [float]$Rect.Height) / [float]2
    $fl = [Math]::Floor([double]$mn)
    $mx = [float][Math]::Min([double]$Radius, $fl)
    if ($mx -lt [float]2) { $mx = [float]2 }
    $d = $mx * [float]2
    $z = [float]0
    $a180 = [float]180
    $a270 = [float]270
    $a90 = [float]90
    [void]$path.AddArc([float]$Rect.X, [float]$Rect.Y, $d, $d, $a180, $a90)
    [void]$path.AddArc([float]$Rect.Right - $d, [float]$Rect.Y, $d, $d, $a270, $a90)
    [void]$path.AddArc([float]$Rect.Right - $d, [float]$Rect.Bottom - $d, $d, $d, $z, $a90)
    [void]$path.AddArc([float]$Rect.X, [float]$Rect.Bottom - $d, $d, $d, $a90, $a90)
    $path.CloseFigure()
    return $path
}

function Set-HubButtonStyle {
    <#
    Единый вид кнопок: плоский стиль, опционально скругление (Region), курсор-рука, цвета по роли.
    Primary / Success — без рамки; Secondary — светлая с тонкой границей.
    #>
    param(
        [Parameter(Mandatory)][System.Windows.Forms.Button]$Button,
        [Parameter(Mandatory)][ValidateSet('Primary', 'Success', 'Secondary')][string]$Variant,
        [switch]$CenterText,
        [switch]$NoRound
    )
    $Button.UseVisualStyleBackColor = $false
    $Button.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
    $Button.Cursor = [System.Windows.Forms.Cursors]::Hand
    $rad = if ($Variant -eq 'Secondary') { 8 } else { 10 }
    $weight = if ($Variant -eq 'Secondary') {
        [System.Drawing.FontStyle]::Regular
    } else {
        [System.Drawing.FontStyle]::Bold
    }
    $Button.Font = New-Object System.Drawing.Font('Segoe UI', 9.75, $weight)
    # Высота строки таблицы / малые кнопки: большой Padding вертикально «съедает» текст (кажется пустой кнопкой)
    $Button.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
    if ($CenterText) {
        $Button.Padding = New-Object System.Windows.Forms.Padding(8, 3, 8, 3)
        $Button.UseCompatibleTextRendering = $false
    } else {
        $Button.Padding = New-Object System.Windows.Forms.Padding(10, 5, 10, 5)
    }
    switch ($Variant) {
        'Primary' {
            $Button.FlatAppearance.BorderSize = 0
            $Button.BackColor = $script:HubUiNavy
            $Button.ForeColor = [System.Drawing.Color]::White
            $Button.FlatAppearance.MouseOverBackColor = $script:HubUiNavyHi
            $Button.FlatAppearance.MouseDownBackColor = $script:HubUiNavyPress
        }
        'Success' {
            $Button.FlatAppearance.BorderSize = 0
            $Button.BackColor = $script:HubUiSuccess
            $Button.ForeColor = [System.Drawing.Color]::White
            $Button.FlatAppearance.MouseOverBackColor = $script:HubUiSuccessHi
            $Button.FlatAppearance.MouseDownBackColor = [System.Drawing.Color]::FromArgb(21, 128, 61)
        }
        'Secondary' {
            $Button.FlatAppearance.BorderSize = 1
            $Button.FlatAppearance.BorderColor = $script:HubUiBorder
            $Button.BackColor = $script:HubUiCard
            $Button.ForeColor = $script:HubUiInk
            $Button.FlatAppearance.MouseOverBackColor = $script:HubUiTrack
            $Button.FlatAppearance.MouseDownBackColor = [System.Drawing.Color]::FromArgb(226, 232, 240)
        }
    }
    if (-not $NoRound) {
        $radiusForRound = [int]$rad
        $roundIt = {
            param($s, $ev)
            Hub-SetControlRoundedRegion -Ctrl ([System.Windows.Forms.Control]$s) -Radius $radiusForRound
        }
        if ($Button.IsHandleCreated) {
            Hub-SetControlRoundedRegion -Ctrl $Button -Radius $radiusForRound
        }
        $Button.Add_Resize($roundIt)
    } else {
        $Button.Region = $null
    }
}

function Hub-MainTabControl_DrawItem {
    param(
        [Parameter(Mandatory)][System.Windows.Forms.TabControl]$Tb,
        [Parameter(Mandatory)][System.Windows.Forms.DrawItemEventArgs]$E
    )
    if ($null -eq $script:HubUiFontTab -or $null -eq $script:HubUiFontTabSel) { return }
    $g = $E.Graphics
    try { $g.ResetClip() } catch { }
    $full = $E.Bounds
    # Плоская заливка с лёгким перекрытием соседей — без скруглений и без швов от GraphicsPath
    $exL = if ($E.Index -gt 0) { 1 } else { 0 }
    $exR = if ($E.Index -lt ($Tb.TabCount - 1)) { 1 } else { 0 }
    $fillRect = New-Object System.Drawing.Rectangle(($full.X - $exL), $full.Y, ($full.Width + $exL + $exR), $full.Height)
    $sel = ($E.Index -eq $Tb.SelectedIndex)
    if ($sel) {
        $fillBr = New-Object System.Drawing.SolidBrush $script:HubUiNavy
        $fc = [System.Drawing.Color]::White
        $font = $script:HubUiFontTabSel
    } else {
        $fillBr = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(248, 250, 252))
        $fc = $script:HubUiInk
        $font = $script:HubUiFontTab
    }
    try {
        $g.FillRectangle($fillBr, $fillRect)
    } finally {
        $fillBr.Dispose()
    }
    $rf = New-Object System.Drawing.RectangleF([float]$full.X, [float]$full.Y, [float]$full.Width, [float]$full.Height)
    $br = New-Object System.Drawing.SolidBrush $fc
    $fmt = New-Object System.Drawing.StringFormat
    try {
        $fmt.Alignment = [System.Drawing.StringAlignment]::Center
        $fmt.LineAlignment = [System.Drawing.StringAlignment]::Center
        $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::ClearTypeGridFit
        $g.DrawString($Tb.TabPages[$E.Index].Text, $font, $br, $rf, $fmt)
    } finally {
        $br.Dispose()
        $fmt.Dispose()
    }
}

function Hub-ApplyMainSplitLayout {
    $sp = $script:MainSplit
    if ($null -eq $sp) { return }
    $iw = [int]$sp.ClientSize.Width
    if ($iw -lt 200) { return }
    $sw = [int]$sp.SplitterWidth
    $m1 = 400
    $wantP2 = 300
    $need = $m1 + $wantP2 + $sw + 12
    $newP2 = if ($iw -ge $need) { $wantP2 } else {
        [Math]::Max(25, [Math]::Min(200, $iw - $m1 - $sw - 12))
    }
    # Сначала укладываем SplitterDistance под будущий Panel2MinSize (иначе исключение при присвоении)
    $max1Preview = $iw - $newP2 - $sw - 8
    if ($max1Preview -ge $m1 -and $sp.SplitterDistance -gt $max1Preview) {
        $sp.SplitterDistance = $max1Preview
    }
    $sp.Panel2MinSize = $newP2
    $m2 = [int]$sp.Panel2MinSize
    $max1 = $iw - $m2 - $sw - 8
    if ($max1 -lt $m1) { return }
    $ideal = [int][Math]::Round($iw * 0.38)
    $ideal = [Math]::Max($m1, [Math]::Min(580, $ideal))
    $sp.SplitterDistance = [Math]::Min($ideal, $max1)
    try { $sp.Panel1MinSize = $m1 } catch { }
}

function Hub-RestartHubAfterScriptUpdate {
    <# Запускает новый экземпляр хаба и закрывает текущую форму (применение обновления ps1). #>
    $ps1 = $script:HubAppScriptPath
    if (-not (Test-Path -LiteralPath $ps1)) {
        $ps1 = Join-Path $script:HubDir 'AventusBotHub.ps1'
    }
    if (-not (Test-Path -LiteralPath $ps1)) { return }
    $psx = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    try {
        Start-Process -FilePath $psx -ArgumentList @(
            '-NoProfile', '-ExecutionPolicy', 'Bypass', '-Sta', '-NoLogo', '-WindowStyle', 'Hidden', '-File', $ps1
        ) -WorkingDirectory $script:HubDir -ErrorAction Stop
    } catch {
        try { Append-Log ('Перезапуск хаба: ' + [string]$_.Exception.Message) } catch { }
        $script:HubSelfUpdateRestarting = $false
        return
    }
    try {
        if ($null -ne $form -and -not $form.IsDisposed) { $form.Close() }
    } catch { }
}

function Hub-HubSelfUpdateTimerTick {
    if ($script:HubSelfUpdateRestarting) { return }
    if (([DateTime]::UtcNow - $script:HubProcessStartUtc).TotalSeconds -lt 25) { return }
    try {
        if (-not (Test-Path -LiteralPath $script:HubAppScriptPath)) { return }
        $fi = Get-Item -LiteralPath $script:HubAppScriptPath
        if ($fi.LastWriteTimeUtc -le $script:HubSessionScriptUtc) { return }
    } catch { return }
    $script:HubSelfUpdateRestarting = $true
    try { Append-Log 'Файл AventusBotHub.ps1 обновлён на диске — перезапуск для применения изменений.' } catch { }
    Hub-RestartHubAfterScriptUpdate
}

# WinForms + $ErrorActionPreference='Stop': конвейеры с Select-Object -First дают PipelineStoppedException на UI-потоке.
try {
    [void][System.Windows.Forms.Application]::SetUnhandledExceptionMode([System.Windows.Forms.UnhandledExceptionMode]::CatchException)
} catch { }
[System.Windows.Forms.Application]::add_ThreadException({
        param($s, $tea)
        try {
            $w = $tea.Exception
            while ($null -ne $w) {
                if ($w.GetType().FullName -eq 'System.Management.Automation.PipelineStoppedException') { return }
                $w = $w.InnerException
            }
        } catch { }
        try {
            [void][System.Windows.Forms.MessageBox]::Show(
                ('Сбой UI-потока:' + [Environment]::NewLine + [string]$tea.Exception.Message),
                $script:HubAppTitle,
                [System.Windows.Forms.MessageBoxButtons]::OK,
                [System.Windows.Forms.MessageBoxIcon]::Error)
        } catch { }
    })

# --- UI ---
$script:CatalogEditorPath = $null
$script:CatalogRootObject = $null

$form = New-Object System.Windows.Forms.Form
$form.Text = $script:HubAppTitle
$form.MinimumSize = New-Object System.Drawing.Size(880, 620)
$form.Size = New-Object System.Drawing.Size(1200, 800)
$form.StartPosition = 'CenterScreen'
$form.WindowState = [System.Windows.Forms.FormWindowState]::Maximized
$form.BackColor = $script:HubUiPageBg
$form.Font = New-Object System.Drawing.Font('Segoe UI', 9.5)
$script:HubUiFontTab = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Regular)
$script:HubUiFontTabSel = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)

$script:HubIconBitmap = $null
$iconPng = Join-Path $script:HubDir 'app-icon.png'
if (Test-Path -LiteralPath $iconPng) {
    try {
        $script:HubIconBitmap = [System.Drawing.Bitmap]::FromFile($iconPng)
        $hIcon = $script:HubIconBitmap.GetHicon()
        $tmpIco = [System.Drawing.Icon]::FromHandle($hIcon)
        $form.Icon = [System.Drawing.Icon]::new($tmpIco, [System.Drawing.Size]::new(32, 32))
        $tmpIco.Dispose()
    } catch {
        if ($null -ne $script:HubIconBitmap) {
            try { $script:HubIconBitmap.Dispose() } catch { }
            $script:HubIconBitmap = $null
        }
    }
}
$form.Add_FormClosed({
        if ($null -ne $script:CmsQueueSchemas) {
            try { $script:CmsQueueSchemas.Dispose() } catch { }
            $script:CmsQueueSchemas = $null
        }
        if ($null -ne $script:HubIconBitmap) {
            try { $script:HubIconBitmap.Dispose() } catch { }
            $script:HubIconBitmap = $null
        }
        if ($null -ne $script:HubUiFontTab) {
            try { $script:HubUiFontTab.Dispose() } catch { }
            $script:HubUiFontTab = $null
        }
        if ($null -ne $script:HubUiFontTabSel) {
            try { $script:HubUiFontTabSel.Dispose() } catch { }
            $script:HubUiFontTabSel = $null
        }
        if ($null -ne $script:TimerCompanyTreeClock) {
            try { $script:TimerCompanyTreeClock.Stop() } catch { }
            try { $script:TimerCompanyTreeClock.Dispose() } catch { }
            $script:TimerCompanyTreeClock = $null
        }
        if ($null -ne $script:TimerHubSelfUpdate) {
            try { $script:TimerHubSelfUpdate.Stop() } catch { }
            try { $script:TimerHubSelfUpdate.Dispose() } catch { }
            $script:TimerHubSelfUpdate = $null
        }
    })

$script:MainSplit = New-Object System.Windows.Forms.SplitContainer
$script:MainSplit.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:MainSplit.FixedPanel = [System.Windows.Forms.FixedPanel]::Panel1
# До layout ширина по умолчанию мала — жёсткие минимумы дают исключение; Hub-ApplyMainSplitLayout донастроит.
$script:MainSplit.Panel1MinSize = 1
$script:MainSplit.SplitterWidth = 5
$script:MainSplit.Panel2MinSize = 1
$script:MainSplit.SplitterDistance = 200
$script:MainSplit.BackColor = $script:HubUiPageBg
$script:MainSplit.Panel1.BackColor = $script:HubUiPageBg
$script:MainSplit.Panel2.BackColor = $script:HubUiPageBg
$script:MainSplit.Panel1.Padding = New-Object System.Windows.Forms.Padding(12, 6, 10, 10)

$lblSide = New-Object System.Windows.Forms.Label
$lblSide.Text = 'КОМПАНИИ И БОТЫ'
$lblSide.Dock = [System.Windows.Forms.DockStyle]::Top
$lblSide.Height = 32
$lblSide.Padding = New-Object System.Windows.Forms.Padding(14, 12, 12, 2)
$lblSide.ForeColor = $script:HubUiMuted
$lblSide.BackColor = $script:HubUiPageBg
$lblSide.Font = New-Object System.Drawing.Font('Segoe UI', 8.25, [System.Drawing.FontStyle]::Bold)

$script:PnlCompanyButtons = New-Object System.Windows.Forms.Panel
$script:PnlCompanyButtons.Dock = [System.Windows.Forms.DockStyle]::Bottom
$script:PnlCompanyButtons.Height = 178
$script:PnlCompanyButtons.BackColor = $script:HubUiCard
$script:PnlCompanyButtons.Padding = New-Object System.Windows.Forms.Padding(12, 10, 12, 12)

$script:TlpCompanyActions = New-Object System.Windows.Forms.TableLayoutPanel
$script:TlpCompanyActions.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:TlpCompanyActions.ColumnCount = 2
$script:TlpCompanyActions.RowCount = 3
$script:TlpCompanyActions.Margin = [System.Windows.Forms.Padding]::Empty
$script:TlpCompanyActions.Padding = [System.Windows.Forms.Padding]::Empty
[void]$script:TlpCompanyActions.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, [float]50)))
[void]$script:TlpCompanyActions.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, [float]50)))
[void]$script:TlpCompanyActions.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, [float]42)))
[void]$script:TlpCompanyActions.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, [float]46)))
[void]$script:TlpCompanyActions.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, [float]44)))

$btnMargin = New-Object System.Windows.Forms.Padding(0, 0, 5, 8)
$btnMarginLastCol = New-Object System.Windows.Forms.Padding(5, 0, 0, 8)

$btnAll = New-Object System.Windows.Forms.Button
$btnAll.Text = 'Все'
$btnAll.Dock = [System.Windows.Forms.DockStyle]::Fill
$btnAll.Margin = $btnMargin
$btnAll.Add_Click({
        if ($null -eq $script:TvCompanies) { return }
        $script:CompanyTreeSuppressCheck = $true
        try {
            foreach ($root in $script:TvCompanies.Nodes) {
                foreach ($ch in $root.Nodes) { $ch.Checked = $true }
                $root.Checked = $true
            }
        } finally {
            $script:CompanyTreeSuppressCheck = $false
        }
    })

$btnNone = New-Object System.Windows.Forms.Button
$btnNone.Text = 'Снять выделение'
$btnNone.Dock = [System.Windows.Forms.DockStyle]::Fill
$btnNone.Margin = $btnMarginLastCol
$btnNone.Add_Click({
        if ($null -eq $script:TvCompanies) { return }
        $script:CompanyTreeSuppressCheck = $true
        try {
            foreach ($root in $script:TvCompanies.Nodes) {
                $root.Checked = $false
                foreach ($ch in $root.Nodes) { $ch.Checked = $false }
            }
        } finally {
            $script:CompanyTreeSuppressCheck = $false
        }
    })

$script:BtnCompanyAdd = New-Object System.Windows.Forms.Button
$script:BtnCompanyAdd.Text = 'Добавить компанию'
$script:BtnCompanyAdd.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:BtnCompanyAdd.Margin = $btnMargin
$script:BtnCompanyAdd.Add_Click({ Hub-AddCompany })

$script:BtnCompanyRemove = New-Object System.Windows.Forms.Button
$script:BtnCompanyRemove.Text = 'Удалить компанию'
$script:BtnCompanyRemove.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:BtnCompanyRemove.Margin = $btnMarginLastCol
$script:BtnCompanyRemove.Add_Click({ Hub-RemoveCompany })

$script:BtnReloadCfg = New-Object System.Windows.Forms.Button
$script:BtnReloadCfg.Text = 'Перечитать deploy-config'
$script:BtnReloadCfg.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:BtnReloadCfg.Margin = New-Object System.Windows.Forms.Padding(0, 6, 0, 0)
$script:BtnReloadCfg.Add_Click({
        try {
            Hub-ReloadDeployConfig
            if ($null -ne $script:TxtLog) { Append-Log 'Перечитан deploy-config.json (Hub-ReloadDeployConfig).' }
        } catch {
            [void][System.Windows.Forms.MessageBox]::Show($_.Exception.Message, $script:HubAppTitle)
        }
    })

[void]$script:TlpCompanyActions.Controls.Add($btnAll, 0, 0)
[void]$script:TlpCompanyActions.Controls.Add($btnNone, 1, 0)
[void]$script:TlpCompanyActions.Controls.Add($script:BtnCompanyAdd, 0, 1)
[void]$script:TlpCompanyActions.Controls.Add($script:BtnCompanyRemove, 1, 1)
[void]$script:TlpCompanyActions.Controls.Add($script:BtnReloadCfg, 0, 2)
$script:TlpCompanyActions.SetColumnSpan($script:BtnReloadCfg, 2)

$script:PnlCompanyButtons.Controls.Add($script:TlpCompanyActions)

foreach ($hubCoBtn in @($btnAll, $btnNone, $script:BtnCompanyAdd, $script:BtnCompanyRemove, $script:BtnReloadCfg)) {
    Set-HubButtonStyle -Button $hubCoBtn -Variant Secondary -CenterText -NoRound
}

$script:TvCompanies = New-Object System.Windows.Forms.TreeView
$script:TvCompanies.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:TvCompanies.BorderStyle = [System.Windows.Forms.BorderStyle]::None
$script:TvCompanies.BackColor = $script:HubUiCard
$script:TvCompanies.ForeColor = $script:HubUiInk
$script:TvCompanies.FullRowSelect = $true
$script:TvCompanies.HideSelection = $false
$script:TvCompanies.HotTracking = $true
$script:TvCompanies.ShowLines = $false
$script:TvCompanies.ShowPlusMinus = $true
$script:TvCompanies.ShowRootLines = $false
$script:TvCompanies.CheckBoxes = $true
$script:TvCompanies.ItemHeight = 24
$script:TvCompanies.Font = New-Object System.Drawing.Font('Segoe UI', 9.5, [System.Drawing.FontStyle]::Regular)
try {
    $script:TvCompanies.LineColor = $script:HubUiBorder
} catch { }

$script:PnlCompanyTreeCard = New-Object System.Windows.Forms.Panel
$script:PnlCompanyTreeCard.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:PnlCompanyTreeCard.BackColor = $script:HubUiCard
$script:PnlCompanyTreeCard.Padding = New-Object System.Windows.Forms.Padding(14, 14, 14, 14)
$script:PnlCompanyTreeCard.Margin = New-Object System.Windows.Forms.Padding(0, 2, 0, 8)
try {
    $tCard = $script:PnlCompanyTreeCard.GetType()
    $dblCard = $tCard.GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::NonPublic)
    if ($null -ne $dblCard) { $dblCard.SetValue($script:PnlCompanyTreeCard, $true, $null) }
} catch { }

$script:PnlCompanyTreeRefreshBar = New-Object System.Windows.Forms.Panel
$script:PnlCompanyTreeRefreshBar.Dock = [System.Windows.Forms.DockStyle]::Bottom
$script:PnlCompanyTreeRefreshBar.Height = 46
$script:PnlCompanyTreeRefreshBar.BackColor = $script:HubUiCard

$script:BtnHubSidebarRefresh = New-Object System.Windows.Forms.Button
$script:BtnHubSidebarRefresh.Size = New-Object System.Drawing.Size(38, 38)
$script:BtnHubSidebarRefresh.TabStop = $true
$script:BtnHubSidebarRefresh.UseVisualStyleBackColor = $false
$script:BtnHubSidebarRefresh.FlatStyle = [System.Windows.Forms.FlatStyle]::Flat
$script:BtnHubSidebarRefresh.Cursor = [System.Windows.Forms.Cursors]::Hand
$script:BtnHubSidebarRefresh.BackColor = $script:HubUiCard
$script:BtnHubSidebarRefresh.ForeColor = $script:HubUiInk
$script:BtnHubSidebarRefresh.FlatAppearance.BorderSize = 1
$script:BtnHubSidebarRefresh.FlatAppearance.BorderColor = $script:HubUiBorder
$script:BtnHubSidebarRefresh.FlatAppearance.MouseOverBackColor = $script:HubUiTrack
$script:BtnHubSidebarRefresh.FlatAppearance.MouseDownBackColor = [System.Drawing.Color]::FromArgb(226, 232, 240)
$script:BtnHubSidebarRefresh.Padding = [System.Windows.Forms.Padding]::Empty
$script:BtnHubSidebarRefresh.Region = $null
try {
    $script:BtnHubSidebarRefresh.Font = New-Object System.Drawing.Font('Segoe MDL2 Assets', 13, [System.Drawing.FontStyle]::Regular)
    $script:BtnHubSidebarRefresh.Text = ([string][char]0xE72C)
} catch {
    $script:BtnHubSidebarRefresh.Font = New-Object System.Drawing.Font('Segoe UI Symbol', 12, [System.Drawing.FontStyle]::Regular)
    $script:BtnHubSidebarRefresh.Text = ([string][char]0x21BA)
}
$script:BtnHubSidebarRefresh.Add_Click({ Hub-HubSidebarRefreshClick })
$script:PnlCompanyTreeRefreshBar.Add_Resize({
        $b = $script:BtnHubSidebarRefresh
        $p = $script:PnlCompanyTreeRefreshBar
        if ($null -eq $b -or $null -eq $p) { return }
        $b.Left = [int](($p.ClientSize.Width - $b.Width) / 2)
        $b.Top = [int](($p.ClientSize.Height - $b.Height) / 2)
    })
[void]$script:PnlCompanyTreeRefreshBar.Controls.Add($script:BtnHubSidebarRefresh)
$script:ToolTipHubSidebar = New-Object System.Windows.Forms.ToolTip
$script:ToolTipHubSidebar.AutoPopDelay = 16000
$script:ToolTipHubSidebar.SetToolTip($script:BtnHubSidebarRefresh, 'Обновить: deploy-config, дерево компаний, проверка чат-очередей и выгрузку диалогов в архив; во вкладке «Чаты» — перечитать список из архива.')

$script:PnlCompanyTreeCard.Controls.Add($script:PnlCompanyTreeRefreshBar)
$script:PnlCompanyTreeCard.Controls.Add($script:TvCompanies)
$script:TvCompanies.Add_AfterCheck({
        param($Sender, $e)
        if ($script:CompanyTreeSuppressCheck) { return }
        $n = $e.Node
        if ($null -eq $n) { return }
        $tag = [string]$n.Tag
        if ($tag.StartsWith('COMPANY|')) {
            $script:CompanyTreeSuppressCheck = $true
            try {
                foreach ($c in $n.Nodes) { $c.Checked = $n.Checked }
            } finally {
                $script:CompanyTreeSuppressCheck = $false
            }
        }
        if ($null -ne $script:TabMain -and ($script:TabMain.SelectedTab -eq $script:TpCatalog)) {
            if ($null -ne (Hub-GetCatalogCompanyKeyFromTree)) { Hub-LoadCatalogEditor }
        }
        if ($null -ne $script:TabMain -and ($script:TabMain.SelectedTab -eq $script:TpChats)) {
            Hub-ChatRefreshChatsSectionFromArchive
        }
        if ($null -ne $script:TabMain -and ($script:TabMain.SelectedTab -eq $script:TpTesters)) {
            Hub-RefreshTestersTab
        }
        if ($null -ne $script:TabMain -and ($script:TabMain.SelectedTab -eq $script:TpQueues)) {
            try { & $script:HubLayoutQueuesTab } catch { }
        }
    })
$script:TvCompanies.Add_AfterSelect({
        if ($null -eq $script:TabMain) { return }
        if ($script:TabMain.SelectedTab -eq $script:TpCatalog) {
            Hub-LoadCatalogEditor
        }
        if ($script:TabMain.SelectedTab -eq $script:TpChats) {
            Hub-ChatRefreshChatsSectionFromArchive
        }
        if ($script:TabMain.SelectedTab -eq $script:TpTesters) {
            Hub-RefreshTestersTab
        }
        if ($null -ne $script:TabMain -and ($script:TabMain.SelectedTab -eq $script:TpQueues)) {
            & $script:HubLayoutQueuesTab
        }
    })

$script:TimerCompanyTreeClock = New-Object System.Windows.Forms.Timer
$script:TimerCompanyTreeClock.Interval = 1000
$script:TimerCompanyTreeClock.Add_Tick({ try { Hub-CompanyTreeClockApplyToAllRoots } catch { } })

$script:TimerHubSelfUpdate = New-Object System.Windows.Forms.Timer
$script:TimerHubSelfUpdate.Interval = 45000
$script:TimerHubSelfUpdate.Add_Tick({ try { Hub-HubSelfUpdateTimerTick } catch { } })

$script:MainSplit.Panel1.Controls.Add($script:PnlCompanyTreeCard)
$script:MainSplit.Panel1.Controls.Add($script:PnlCompanyButtons)
$script:MainSplit.Panel1.Controls.Add($lblSide)

$tab = New-Object System.Windows.Forms.TabControl
$tab.Dock = [System.Windows.Forms.DockStyle]::Fill
$tab.Padding = New-Object System.Drawing.Point(12, 14)
$tab.Margin = New-Object System.Windows.Forms.Padding(12, 10, 14, 12)
$tab.BackColor = $script:HubUiPageBg
$tab.Appearance = [System.Windows.Forms.TabAppearance]::Normal
$tab.DrawMode = [System.Windows.Forms.TabDrawMode]::OwnerDrawFixed
# FillToRight — вкладки заполняют полосу, без «серого хвоста» и вертикали справа от последней вкладки
$tab.SizeMode = [System.Windows.Forms.TabSizeMode]::FillToRight
$tab.ItemSize = New-Object System.Drawing.Size(120, 46)
$tab.Add_DrawItem({
        param($s, $ev)
        Hub-MainTabControl_DrawItem -Tb ([System.Windows.Forms.TabControl]$s) -E $ev
    })
$tab.Add_HandleCreated({
        param($s, $ev)
        try {
            $tc = [System.Windows.Forms.TabControl]$s
            if ($tc.Handle -ne [IntPtr]::Zero) {
                [void][HubUxTheme]::SetWindowTheme($tc.Handle, '', '')
            }
        } catch { }
    })
$script:TabMain = $tab

$tp1 = New-Object System.Windows.Forms.TabPage
$tp1.Text = 'Операции'
$tp1.UseVisualStyleBackColor = $false
$tp1.BackColor = $script:HubUiPageBg
$tp1.Padding = New-Object System.Windows.Forms.Padding(14, 10, 14, 14)
$script:TpOperations = $tp1

$tpLog = New-Object System.Windows.Forms.TabPage
$tpLog.Text = 'Логи'
$tpLog.UseVisualStyleBackColor = $false
$tpLog.BackColor = $script:HubUiPageBg
$tpLog.Padding = New-Object System.Windows.Forms.Padding(14, 10, 14, 14)
$script:TpLog = $tpLog

$tp2 = New-Object System.Windows.Forms.TabPage
$tp2.Text = 'Справочники'
$tp2.UseVisualStyleBackColor = $false
$tp2.BackColor = $script:HubUiPageBg
$tp2.Padding = New-Object System.Windows.Forms.Padding(14, 10, 14, 14)
$script:TpCatalog = $tp2

$tp3 = New-Object System.Windows.Forms.TabPage
$tp3.Text = 'Чаты'
$tp3.UseVisualStyleBackColor = $false
$tp3.BackColor = $script:HubUiPageBg
$tp3.Padding = New-Object System.Windows.Forms.Padding(14, 10, 14, 14)
$script:TpChats = $tp3

$tp4 = New-Object System.Windows.Forms.TabPage
$tp4.Text = 'Тестеры'
$tp4.UseVisualStyleBackColor = $false
$tp4.BackColor = $script:HubUiPageBg
$tp4.Padding = New-Object System.Windows.Forms.Padding(14, 10, 14, 14)
$script:TpTesters = $tp4

$tp5 = New-Object System.Windows.Forms.TabPage
$tp5.Text = 'Контроль очередей'
$tp5.UseVisualStyleBackColor = $false
$tp5.BackColor = $script:HubUiPageBg
$tp5.Padding = New-Object System.Windows.Forms.Padding(14, 10, 14, 14)
$script:TpQueues = $tp5

$script:PnlQueuesTop = New-Object System.Windows.Forms.Panel
$script:PnlQueuesTop.Dock = [System.Windows.Forms.DockStyle]::Top
$script:PnlQueuesTop.Height = 128
$script:PnlQueuesTop.BackColor = $script:HubUiPageBg

$script:LblQueuesHint = New-Object System.Windows.Forms.Label
$script:LblQueuesHint.Dock = [System.Windows.Forms.DockStyle]::Top
$script:LblQueuesHint.Height = 44
$script:LblQueuesHint.AutoSize = $false
$script:LblQueuesHint.Text = '«Обновить список»: сначала учитываются галочки у компаний и ботов (можно несколько); если ни одной нет — используется только выделенная строка. Типы — model.QueueType Webitel. Фильтры по типу и Team только сужают таблицу.'
$script:LblQueuesHint.TextAlign = [System.Drawing.ContentAlignment]::TopLeft
$script:LblQueuesHint.ForeColor = $script:HubUiMuted
$script:LblQueuesHint.Font = New-Object System.Drawing.Font('Segoe UI', 9)

$flpQueuesBar = New-Object System.Windows.Forms.FlowLayoutPanel
$flpQueuesBar.Dock = [System.Windows.Forms.DockStyle]::Fill
$flpQueuesBar.WrapContents = $true
$flpQueuesBar.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
$flpQueuesBar.Padding = New-Object System.Windows.Forms.Padding(0, 4, 0, 0)
$flpQueuesBar.AutoSize = $false
$flpQueuesBar.BackColor = $script:HubUiPageBg

$script:CmbQueuesTypeFilter = New-Object System.Windows.Forms.ComboBox
$script:CmbQueuesTypeFilter.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
$script:CmbQueuesTypeFilter.Width = 400
$script:CmbQueuesTypeFilter.Height = 28
$script:CmbQueuesTypeFilter.Font = New-Object System.Drawing.Font('Segoe UI', 9)
foreach ($def in @(Hub-QueueControlGetTypeFilterDefinitions)) {
    [void]$script:CmbQueuesTypeFilter.Items.Add([string]$def.Text)
}
$script:CmbQueuesTypeFilter.SelectedIndex = 0
$script:CmbQueuesTypeFilter.Add_SelectedIndexChanged({ try { Hub-QueueControlApplyFiltersToGrid } catch { } })

$script:CmbQueuesTeamFilter = New-Object System.Windows.Forms.ComboBox
$script:CmbQueuesTeamFilter.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
$script:CmbQueuesTeamFilter.Width = 260
$script:CmbQueuesTeamFilter.Height = 28
$script:CmbQueuesTeamFilter.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$script:CmbQueuesTeamFilter.Margin = New-Object System.Windows.Forms.Padding(8, 2, 0, 2)
[void]$script:CmbQueuesTeamFilter.Items.Add('Все команды (Team)')
[void]$script:CmbQueuesTeamFilter.Items.Add($script:QueueControlTeamFilterEmptyLabel)
$script:CmbQueuesTeamFilter.SelectedIndex = 0
$script:CmbQueuesTeamFilter.Add_SelectedIndexChanged({ try { Hub-QueueControlApplyFiltersToGrid } catch { } })

$script:BtnQueuesRefresh = New-Object System.Windows.Forms.Button
$script:BtnQueuesRefresh.Text = 'Обновить список'
$script:BtnQueuesRefresh.AutoSize = $true
$script:BtnQueuesRefresh.MinimumSize = New-Object System.Drawing.Size(200, 34)
$script:BtnQueuesRefresh.Margin = New-Object System.Windows.Forms.Padding(14, 2, 0, 0)
Set-HubButtonStyle -Button $script:BtnQueuesRefresh -Variant Primary
$script:BtnQueuesRefresh.Add_Click({ try { Hub-QueueControlRefreshFromTreeSelection } catch { } })

$lblQueuesAuto = New-Object System.Windows.Forms.Label
$lblQueuesAuto.AutoSize = $true
$lblQueuesAuto.Margin = New-Object System.Windows.Forms.Padding(10, 10, 4, 0)
$lblQueuesAuto.Text = 'Автообновление:'
$lblQueuesAuto.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$lblQueuesAuto.ForeColor = $script:HubUiInk

$script:CmbQueuesAutoRefresh = New-Object System.Windows.Forms.ComboBox
$script:CmbQueuesAutoRefresh.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
$script:CmbQueuesAutoRefresh.Width = 220
$script:CmbQueuesAutoRefresh.Height = 28
$script:CmbQueuesAutoRefresh.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$script:CmbQueuesAutoRefresh.Margin = New-Object System.Windows.Forms.Padding(0, 2, 0, 2)
[void]$script:CmbQueuesAutoRefresh.Items.Add('Без автообновления')
[void]$script:CmbQueuesAutoRefresh.Items.Add('Каждые 10 секунд')
[void]$script:CmbQueuesAutoRefresh.Items.Add('Каждые 30 секунд')
[void]$script:CmbQueuesAutoRefresh.Items.Add('Раз в минуту')
[void]$script:CmbQueuesAutoRefresh.Items.Add('Раз в 30 минут')
[void]$script:CmbQueuesAutoRefresh.Items.Add('Раз в час')
[void]$script:CmbQueuesAutoRefresh.Items.Add('Раз в 3 часа')
$script:CmbQueuesAutoRefresh.SelectedIndex = 0
$script:CmbQueuesAutoRefresh.Add_SelectedIndexChanged({ try { Hub-QueueControlConfigureQueuesAutoTimer } catch { } })

$script:TimerQueuesAuto = New-Object System.Windows.Forms.Timer
$script:TimerQueuesAuto.Add_Tick({ try { Hub-QueueControlRefreshFromTreeSelection -Silent -Async } catch { } })

$script:QueuesRefreshWorker = New-Object System.ComponentModel.BackgroundWorker
$script:QueuesRefreshWorker.add_DoWork({
        param($sender, $e)
        $arg = $e.Argument
        if ($null -eq $arg) {
            $e.Result = $null
            return
        }
        $keyList = @($arg.Keys)
        $acc = New-Object System.Collections.Generic.List[object]
        foreach ($k in $keyList) {
            $ks = [string]$k
            try {
                $items = Hub-QueueControlFetchPagedQueuesForCompanyKey -Key $ks
                foreach ($row in @(Hub-QueueControlBuildRowsForCompany -Key $ks -Items $items -ErrorText '')) {
                    [void]$acc.Add($row)
                }
            } catch {
                foreach ($row in @(Hub-QueueControlBuildRowsForCompany -Key $ks -Items @() -ErrorText ([string]$_.Exception.Message))) {
                    [void]$acc.Add($row)
                }
            }
        }
        $metricsPayload = $null
        $bk = ''
        try { $bk = [string]$arg.BindingKey } catch { }
        if (-not [string]::IsNullOrWhiteSpace($bk)) {
            $b = $arg.Binding
            $head = ('Очередь: ' + [string]$b.Name + '  (id ' + [string]$b.QueueId + ', ' + [string]$b.CompanyKey + ')')
            $at = -1
            $ao = -1
            try {
                $qidB = ([string]$b.QueueId).Trim()
                $ckB = ([string]$b.CompanyKey).Trim()
                foreach ($rw in $acc) {
                    if ($null -eq $rw) { continue }
                    try {
                        if ([string]$rw.CompanyKey -eq $ckB -and ([string]$rw.QueueId).Trim() -eq $qidB) {
                            if ($rw.PSObject.Properties['AgentTotalHint']) { $at = [int]$rw.AgentTotalHint }
                            if ($rw.PSObject.Properties['AgentOnlineHint']) { $ao = [int]$rw.AgentOnlineHint }
                            break
                        }
                    } catch { }
                }
            } catch { }
            try {
                $itemsM = Hub-QueueControlFetchMembersForQueue -Key ([string]$b.CompanyKey) -QueueId ([string]$b.QueueId)
                $cnt = Hub-QueueControlCountMembersActiveWaiting -Items $itemsM
                if ($at -lt 0 -or $ao -lt 0) {
                    try {
                        $stAg = Hub-QueueControlFetchAgentsStatsForQueue -Key ([string]$b.CompanyKey) -QueueId ([string]$b.QueueId)
                        if ($stAg.Ok) {
                            $at = [int]$stAg.Total
                            $ao = [int]$stAg.Online
                        }
                    } catch { }
                }
                $metricsPayload = @{
                    Head          = $head
                    Active        = [int]$cnt.Active
                    Waiting       = [int]$cnt.Waiting
                    ErrorText     = ''
                    AgentsTotal   = $at
                    AgentsOnline  = $ao
                }
            } catch {
                $metricsPayload = @{
                    Head          = $head
                    Active        = 0
                    Waiting       = 0
                    ErrorText     = [string]$_.Exception.Message
                    AgentsTotal   = -1
                    AgentsOnline  = -1
                }
            }
        }
        $e.Result = @{
            AllRows          = @($acc.ToArray())
            StartBindingKey  = $bk
            Metrics          = $metricsPayload
            Silent           = [bool]$arg.Silent
            KeysForLog       = [string]$arg.KeysForLog
        }
    })
$script:QueuesRefreshWorker.add_RunWorkerCompleted({
        param($sender, $e)
        $errEx = $e.Error
        $resPack = $e.Result
        $apply = {
            if ($null -ne $errEx) {
                if ($null -ne $script:TxtLog) {
                    try { Append-Log ('Очереди (фон): ' + $errEx.Exception.Message) } catch { }
                }
                return
            }
            if ($null -eq $resPack) { return }
            $script:QueueControlAllRows = $resPack.AllRows
            Hub-QueueControlRebuildTeamFilterCombo
            Hub-QueueControlApplyFiltersToGrid -PrefetchedMetrics $resPack.Metrics -PrefetchedMetricsBindingKey ([string]$resPack.StartBindingKey)
            if ($null -ne $script:TxtLog -and -not [bool]$resPack.Silent) {
                try { Append-Log ('Очереди: обновлено строк ' + $script:QueueControlAllRows.Count + ' по компаниям: ' + $resPack.KeysForLog + '.') } catch { }
            }
        }
        try {
            if ($null -ne $form -and $form.InvokeRequired) {
                [void]$form.BeginInvoke([action]$apply)
            } else {
                & $apply
            }
        } catch {
            try { & $apply } catch { }
        }
    })

[void]$flpQueuesBar.Controls.Add($script:CmbQueuesTypeFilter)
[void]$flpQueuesBar.Controls.Add($script:CmbQueuesTeamFilter)
[void]$flpQueuesBar.Controls.Add($lblQueuesAuto)
[void]$flpQueuesBar.Controls.Add($script:CmbQueuesAutoRefresh)
[void]$flpQueuesBar.Controls.Add($script:BtnQueuesRefresh)
[void]$script:PnlQueuesTop.Controls.Add($flpQueuesBar)
[void]$script:PnlQueuesTop.Controls.Add($script:LblQueuesHint)

$script:DgvQueues = New-Object System.Windows.Forms.DataGridView
$script:DgvQueues.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:DgvQueues.AllowUserToAddRows = $false
$script:DgvQueues.AllowUserToDeleteRows = $false
$script:DgvQueues.ReadOnly = $false
$script:DgvQueues.EditMode = [System.Windows.Forms.DataGridViewEditMode]::EditProgrammatically
$script:DgvQueues.RowHeadersVisible = $false
$script:DgvQueues.MultiSelect = $false
$script:DgvQueues.SelectionMode = [System.Windows.Forms.DataGridViewSelectionMode]::FullRowSelect
$script:DgvQueues.AutoSizeColumnsMode = [System.Windows.Forms.DataGridViewAutoSizeColumnsMode]::None
$script:DgvQueues.ScrollBars = [System.Windows.Forms.ScrollBars]::Both
$script:DgvQueues.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$script:DgvQueues.BackgroundColor = $script:HubUiCard
$script:DgvQueues.BorderStyle = [System.Windows.Forms.BorderStyle]::None
$script:DgvQueues.GridColor = $script:HubUiBorder
$script:DgvQueues.EnableHeadersVisualStyles = $false
$script:DgvQueues.ColumnHeadersHeight = 34
$script:DgvQueues.ColumnHeadersDefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(248, 250, 252)
$script:DgvQueues.ColumnHeadersDefaultCellStyle.ForeColor = $script:HubUiInk
$script:DgvQueues.ColumnHeadersDefaultCellStyle.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
$script:DgvQueues.DefaultCellStyle.ForeColor = $script:HubUiInk
$script:DgvQueues.DefaultCellStyle.SelectionBackColor = [System.Drawing.Color]::FromArgb(219, 234, 254)
$script:DgvQueues.DefaultCellStyle.SelectionForeColor = $script:HubUiInk
$script:DgvQueues.AlternatingRowsDefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(252, 252, 254)
try {
    $dq = $script:DgvQueues.GetType()
    $dblQ = $dq.GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::NonPublic)
    if ($null -ne $dblQ) { $dblQ.SetValue($script:DgvQueues, $true, $null) }
} catch { }

$colQC = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colQC.Name = 'ColQCompany'
$colQC.HeaderText = 'Компания'
$colQC.ReadOnly = $true
$colQI = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colQI.Name = 'ColQId'
$colQI.HeaderText = 'Id очереди'
$colQI.ReadOnly = $true
$colQN = New-Object System.Windows.Forms.DataGridViewLinkColumn
$colQN.Name = 'ColQName'
$colQN.HeaderText = 'Имя'
$colQN.ReadOnly = $false
$colQN.UseColumnTextForLinkValue = $false
$colQN.TrackVisitedState = $false
$colQN.LinkColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
$colQN.ActiveLinkColor = [System.Drawing.Color]::FromArgb(29, 78, 216)
$colQN.VisitedLinkColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
$colQN.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::Fill
$colQN.ToolTipText = 'Открыть параметры очереди в Webitel (веб)'
$colQCal = New-Object System.Windows.Forms.DataGridViewLinkColumn
$colQCal.Name = 'ColQCalendar'
$colQCal.HeaderText = 'Календарь'
$colQCal.ReadOnly = $false
$colQCal.UseColumnTextForLinkValue = $false
$colQCal.TrackVisitedState = $false
$colQCal.LinkColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
$colQCal.ActiveLinkColor = [System.Drawing.Color]::FromArgb(29, 78, 216)
$colQCal.VisitedLinkColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
$colQCal.ToolTipText = 'Открыть календарь в Webitel (lookups), если известен id.'
$colQSchemas = New-Object System.Windows.Forms.DataGridViewLinkColumn
$colQSchemas.Name = 'ColQSchemas'
$colQSchemas.HeaderText = 'Схема'
$colQSchemas.ReadOnly = $false
$colQSchemas.UseColumnTextForLinkValue = $false
$colQSchemas.TrackVisitedState = $false
$colQSchemas.LinkColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
$colQSchemas.ActiveLinkColor = [System.Drawing.Color]::FromArgb(29, 78, 216)
$colQSchemas.VisitedLinkColor = [System.Drawing.Color]::FromArgb(37, 99, 235)
$colQSchemas.ToolTipText = 'Схемы очереди: Pre-executive, Flow, After-executive — клик по «Schemas» открывает меню со ссылками.'
$colQT = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colQT.Name = 'ColQType'
$colQT.HeaderText = 'Тип'
$colQT.ReadOnly = $true
$colQS = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colQS.Name = 'ColQStatus'
$colQS.HeaderText = 'Статус'
$colQS.ReadOnly = $true
$colQG = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colQG.Name = 'ColQTeam'
$colQG.HeaderText = 'Team'
$colQG.ReadOnly = $true
$colQG.ToolTipText = 'Команда (team), привязанная к очереди в Webitel Engine, если API вернул поле team / teams.'
[void]$script:DgvQueues.Columns.Add($colQC)
[void]$script:DgvQueues.Columns.Add($colQI)
[void]$script:DgvQueues.Columns.Add($colQN)
[void]$script:DgvQueues.Columns.Add($colQCal)
[void]$script:DgvQueues.Columns.Add($colQSchemas)
[void]$script:DgvQueues.Columns.Add($colQT)
[void]$script:DgvQueues.Columns.Add($colQS)
[void]$script:DgvQueues.Columns.Add($colQG)
$script:CmsQueueSchemas = New-Object System.Windows.Forms.ContextMenuStrip
$script:CmsQueueSchemas.ShowImageMargin = $false
$script:HubQueueSchemaMenuItemClickHandler = [System.EventHandler]{
        param($src, $ea)
        try {
            $mi = $src -as [System.Windows.Forms.ToolStripMenuItem]
            if ($null -eq $mi) { return }
            $t = $mi.Tag
            if ($null -eq $t) { return }
            Hub-QueueControlOpenFlowSchemaInBrowser -CompanyKey ([string]$t.CompanyKey) -SchemaId ([string]$t.SchemaId)
        } catch { }
    }
$script:DgvQueues.Add_SizeChanged({ try { Hub-QueuesApplyDgvColumnWidths } catch { } })
$script:DgvQueues.Add_CellContentClick({
        param($sender, $e)
        if ($e.RowIndex -lt 0) { return }
        $dg = $script:DgvQueues
        if ($null -eq $dg) { return }
        $cname = ''
        try { $cname = [string]$dg.Columns[$e.ColumnIndex].Name } catch { return }
        if ($cname -ne 'ColQName' -and $cname -ne 'ColQCalendar' -and $cname -ne 'ColQSchemas') { return }
        try {
            $row = $dg.Rows[$e.RowIndex]
            $tag = $row.Tag
            if ($cname -eq 'ColQName') {
                Hub-QueueControlOpenQueueParametersInBrowser $tag
            } elseif ($cname -eq 'ColQCalendar') {
                Hub-QueueControlOpenCalendarLookupInBrowser $tag
            } else {
                $cellVal = ''
                try { $cellVal = ([string]$row.Cells['ColQSchemas'].Value).Trim() } catch { }
                if ([string]::IsNullOrWhiteSpace($cellVal)) { return }
                $qk = ''
                try { $qk = ([string]$tag.CompanyKey).Trim() } catch { }
                $preId = ''; $preLbl = ''
                try { $preId = ([string]$tag.SchemaPreId).Trim() } catch { }
                try { $preLbl = ([string]$tag.SchemaPreLabel).Trim() } catch { }
                if ([string]::IsNullOrWhiteSpace($preLbl)) { $preLbl = $preId }
                $flId = ''; $flLbl = ''
                try { $flId = ([string]$tag.SchemaFlowId).Trim() } catch { }
                try { $flLbl = ([string]$tag.SchemaFlowLabel).Trim() } catch { }
                if ([string]::IsNullOrWhiteSpace($flLbl)) { $flLbl = $flId }
                $aftId = ''; $aftLbl = ''
                try { $aftId = ([string]$tag.SchemaAfterId).Trim() } catch { }
                try { $aftLbl = ([string]$tag.SchemaAfterLabel).Trim() } catch { }
                if ([string]::IsNullOrWhiteSpace($aftLbl)) { $aftLbl = $aftId }
                $menu = $script:CmsQueueSchemas
                if ($null -eq $menu) { return }
                $menu.Items.Clear()
                $slots = @(
                    @{ Title = 'Pre-executive'; Id = $preId; Label = $preLbl }
                    @{ Title = 'Flow'; Id = $flId; Label = $flLbl }
                    @{ Title = 'After-executive'; Id = $aftId; Label = $aftLbl }
                )
                foreach ($sl in $slots) {
                    $lid = [string]$sl.Id
                    $llb = [string]$sl.Label
                    if ([string]::IsNullOrWhiteSpace($lid) -and [string]::IsNullOrWhiteSpace($llb)) { continue }
                    if ([string]::IsNullOrWhiteSpace($llb)) { $llb = '—' }
                    $mi = New-Object System.Windows.Forms.ToolStripMenuItem
                    $mi.Text = ([string]$sl.Title + ' — ' + $llb)
                    if ([string]::IsNullOrWhiteSpace($lid)) {
                        $mi.Enabled = $false
                    } else {
                        $mi.Tag = @{ CompanyKey = $qk; SchemaId = $lid }
                        $mi.Add_Click($script:HubQueueSchemaMenuItemClickHandler)
                    }
                    [void]$menu.Items.Add($mi)
                }
                if ($menu.Items.Count -eq 0) { return }
                $rect = $dg.GetCellDisplayRectangle($e.ColumnIndex, $e.RowIndex, $false)
                $pt = $dg.PointToScreen([System.Drawing.Point]::new($rect.Left, $rect.Bottom))
                $menu.Show($pt)
            }
        } catch { }
    })
$script:DgvQueues.Add_SelectionChanged({
        if ($script:QueueControlInGridRestore) { return }
        try { Hub-QueueControlRefreshSelectedQueueMetrics } catch { }
    })

$script:QueuesSplit = New-Object System.Windows.Forms.SplitContainer
$script:QueuesSplit.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:QueuesSplit.Orientation = [System.Windows.Forms.Orientation]::Horizontal
$script:QueuesSplit.BorderStyle = [System.Windows.Forms.BorderStyle]::None
$script:QueuesSplit.SplitterWidth = 6
$script:QueuesSplit.Panel1MinSize = 140
$script:QueuesSplit.BackColor = $script:HubUiPageBg
# Panel2MinSize и SplitterDistance не задаём здесь: у контрола ещё ClientSize.Height = 0,
# иначе исключение «SplitterDistance must be between Panel1MinSize and …». См. HubLayoutQueuesTab.

$script:LblQueuesDetailHead = New-Object System.Windows.Forms.Label
$script:LblQueuesDetailHead.Dock = [System.Windows.Forms.DockStyle]::Top
$script:LblQueuesDetailHead.Height = 28
$script:LblQueuesDetailHead.AutoSize = $false
$script:LblQueuesDetailHead.Text = 'Метрики выбранной очереди'
$script:LblQueuesDetailHead.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
$script:LblQueuesDetailHead.Padding = New-Object System.Windows.Forms.Padding(0, 4, 0, 0)
$script:LblQueuesDetailHead.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
$script:LblQueuesDetailHead.ForeColor = $script:HubUiInk
$script:LblQueuesDetailHead.BackColor = $script:HubUiPageBg

$script:DgvQueueMetrics = New-Object System.Windows.Forms.DataGridView
$script:DgvQueueMetrics.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:DgvQueueMetrics.AllowUserToAddRows = $false
$script:DgvQueueMetrics.AllowUserToDeleteRows = $false
$script:DgvQueueMetrics.ReadOnly = $true
$script:DgvQueueMetrics.RowHeadersVisible = $false
$script:DgvQueueMetrics.MultiSelect = $false
$script:DgvQueueMetrics.SelectionMode = [System.Windows.Forms.DataGridViewSelectionMode]::FullRowSelect
$script:DgvQueueMetrics.AutoSizeColumnsMode = [System.Windows.Forms.DataGridViewAutoSizeColumnsMode]::None
$script:DgvQueueMetrics.ScrollBars = [System.Windows.Forms.ScrollBars]::None
$script:DgvQueueMetrics.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$script:DgvQueueMetrics.BackgroundColor = $script:HubUiCard
$script:DgvQueueMetrics.BorderStyle = [System.Windows.Forms.BorderStyle]::None
$script:DgvQueueMetrics.GridColor = $script:HubUiBorder
$script:DgvQueueMetrics.EnableHeadersVisualStyles = $false
$script:DgvQueueMetrics.ColumnHeadersHeight = 30
$script:DgvQueueMetrics.ColumnHeadersDefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(248, 250, 252)
$script:DgvQueueMetrics.ColumnHeadersDefaultCellStyle.ForeColor = $script:HubUiInk
$script:DgvQueueMetrics.ColumnHeadersDefaultCellStyle.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
$script:DgvQueueMetrics.DefaultCellStyle.ForeColor = $script:HubUiInk
$script:DgvQueueMetrics.RowTemplate.Height = 28
try {
    $dm = $script:DgvQueueMetrics.GetType()
    $dblM = $dm.GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::NonPublic)
    if ($null -ne $dblM) { $dblM.SetValue($script:DgvQueueMetrics, $true, $null) }
} catch { }
$colQMn = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colQMn.Name = 'ColQNameMet'
$colQMn.HeaderText = 'Показатель'
$colQMn.ReadOnly = $true
$colQMn.Width = 200
$colQMv = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colQMv.Name = 'ColQValMet'
$colQMv.HeaderText = 'Значение'
$colQMv.ReadOnly = $true
$colQMv.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::Fill
[void]$script:DgvQueueMetrics.Columns.Add($colQMn)
[void]$script:DgvQueueMetrics.Columns.Add($colQMv)

[void]$script:QueuesSplit.Panel1.Controls.Add($script:DgvQueues)
[void]$script:QueuesSplit.Panel2.Controls.Add($script:DgvQueueMetrics)
[void]$script:QueuesSplit.Panel2.Controls.Add($script:LblQueuesDetailHead)

[void]$tp5.Controls.Add($script:QueuesSplit)
[void]$tp5.Controls.Add($script:PnlQueuesTop)

try { Hub-QueueControlSetQueueMetricsUi -Head 'Выберите строку очереди в верхней таблице.' -Active 0 -Waiting 0 -ErrorText '' -AgentsTotal -1 -AgentsOnline -1 } catch { }

$script:HubLayoutQueuesTab = {
        try { Hub-QueuesApplyDgvColumnWidths } catch { }
        $sp = $script:QueuesSplit
        if ($null -eq $sp) { return }
        try {
            $h = [int]$sp.ClientSize.Height
            if ($h -lt 180) { return }
            $sw = [int]$sp.SplitterWidth
            try { $sp.Panel2MinSize = 168 } catch { }
            $min1 = [Math]::Max(100, [int]$sp.Panel1MinSize)
            $min2 = [Math]::Max(100, [int]$sp.Panel2MinSize)
            $max1 = $h - $min2 - $sw
            if ($max1 -lt $min1) { return }
            <# ~73% высоты — список очередей; низ — метрики (типичное соотношение master/detail). #>
            $want = [int][Math]::Round([double]($h - $sw) * 0.73)
            $want = [Math]::Max($min1, [Math]::Min($want, $max1))
            $sp.SplitterDistance = $want
        } catch { }
    }
$script:TpQueues.Add_Resize({ & $script:HubLayoutQueuesTab })

$lblC = New-Object System.Windows.Forms.Label
$lblC.Text = 'КОМАНДЫ'
$lblC.Dock = [System.Windows.Forms.DockStyle]::Top
$lblC.Height = 26
$lblC.Padding = [System.Windows.Forms.Padding]::new(14, 8, 0, 0)
$lblC.ForeColor = $script:HubUiMuted
$lblC.BackColor = $script:HubUiPageBg
$lblC.Font = New-Object System.Drawing.Font('Segoe UI', 8.25, [System.Drawing.FontStyle]::Bold)
$script:LblC = $lblC
$tp1.Controls.Add($lblC)

$script:OpsCommandButtons = New-Object 'System.Collections.Generic.List[System.Windows.Forms.Button]'
$script:PnlOpsCmdHost = New-Object System.Windows.Forms.Panel
$script:PnlOpsCmdHost.AutoScroll = $true
$script:PnlOpsCmdHost.BackColor = $script:HubUiPageBg

$script:FlpOpsCommands = New-Object System.Windows.Forms.FlowLayoutPanel
$script:FlpOpsCommands.FlowDirection = [System.Windows.Forms.FlowDirection]::TopDown
$script:FlpOpsCommands.WrapContents = $false
$script:FlpOpsCommands.AutoSize = $true
$script:FlpOpsCommands.AutoSizeMode = [System.Windows.Forms.AutoSizeMode]::GrowAndShrink
$script:FlpOpsCommands.Padding = New-Object System.Windows.Forms.Padding(0, 2, 0, 4)
$script:FlpOpsCommands.Margin = [System.Windows.Forms.Padding]::Empty
$script:FlpOpsCommands.BackColor = $script:HubUiPageBg
$script:FlpOpsCommands.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:PnlOpsCmdHost.Controls.Add($script:FlpOpsCommands)

$script:PrgOpsProgress = New-Object System.Windows.Forms.ProgressBar
$script:PrgOpsProgress.Dock = [System.Windows.Forms.DockStyle]::Bottom
$script:PrgOpsProgress.Height = 22
$script:PrgOpsProgress.Visible = $false
$script:PrgOpsProgress.Style = [System.Windows.Forms.ProgressBarStyle]::Continuous
$script:PnlOpsCmdHost.Controls.Add($script:PrgOpsProgress)
$script:PrgOpsProgress.BringToFront()

$script:HubOpsCommandDefs = @(
    @{ Id = 0; Text = 'Скачать с прода → current + stable'; Variant = 'Secondary'; Confirm = 'Скачать текущие и stable-схемы с прода для всех отмеченных в дереве ботов?' }
    @{ Id = 1; Text = 'Загрузить на прод (deploy)'; Variant = 'Primary'; Confirm = 'Выполнить deploy на прод для всех отмеченных в дереве ботов?' }
    @{ Id = 2; Text = 'Чек-лист каталога (catalog-checklist)'; Variant = 'Secondary'; Confirm = 'Запустить чек-лист каталога для отмеченных ботов?' }
    @{ Id = 3; Text = 'Проверка связей схемы (validate)'; Variant = 'Secondary'; Confirm = 'Проверить связи схем (validate) для отмеченных ботов?' }
    @{ Id = 4; Text = 'CRM lookup аудит (check-crm-phone-fetch)'; Variant = 'Secondary'; Confirm = 'Запустить CRM lookup аудит для отмеченных ботов?' }
    @{ Id = 5; Text = 'Sync CO result_mapping (каталог CO_)'; Variant = 'Secondary'; Confirm = 'Синхронизировать result_mapping для каталога CO_ из схемы? (если каталога нет — операция завершится ошибкой)' }
    @{ Id = 6; Text = 'Открыть папку schemas\current'; Variant = 'Secondary'; Confirm = 'Открыть папку schemas\current в проводнике?' }
    @{ Id = 7; Text = 'Открыть папку data\catalogs (хаб)'; Variant = 'Secondary'; Confirm = 'Открыть папку data\catalogs в проводнике?' }
    @{ Id = 8; Text = 'Импорт тестеров: catalog.json → data\testers'; Variant = 'Secondary'; Confirm = 'Импортировать тестеров из catalog.json (testers.people) в data\testers для всех ключей хаба?' }
    @{ Id = 9; Text = 'Загрузить новые чаты (очереди + архив)'; Variant = 'Success'; Confirm = 'Обновить чаты для всех компаний: метаданные очередей и догрузка архива диалогов с последней сохранённой даты?' }
)
$script:HubOpsConfirmById = @{}
foreach ($def in $script:HubOpsCommandDefs) {
    $script:HubOpsConfirmById[[int]$def.Id] = [string]$def.Confirm
}
foreach ($def in $script:HubOpsCommandDefs) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = [string]$def.Text
    $b.Height = 36
    $b.Margin = New-Object System.Windows.Forms.Padding(4, 3, 4, 3)
    $b.Tag = [int]$def.Id
    Set-HubButtonStyle -Button $b -Variant ([string]$def.Variant)
    $b.Add_Click({
            $id = [int]$this.Tag
            $msg = [string]$script:HubOpsConfirmById[$id]
            Hub-OpsRunConfirmed -ConfirmMessage $msg -Work { Invoke-HubOperationById -OpId $id }
        })
    [void]$script:FlpOpsCommands.Controls.Add($b)
    [void]$script:OpsCommandButtons.Add($b)
}
$script:FlpOpsCommands.Add_ClientSizeChanged({
        try {
            $iw = [Math]::Max(120, $script:FlpOpsCommands.ClientSize.Width - 12)
            foreach ($c in $script:FlpOpsCommands.Controls) {
                if ($c -is [System.Windows.Forms.Button]) { $c.Width = $iw }
            }
        } catch { }
    })
$tp1.Controls.Add($script:PnlOpsCmdHost)

$script:PnlExecStatus = New-Object System.Windows.Forms.Panel
$script:PnlExecStatus.Height = 36
$script:PnlExecStatus.BackColor = [System.Drawing.Color]::FromArgb(189, 189, 189)
$script:LblExecStatus = New-Object System.Windows.Forms.Label
$script:LblExecStatus.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:LblExecStatus.Text = 'Готово'
$script:LblExecStatus.TextAlign = [System.Drawing.ContentAlignment]::MiddleCenter
$script:LblExecStatus.Font = New-Object System.Drawing.Font('Segoe UI', 10, [System.Drawing.FontStyle]::Bold)
$script:LblExecStatus.ForeColor = [System.Drawing.Color]::FromArgb(33, 33, 33)
$script:PnlExecStatus.Controls.Add($script:LblExecStatus)
$tp1.Controls.Add($script:PnlExecStatus)

$script:PnlIntegrity = New-Object System.Windows.Forms.Panel
$script:PnlIntegrity.BackColor = $script:HubUiPageBg

$script:DgvIntegrity = New-Object System.Windows.Forms.DataGridView
$script:DgvIntegrity.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:DgvIntegrity.AllowUserToAddRows = $false
$script:DgvIntegrity.AllowUserToDeleteRows = $false
$script:DgvIntegrity.ReadOnly = $false
$script:DgvIntegrity.EditMode = [System.Windows.Forms.DataGridViewEditMode]::EditProgrammatically
$script:DgvIntegrity.RowHeadersVisible = $false
$script:DgvIntegrity.MultiSelect = $false
$script:DgvIntegrity.SelectionMode = [System.Windows.Forms.DataGridViewSelectionMode]::FullRowSelect
$script:DgvIntegrity.AutoSizeColumnsMode = [System.Windows.Forms.DataGridViewAutoSizeColumnsMode]::None
$script:DgvIntegrity.ScrollBars = [System.Windows.Forms.ScrollBars]::Vertical
$script:DgvIntegrity.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$script:DgvIntegrity.BackgroundColor = $script:HubUiCard
$script:DgvIntegrity.BorderStyle = [System.Windows.Forms.BorderStyle]::None
$script:DgvIntegrity.GridColor = $script:HubUiBorder
$script:DgvIntegrity.EnableHeadersVisualStyles = $false
$script:DgvIntegrity.ColumnHeadersHeight = 30
$script:DgvIntegrity.ColumnHeadersDefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(248, 250, 252)
$script:DgvIntegrity.ColumnHeadersDefaultCellStyle.ForeColor = $script:HubUiInk
$script:DgvIntegrity.ColumnHeadersDefaultCellStyle.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
$script:DgvIntegrity.DefaultCellStyle.ForeColor = $script:HubUiInk
$script:DgvIntegrity.DefaultCellStyle.WrapMode = [System.Windows.Forms.DataGridViewTriState]::False
$script:DgvIntegrity.AutoSizeRowsMode = [System.Windows.Forms.DataGridViewAutoSizeRowsMode]::None
$script:DgvIntegrity.RowTemplate.Height = 26
try {
    $di = $script:DgvIntegrity.GetType()
    $dblI = $di.GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::NonPublic)
    if ($null -ne $dblI) { $dblI.SetValue($script:DgvIntegrity, $true, $null) }
} catch { }

$colIntComp = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colIntComp.Name = 'ColIntComp'
$colIntComp.HeaderText = 'Компания'
$colIntComp.ReadOnly = $true
$colIntComp.Width = 220
$colIntKind = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colIntKind.Name = 'ColIntKind'
$colIntKind.HeaderText = 'Тип'
$colIntKind.ReadOnly = $true
$colIntKind.Width = 88
$colIntExp = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colIntExp.Name = 'ColIntExpected'
$colIntExp.HeaderText = 'Ожидается'
$colIntExp.ReadOnly = $true
$colIntExp.Width = 200
$colIntOn = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colIntOn.Name = 'ColIntOnEngine'
$colIntOn.HeaderText = 'На Engine'
$colIntOn.ReadOnly = $true
$colIntOn.Width = 220
$colIntSta = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colIntSta.Name = 'ColIntStatus'
$colIntSta.HeaderText = 'Статус'
$colIntSta.ReadOnly = $true
$colIntSta.Width = 48
$colIntSta.DefaultCellStyle.Alignment = [System.Windows.Forms.DataGridViewContentAlignment]::MiddleCenter
$colIntNote = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colIntNote.Name = 'ColIntNote'
$colIntNote.HeaderText = 'Замечания'
$colIntNote.ReadOnly = $true
$colIntNote.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::Fill
[void]$script:DgvIntegrity.Columns.Add($colIntComp)
[void]$script:DgvIntegrity.Columns.Add($colIntKind)
[void]$script:DgvIntegrity.Columns.Add($colIntExp)
[void]$script:DgvIntegrity.Columns.Add($colIntOn)
[void]$script:DgvIntegrity.Columns.Add($colIntSta)
[void]$script:DgvIntegrity.Columns.Add($colIntNote)

$script:PnlIntegrityHead = New-Object System.Windows.Forms.Panel
$script:PnlIntegrityHead.Dock = [System.Windows.Forms.DockStyle]::Top
$script:PnlIntegrityHead.Height = 42
$script:PnlIntegrityHead.BackColor = $script:HubUiPageBg

$script:BtnIntegrityRun = New-Object System.Windows.Forms.Button
$script:BtnIntegrityRun.Text = 'Проверить очереди и календари'
$script:BtnIntegrityRun.Dock = [System.Windows.Forms.DockStyle]::Top
$script:BtnIntegrityRun.Height = 36
$script:BtnIntegrityRun.AutoSize = $false
Set-HubButtonStyle -Button $script:BtnIntegrityRun -Variant Secondary
if ($null -ne $script:ToolTipHubSidebar) {
    $script:ToolTipHubSidebar.SetToolTip($script:BtnIntegrityRun,
        'По отмеченным компаниям/ботам: 9 имён Collection_G1|G2|G3_Main|APTP|BPTP сопоставляются только с очередями типа Predictive dialer (QueueType=5); остальные типы не учитываются. Календари — по справочнику и привязкам очередей. Имя на Engine может быть с пробелами. «Статус»: зелёный — есть, красный — нет.')
}
$script:BtnIntegrityRun.Add_Click({
        try { Hub-IntegrityRefreshGrid } catch {
            if ($null -ne $script:TxtLog) {
                try { Append-Log ('Целостность (кнопка): ' + [string]$_.Exception.Message) } catch { }
            }
        }
    })

$script:LblIntegrityHint = $null
[void]$script:PnlIntegrityHead.Controls.Add($script:BtnIntegrityRun)

[void]$script:PnlIntegrity.Controls.Add($script:DgvIntegrity)
[void]$script:PnlIntegrity.Controls.Add($script:PnlIntegrityHead)
$tp1.Controls.Add($script:PnlIntegrity)

$script:LblLog = New-Object System.Windows.Forms.Label
$script:LblLog.Text = 'ЛОГ'
$script:LblLog.ForeColor = $script:HubUiMuted
$script:LblLog.BackColor = $script:HubUiPageBg
$script:LblLog.Font = New-Object System.Drawing.Font('Segoe UI', 8.25, [System.Drawing.FontStyle]::Bold)
$script:LblLog.AutoSize = $false

$script:TxtLog = New-Object System.Windows.Forms.TextBox
$script:TxtLog.Multiline = $true
$script:TxtLog.ScrollBars = 'Vertical'
$script:TxtLog.ReadOnly = $true
$script:TxtLog.BackColor = $script:HubUiCard
$script:TxtLog.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$script:TxtLog.ForeColor = $script:HubUiInk
[void]$tpLog.Controls.Add($script:TxtLog)
[void]$tpLog.Controls.Add($script:LblLog)

$null = $tab.TabPages.Add($tp1)
$null = $tab.TabPages.Add($tpLog)
$null = $tab.TabPages.Add($tp2)
$null = $tab.TabPages.Add($tp3)
$null = $tab.TabPages.Add($tp4)
$null = $tab.TabPages.Add($tp5)
# Закрашиваем полосу вкладок справа от последней (стандартная отрисовка даёт сетку/«ребро»)
$tab.Add_Paint({
        param($sender, $e)
        $tc = [System.Windows.Forms.TabControl]$sender
        if ($null -eq $tc -or $tc.TabCount -eq 0) { return }
        try {
            $top = $tc.DisplayRectangle.Top
            if ($top -lt 4) { return }
            $rLast = $tc.GetTabRect($tc.TabCount - 1)
            $cr = $tc.ClientRectangle
            if ($rLast.Right -ge ($cr.Width - 1)) { return }
            $br = New-Object System.Drawing.SolidBrush $script:HubUiPageBg
            try {
                $w = [Math]::Max(1, $cr.Width - $rLast.Right)
                $rect = New-Object System.Drawing.Rectangle($rLast.Right, 0, $w, $top)
                $e.Graphics.FillRectangle($br, $rect)
            } finally {
                $br.Dispose()
            }
        } catch { }
    })
$script:MainSplit.Panel2.Controls.Add($tab)
$form.Controls.Add($script:MainSplit)

$script:PnlChatTop = New-Object System.Windows.Forms.Panel
$script:PnlChatTop.Dock = [System.Windows.Forms.DockStyle]::Top
$script:PnlChatTop.Height = 248
$script:PnlChatTop.BackColor = $script:HubUiPageBg
$script:PnlChatTop.Padding = New-Object System.Windows.Forms.Padding(12, 8, 12, 8)

$script:LblChatCompany = New-Object System.Windows.Forms.Label
$script:LblChatCompany.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:LblChatCompany.AutoSize = $false
$script:LblChatCompany.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
$script:LblChatCompany.Padding = New-Object System.Windows.Forms.Padding(0, 4, 0, 4)
$script:LblChatCompany.Text = 'Компания: выберите бота в дереве — чаты из архива; отметьте чат-очереди для фильтра.'
$script:LblChatCompany.ForeColor = $script:HubUiInk
$script:LblChatCompany.Font = New-Object System.Drawing.Font('Segoe UI', 9.5, [System.Drawing.FontStyle]::Bold)

$script:TlpChatToolbar = New-Object System.Windows.Forms.TableLayoutPanel
$script:TlpChatToolbar.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:TlpChatToolbar.ColumnCount = 2
$script:TlpChatToolbar.RowCount = 1
$script:TlpChatToolbar.BackColor = $script:HubUiCard
$script:TlpChatToolbar.Margin = [System.Windows.Forms.Padding]::Empty
$script:TlpChatToolbar.Padding = New-Object System.Windows.Forms.Padding(0, 0, 0, 0)
[void]$script:TlpChatToolbar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, [float]52)))
[void]$script:TlpChatToolbar.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, [float]48)))
[void]$script:TlpChatToolbar.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, [float]100)))

$script:PnlChatLeft = New-Object System.Windows.Forms.Panel
$script:PnlChatLeft.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:PnlChatLeft.Margin = [System.Windows.Forms.Padding]::Empty
$script:PnlChatLeft.BackColor = $script:HubUiCard
$script:PnlChatLeft.Padding = New-Object System.Windows.Forms.Padding(10, 10, 12, 10)

$script:TlpChatLeft = New-Object System.Windows.Forms.TableLayoutPanel
$script:TlpChatLeft.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:TlpChatLeft.ColumnCount = 1
$script:TlpChatLeft.RowCount = 2
[void]$script:TlpChatLeft.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, [float]100)))
[void]$script:TlpChatLeft.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, [float]44)))

$script:ClbChatQueues = New-Object System.Windows.Forms.CheckedListBox
$script:ClbChatQueues.CheckOnClick = $true
$script:ClbChatQueues.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:ClbChatQueues.IntegralHeight = $false
$script:ClbChatQueues.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$script:ClbChatQueues.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$script:ClbChatQueues.Add_ItemCheck({
        param($sender, $ev)
        if ($null -eq $form) { return }
        [void]$form.BeginInvoke([System.Action]{ Hub-ChatApplyQueueFilterAndPopulate })
    })

$script:PnlChatPhoneRow = New-Object System.Windows.Forms.Panel
$script:PnlChatPhoneRow.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:PnlChatPhoneRow.Margin = New-Object System.Windows.Forms.Padding(0, 6, 0, 0)

$script:LblChatPhoneFilter = New-Object System.Windows.Forms.Label
$script:LblChatPhoneFilter.Text = 'Номер (LIKE):'
$script:LblChatPhoneFilter.AutoSize = $true
$script:LblChatPhoneFilter.Location = New-Object System.Drawing.Point(0, 8)
$script:LblChatPhoneFilter.ForeColor = [System.Drawing.Color]::FromArgb(80, 82, 96)

$script:TxtChatPhoneFilter = New-Object System.Windows.Forms.TextBox
$script:TxtChatPhoneFilter.Location = New-Object System.Drawing.Point(108, 4)
$script:TxtChatPhoneFilter.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
$script:TxtChatPhoneFilter.Height = 24
$script:TxtChatPhoneFilter.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$script:TxtChatPhoneFilter.Add_TextChanged({
        if ($null -eq $script:ChatDialogsCache -or @($script:ChatDialogsCache).Count -eq 0) { return }
        Hub-ChatPopulateDialogsGrid
    })
$script:PnlChatPhoneRow.Add_Resize({
        if ($null -eq $script:TxtChatPhoneFilter) { return }
        $script:TxtChatPhoneFilter.Width = [Math]::Max(80, $script:PnlChatPhoneRow.ClientSize.Width - 116)
    })

$script:PnlChatPhoneRow.Controls.Add($script:LblChatPhoneFilter)
$script:PnlChatPhoneRow.Controls.Add($script:TxtChatPhoneFilter)

[void]$script:TlpChatLeft.Controls.Add($script:ClbChatQueues, 0, 0)
[void]$script:TlpChatLeft.Controls.Add($script:PnlChatPhoneRow, 0, 1)
$script:PnlChatLeft.Controls.Add($script:TlpChatLeft)

$script:PnlChatPeriod = New-Object System.Windows.Forms.Panel
$script:PnlChatPeriod.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:PnlChatPeriod.Margin = [System.Windows.Forms.Padding]::Empty
$script:PnlChatPeriod.BackColor = $script:HubUiCard
$script:PnlChatPeriod.Padding = [System.Windows.Forms.Padding]::Empty

$pnlChatPeriodBody = New-Object System.Windows.Forms.Panel
$pnlChatPeriodBody.Dock = [System.Windows.Forms.DockStyle]::Fill
$pnlChatPeriodBody.BackColor = $script:HubUiCard
$pnlChatPeriodBody.AutoScroll = $true
$pnlChatPeriodBody.Padding = New-Object System.Windows.Forms.Padding(12, 10, 12, 4)

$script:RbChatDays = New-Object System.Windows.Forms.RadioButton
$script:RbChatDays.Text = 'За последние (дней):'
$script:RbChatDays.Location = New-Object System.Drawing.Point(4, 6)
$script:RbChatDays.AutoSize = $true
$script:RbChatDays.Checked = $true
$script:RbChatDays.Add_CheckedChanged({ Hub-ChatPeriodModeChanged })

$script:NumChatDays = New-Object System.Windows.Forms.NumericUpDown
$script:NumChatDays.Location = New-Object System.Drawing.Point(188, 2)
$script:NumChatDays.Size = New-Object System.Drawing.Size(64, 24)
$script:NumChatDays.Minimum = 1
$script:NumChatDays.Maximum = 365
$script:NumChatDays.Value = 7
$script:NumChatDays.Add_ValueChanged({
        if ($null -ne $script:TabMain -and $script:TabMain.SelectedTab -eq $script:TpChats) { Hub-ChatRefreshChatsSectionFromArchive }
    })

$script:RbChatRange = New-Object System.Windows.Forms.RadioButton
$script:RbChatRange.Text = 'Диапазон дат (UTC, календарный день):'
$script:RbChatRange.Location = New-Object System.Drawing.Point(4, 38)
$script:RbChatRange.AutoSize = $true
$script:RbChatRange.Add_CheckedChanged({ Hub-ChatPeriodModeChanged })

$script:LblChatFrom = New-Object System.Windows.Forms.Label
$script:LblChatFrom.Text = 'С:'
$script:LblChatFrom.Location = New-Object System.Drawing.Point(8, 66)
$script:LblChatFrom.AutoSize = $true

$script:DtpChatFrom = New-Object System.Windows.Forms.DateTimePicker
$script:DtpChatFrom.Location = New-Object System.Drawing.Point(36, 62)
$script:DtpChatFrom.Width = 148
$script:DtpChatFrom.Format = [System.Windows.Forms.DateTimePickerFormat]::Short
$script:DtpChatFrom.Value = ([DateTime]::Today.AddDays(-7))
$script:DtpChatFrom.Add_ValueChanged({
        if ($null -ne $script:TabMain -and $script:TabMain.SelectedTab -eq $script:TpChats) { Hub-ChatRefreshChatsSectionFromArchive }
    })

$script:LblChatTo = New-Object System.Windows.Forms.Label
$script:LblChatTo.Text = 'По:'
$script:LblChatTo.Location = New-Object System.Drawing.Point(198, 66)
$script:LblChatTo.AutoSize = $true

$script:DtpChatTo = New-Object System.Windows.Forms.DateTimePicker
$script:DtpChatTo.Location = New-Object System.Drawing.Point(230, 62)
$script:DtpChatTo.Width = 148
$script:DtpChatTo.Format = [System.Windows.Forms.DateTimePickerFormat]::Short
$script:DtpChatTo.Value = [DateTime]::Today
$script:DtpChatTo.Add_ValueChanged({
        if ($null -ne $script:TabMain -and $script:TabMain.SelectedTab -eq $script:TpChats) { Hub-ChatRefreshChatsSectionFromArchive }
    })

$pnlChatPeriodBody.Controls.AddRange(@(
        $script:RbChatDays, $script:NumChatDays, $script:RbChatRange,
        $script:LblChatFrom, $script:DtpChatFrom, $script:LblChatTo, $script:DtpChatTo))
$script:PnlChatPeriod.Controls.Add($pnlChatPeriodBody)

[void]$script:TlpChatToolbar.Controls.Add($script:PnlChatLeft, 0, 0)
[void]$script:TlpChatToolbar.Controls.Add($script:PnlChatPeriod, 1, 0)

$script:TlpChatTopWrap = New-Object System.Windows.Forms.TableLayoutPanel
$script:TlpChatTopWrap.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:TlpChatTopWrap.ColumnCount = 1
$script:TlpChatTopWrap.RowCount = 2
[void]$script:TlpChatTopWrap.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, [float]36)))
[void]$script:TlpChatTopWrap.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, [float]100)))
[void]$script:TlpChatTopWrap.Controls.Add($script:LblChatCompany, 0, 0)
[void]$script:TlpChatTopWrap.Controls.Add($script:TlpChatToolbar, 0, 1)
$script:PnlChatTop.Controls.Add($script:TlpChatTopWrap)

$script:ChatSplit = New-Object System.Windows.Forms.SplitContainer
$script:ChatSplit.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:ChatSplit.Orientation = [System.Windows.Forms.Orientation]::Horizontal
# До layout высота по умолчанию мала — большой SplitterDistance сразу падает.
$script:ChatSplit.Panel1MinSize = 1
$script:ChatSplit.Panel2MinSize = 1
$script:ChatSplit.SplitterDistance = 80
$script:ChatSplit.BackColor = $script:HubUiPageBg

$script:PnlChatSrcFilter = New-Object System.Windows.Forms.Panel
$script:PnlChatSrcFilter.Height = 44
$script:PnlChatSrcFilter.Dock = [System.Windows.Forms.DockStyle]::Bottom
$script:PnlChatSrcFilter.BackColor = $script:HubUiTrack
$script:PnlChatSrcFilter.Padding = New-Object System.Windows.Forms.Padding(10, 8, 10, 8)

$script:FlpChatSrc = New-Object System.Windows.Forms.FlowLayoutPanel
$script:FlpChatSrc.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:FlpChatSrc.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
$script:FlpChatSrc.WrapContents = $false
$script:FlpChatSrc.AutoSize = $true
$script:FlpChatSrc.AutoSizeMode = [System.Windows.Forms.AutoSizeMode]::GrowAndShrink
$script:FlpChatSrc.Padding = New-Object System.Windows.Forms.Padding(0, 2, 0, 0)

$lblChatSrc = New-Object System.Windows.Forms.Label
$lblChatSrc.Text = 'Ответчик:'
$lblChatSrc.AutoSize = $true
$lblChatSrc.Margin = New-Object System.Windows.Forms.Padding(0, 6, 12, 0)
$lblChatSrc.ForeColor = [System.Drawing.Color]::FromArgb(55, 58, 70)

$script:RbChatSrcAll = New-Object System.Windows.Forms.RadioButton
$script:RbChatSrcAll.Text = 'Все'
$script:RbChatSrcAll.AutoSize = $true
$script:RbChatSrcAll.Margin = New-Object System.Windows.Forms.Padding(0, 4, 16, 0)
$script:RbChatSrcAll.Checked = $true

$script:RbChatSrcBot = New-Object System.Windows.Forms.RadioButton
$script:RbChatSrcBot.Text = 'Только бот'
$script:RbChatSrcBot.AutoSize = $true
$script:RbChatSrcBot.Margin = New-Object System.Windows.Forms.Padding(0, 4, 16, 0)

$script:RbChatSrcAgent = New-Object System.Windows.Forms.RadioButton
$script:RbChatSrcAgent.Text = 'Только агент'
$script:RbChatSrcAgent.AutoSize = $true
$script:RbChatSrcAgent.Margin = New-Object System.Windows.Forms.Padding(0, 4, 8, 0)

$script:ChatSrcFilterChanged = {
    if ($null -eq $script:ChatDialogsCache -or @($script:ChatDialogsCache).Count -eq 0) { return }
    Hub-ChatPopulateDialogsGrid
}
$script:RbChatSrcAll.Add_CheckedChanged({ if ($script:RbChatSrcAll.Checked) { & $script:ChatSrcFilterChanged } })
$script:RbChatSrcBot.Add_CheckedChanged({ if ($script:RbChatSrcBot.Checked) { & $script:ChatSrcFilterChanged } })
$script:RbChatSrcAgent.Add_CheckedChanged({ if ($script:RbChatSrcAgent.Checked) { & $script:ChatSrcFilterChanged } })

[void]$script:FlpChatSrc.Controls.Add($lblChatSrc)
[void]$script:FlpChatSrc.Controls.Add($script:RbChatSrcAll)
[void]$script:FlpChatSrc.Controls.Add($script:RbChatSrcBot)
[void]$script:FlpChatSrc.Controls.Add($script:RbChatSrcAgent)
$script:PnlChatSrcFilter.Controls.Add($script:FlpChatSrc)

$script:DgvChatDialogs = New-Object System.Windows.Forms.DataGridView
$script:DgvChatDialogs.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:DgvChatDialogs.AllowUserToAddRows = $false
$script:DgvChatDialogs.AllowUserToDeleteRows = $false
$script:DgvChatDialogs.RowHeadersVisible = $false
$script:DgvChatDialogs.MultiSelect = $false
$script:DgvChatDialogs.ReadOnly = $true
$script:DgvChatDialogs.SelectionMode = [System.Windows.Forms.DataGridViewSelectionMode]::FullRowSelect
$script:DgvChatDialogs.AutoSizeColumnsMode = [System.Windows.Forms.DataGridViewAutoSizeColumnsMode]::None
$script:DgvChatDialogs.ScrollBars = [System.Windows.Forms.ScrollBars]::Both
$script:DgvChatDialogs.Font = New-Object System.Drawing.Font('Segoe UI', 9)

$cD = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$cD.Name = 'ColChatDate'
$cD.HeaderText = 'Дата'
$cD.ReadOnly = $true
$cD.Width = 92

$cT = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$cT.Name = 'ColChatTime'
$cT.HeaderText = 'Время'
$cT.ReadOnly = $true
$cT.Width = 86

$cP = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$cP.Name = 'ColChatPhone'
$cP.HeaderText = 'Номер клиента'
$cP.ReadOnly = $true
$cP.Width = 140

$cN = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$cN.Name = 'ColChatName'
$cN.HeaderText = 'ФИО клиента'
$cN.ReadOnly = $true
$cN.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::Fill
$cN.MinimumWidth = 120

$cK = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$cK.Name = 'ColChatDept'
$cK.HeaderText = 'Отдел'
$cK.ReadOnly = $true
$cK.Width = 120

[void]$script:DgvChatDialogs.Columns.Add($cD)
[void]$script:DgvChatDialogs.Columns.Add($cT)
[void]$script:DgvChatDialogs.Columns.Add($cP)
[void]$script:DgvChatDialogs.Columns.Add($cN)
[void]$script:DgvChatDialogs.Columns.Add($cK)

$script:DgvChatDialogs.BackgroundColor = $script:HubUiCard
$script:DgvChatDialogs.BorderStyle = [System.Windows.Forms.BorderStyle]::None
$script:DgvChatDialogs.CellBorderStyle = [System.Windows.Forms.DataGridViewCellBorderStyle]::SingleHorizontal
$script:DgvChatDialogs.GridColor = $script:HubUiBorder
$script:DgvChatDialogs.EnableHeadersVisualStyles = $false
$script:DgvChatDialogs.ColumnHeadersBorderStyle = [System.Windows.Forms.DataGridViewHeaderBorderStyle]::None
$script:DgvChatDialogs.ColumnHeadersDefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(248, 250, 252)
$script:DgvChatDialogs.ColumnHeadersDefaultCellStyle.ForeColor = $script:HubUiInk
$script:DgvChatDialogs.ColumnHeadersDefaultCellStyle.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
$script:DgvChatDialogs.ColumnHeadersHeight = 38
$script:DgvChatDialogs.RowTemplate.Height = 28
$script:DgvChatDialogs.DefaultCellStyle.SelectionBackColor = [System.Drawing.Color]::FromArgb(219, 234, 254)
$script:DgvChatDialogs.DefaultCellStyle.SelectionForeColor = $script:HubUiInk
$script:DgvChatDialogs.AlternatingRowsDefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(252, 252, 254)
try {
    $dgvType = $script:DgvChatDialogs.GetType()
    $dblProp = $dgvType.GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::NonPublic)
    if ($null -ne $dblProp) { $dblProp.SetValue($script:DgvChatDialogs, $true, $null) }
} catch { }

$script:DgvChatDialogs.Add_CurrentCellChanged({ Hub-ChatDialogSelectedChanged })
$script:DgvChatDialogs.Add_CellClick({
        param($Sender, $Ev)
        if ($Ev.RowIndex -lt 0) { return }
        Hub-ChatScheduleTranscriptLoad -DisplayRowIndex $Ev.RowIndex
    })

$script:PnlChatTranscriptShell = New-Object System.Windows.Forms.Panel
$script:PnlChatTranscriptShell.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:PnlChatTranscriptShell.BackColor = [System.Drawing.Color]::FromArgb(232, 236, 242)
$script:PnlChatTranscriptShell.Padding = New-Object System.Windows.Forms.Padding(1, 1, 1, 1)

$script:LblChatTranscriptMeta = New-Object System.Windows.Forms.Label
$script:LblChatTranscriptMeta.Dock = [System.Windows.Forms.DockStyle]::Top
$script:LblChatTranscriptMeta.Height = 76
$script:LblChatTranscriptMeta.Padding = New-Object System.Windows.Forms.Padding(14, 10, 14, 8)
$script:LblChatTranscriptMeta.BackColor = [System.Drawing.Color]::FromArgb(248, 250, 252)
$script:LblChatTranscriptMeta.ForeColor = $script:HubUiMuted
$script:LblChatTranscriptMeta.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Regular)
$script:LblChatTranscriptMeta.Text = 'Выберите диалог в таблице выше.'
$script:LblChatTranscriptMeta.AutoSize = $false
$script:LblChatTranscriptMeta.TextAlign = [System.Drawing.ContentAlignment]::TopLeft

$script:ChatTranscriptSplit = New-Object System.Windows.Forms.SplitContainer
$script:ChatTranscriptSplit.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:ChatTranscriptSplit.Orientation = [System.Windows.Forms.Orientation]::Vertical
$script:ChatTranscriptSplit.SplitterWidth = 5
# До первого layout у SplitContainer ширина по умолчанию мала — сразу 180/180/420 даёт исключение.
$script:ChatTranscriptSplit.Panel1MinSize = 1
$script:ChatTranscriptSplit.Panel2MinSize = 1
$script:ChatTranscriptSplit.SplitterDistance = 60
$script:ChatTranscriptSplit.BackColor = [System.Drawing.Color]::FromArgb(226, 232, 240)

$pnlChatTrOrig = New-Object System.Windows.Forms.Panel
$pnlChatTrOrig.Dock = [System.Windows.Forms.DockStyle]::Fill
$pnlChatTrOrig.Padding = [System.Windows.Forms.Padding]::Empty
$pnlChatTrOrig.BackColor = [System.Drawing.Color]::FromArgb(232, 236, 242)
$lblChatTrOrigHdr = New-Object System.Windows.Forms.Label
$lblChatTrOrigHdr.Dock = [System.Windows.Forms.DockStyle]::Top
$lblChatTrOrigHdr.Height = 24
$lblChatTrOrigHdr.Text = 'Оригинал'
$lblChatTrOrigHdr.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
$lblChatTrOrigHdr.Padding = New-Object System.Windows.Forms.Padding(10, 4, 4, 2)
$lblChatTrOrigHdr.ForeColor = $script:HubUiMuted
$lblChatTrOrigHdr.Font = New-Object System.Drawing.Font('Segoe UI', 8.25, [System.Drawing.FontStyle]::Bold)
$lblChatTrOrigHdr.BackColor = [System.Drawing.Color]::FromArgb(240, 244, 248)

$script:FlpChatTranscript = New-Object System.Windows.Forms.FlowLayoutPanel
$script:FlpChatTranscript.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:FlpChatTranscript.FlowDirection = [System.Windows.Forms.FlowDirection]::TopDown
$script:FlpChatTranscript.WrapContents = $false
$script:FlpChatTranscript.AutoScroll = $true
$script:FlpChatTranscript.Padding = New-Object System.Windows.Forms.Padding(10, 8, 10, 14)
$script:FlpChatTranscript.BackColor = [System.Drawing.Color]::FromArgb(232, 236, 242)
$script:FlpChatTranscript.Margin = [System.Windows.Forms.Padding]::Empty
$script:FlpChatTranscript.Add_Resize({ Hub-ChatReflowTranscriptBubbles })
try {
    $tF = $script:FlpChatTranscript.GetType()
    $dblF = $tF.GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::NonPublic)
    if ($null -ne $dblF) { $dblF.SetValue($script:FlpChatTranscript, $true, $null) }
} catch { }
[void]$pnlChatTrOrig.Controls.Add($lblChatTrOrigHdr)
[void]$pnlChatTrOrig.Controls.Add($script:FlpChatTranscript)

$pnlChatTrRu = New-Object System.Windows.Forms.Panel
$pnlChatTrRu.Dock = [System.Windows.Forms.DockStyle]::Fill
$pnlChatTrRu.Padding = [System.Windows.Forms.Padding]::Empty
$pnlChatTrRu.BackColor = [System.Drawing.Color]::FromArgb(232, 236, 242)
$lblChatTrRuHdr = New-Object System.Windows.Forms.Label
$lblChatTrRuHdr.Dock = [System.Windows.Forms.DockStyle]::Top
$lblChatTrRuHdr.Height = 24
$lblChatTrRuHdr.Text = 'Русский (автоперевод)'
$lblChatTrRuHdr.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
$lblChatTrRuHdr.Padding = New-Object System.Windows.Forms.Padding(10, 4, 4, 2)
$lblChatTrRuHdr.ForeColor = $script:HubUiMuted
$lblChatTrRuHdr.Font = New-Object System.Drawing.Font('Segoe UI', 8.25, [System.Drawing.FontStyle]::Bold)
$lblChatTrRuHdr.BackColor = [System.Drawing.Color]::FromArgb(236, 240, 245)

$script:FlpChatTranscriptRu = New-Object System.Windows.Forms.FlowLayoutPanel
$script:FlpChatTranscriptRu.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:FlpChatTranscriptRu.FlowDirection = [System.Windows.Forms.FlowDirection]::TopDown
$script:FlpChatTranscriptRu.WrapContents = $false
$script:FlpChatTranscriptRu.AutoScroll = $true
$script:FlpChatTranscriptRu.Padding = New-Object System.Windows.Forms.Padding(10, 8, 10, 14)
$script:FlpChatTranscriptRu.BackColor = [System.Drawing.Color]::FromArgb(232, 236, 242)
$script:FlpChatTranscriptRu.Margin = [System.Windows.Forms.Padding]::Empty
$script:FlpChatTranscriptRu.Add_Resize({ Hub-ChatReflowTranscriptBubbles })
try {
    $tR = $script:FlpChatTranscriptRu.GetType()
    $dblR = $tR.GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::NonPublic)
    if ($null -ne $dblR) { $dblR.SetValue($script:FlpChatTranscriptRu, $true, $null) }
} catch { }
[void]$pnlChatTrRu.Controls.Add($lblChatTrRuHdr)
[void]$pnlChatTrRu.Controls.Add($script:FlpChatTranscriptRu)

$script:ChatTranscriptSplit.Panel1.Controls.Add($pnlChatTrOrig)
$script:ChatTranscriptSplit.Panel2.Controls.Add($pnlChatTrRu)

$script:PnlChatTranscriptShell.Controls.Add($script:ChatTranscriptSplit)
$script:PnlChatTranscriptShell.Controls.Add($script:LblChatTranscriptMeta)

$script:ChatSplit.Panel1.Controls.Add($script:PnlChatSrcFilter)
$script:ChatSplit.Panel1.Controls.Add($script:DgvChatDialogs)
$script:ChatSplit.Panel2.Controls.Add($script:PnlChatTranscriptShell)

$tp3.Controls.Add($script:ChatSplit)
$tp3.Controls.Add($script:PnlChatTop)

$tlpTestRoot = New-Object System.Windows.Forms.TableLayoutPanel
$tlpTestRoot.Dock = [System.Windows.Forms.DockStyle]::Fill
$tlpTestRoot.Margin = [System.Windows.Forms.Padding]::Empty
$tlpTestRoot.Padding = [System.Windows.Forms.Padding]::Empty
$tlpTestRoot.BackColor = $script:HubUiPageBg
$tlpTestRoot.ColumnCount = 1
$tlpTestRoot.RowCount = 2
[void]$tlpTestRoot.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, [float]100)))
[void]$tlpTestRoot.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, [float]112)))
[void]$tlpTestRoot.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, [float]100)))

$pnlTestHead = New-Object System.Windows.Forms.Panel
$pnlTestHead.Dock = [System.Windows.Forms.DockStyle]::Fill
$pnlTestHead.Margin = [System.Windows.Forms.Padding]::Empty
$pnlTestHead.Padding = New-Object System.Windows.Forms.Padding(0, 0, 0, 6)
$pnlTestHead.BackColor = $script:HubUiPageBg

$script:LblTestersCompany = New-Object System.Windows.Forms.Label
$script:LblTestersCompany.Dock = [System.Windows.Forms.DockStyle]::Top
$script:LblTestersCompany.AutoSize = $true
$script:LblTestersCompany.MaximumSize = New-Object System.Drawing.Size(2800, 0)
$script:LblTestersCompany.Text = 'Проект: —'
$script:LblTestersCompany.ForeColor = $script:HubUiInk
$script:LblTestersCompany.Font = New-Object System.Drawing.Font('Segoe UI', 9.5, [System.Drawing.FontStyle]::Bold)
$script:LblTestersCompany.Padding = New-Object System.Windows.Forms.Padding(0, 0, 0, 4)

$script:LblTestersPath = New-Object System.Windows.Forms.Label
$script:LblTestersPath.Dock = [System.Windows.Forms.DockStyle]::Top
$script:LblTestersPath.AutoSize = $true
$script:LblTestersPath.MaximumSize = New-Object System.Drawing.Size(2800, 0)
$script:LblTestersPath.Text = 'Файл: —'
$script:LblTestersPath.ForeColor = $script:HubUiMuted
$script:LblTestersPath.Font = New-Object System.Drawing.Font('Segoe UI', 8.75, [System.Drawing.FontStyle]::Regular)
$script:LblTestersPath.Padding = New-Object System.Windows.Forms.Padding(0, 0, 0, 6)

$flpTestDef = New-Object System.Windows.Forms.FlowLayoutPanel
$flpTestDef.Dock = [System.Windows.Forms.DockStyle]::Top
$flpTestDef.AutoSize = $true
$flpTestDef.WrapContents = $false
$flpTestDef.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
$flpTestDef.Padding = [System.Windows.Forms.Padding]::Empty
$flpTestDef.Margin = [System.Windows.Forms.Padding]::Empty
$flpTestDef.BackColor = $script:HubUiPageBg

$lblDefT = New-Object System.Windows.Forms.Label
$lblDefT.AutoSize = $true
$lblDefT.Margin = New-Object System.Windows.Forms.Padding(0, 8, 10, 0)
$lblDefT.Text = 'Дефолтный тестер (id):'
$lblDefT.ForeColor = $script:HubUiInk

$script:CmbTestersDefault = New-Object System.Windows.Forms.ComboBox
$script:CmbTestersDefault.DropDownStyle = [System.Windows.Forms.ComboBoxStyle]::DropDownList
$script:CmbTestersDefault.Width = 240
$script:CmbTestersDefault.Margin = New-Object System.Windows.Forms.Padding(0, 4, 16, 0)

$script:BtnTestersSave = New-Object System.Windows.Forms.Button
$script:BtnTestersSave.Text = 'Сохранить тестеров'
$script:BtnTestersSave.AutoSize = $true
$script:BtnTestersSave.Margin = New-Object System.Windows.Forms.Padding(0, 2, 0, 0)
Set-HubButtonStyle -Button $script:BtnTestersSave -Variant Secondary
$script:BtnTestersSave.Add_Click({ Hub-SaveTestersDocument })

[void]$flpTestDef.Controls.Add($lblDefT)
[void]$flpTestDef.Controls.Add($script:CmbTestersDefault)
[void]$flpTestDef.Controls.Add($script:BtnTestersSave)

[void]$pnlTestHead.Controls.Add($script:LblTestersCompany)
[void]$pnlTestHead.Controls.Add($script:LblTestersPath)
[void]$pnlTestHead.Controls.Add($flpTestDef)

$script:TestersSplit = New-Object System.Windows.Forms.SplitContainer
$script:TestersSplit.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:TestersSplit.Orientation = [System.Windows.Forms.Orientation]::Vertical
$script:TestersSplit.SplitterWidth = 6
# До layout ширина по умолчанию мала — 120/200/268 даёт исключение при Panel2MinSize.
$script:TestersSplit.Panel1MinSize = 1
$script:TestersSplit.Panel2MinSize = 1
$script:TestersSplit.SplitterDistance = 60
$script:TestersSplit.BackColor = $script:HubUiPageBg

$lblTestList = New-Object System.Windows.Forms.Label
$lblTestList.Dock = [System.Windows.Forms.DockStyle]::Top
$lblTestList.Height = 26
$lblTestList.Text = 'Тестеры'
$lblTestList.ForeColor = $script:HubUiMuted
$lblTestList.Font = New-Object System.Drawing.Font('Segoe UI', 8.25, [System.Drawing.FontStyle]::Bold)
$lblTestList.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
$lblTestList.Padding = New-Object System.Windows.Forms.Padding(0, 0, 0, 4)

$script:LstTesters = New-Object System.Windows.Forms.ListBox
$script:LstTesters.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:LstTesters.BorderStyle = [System.Windows.Forms.BorderStyle]::FixedSingle
$script:LstTesters.IntegralHeight = $false
$script:LstTesters.Font = New-Object System.Drawing.Font('Segoe UI', 9.5)
$script:LstTesters.BackColor = $script:HubUiCard
$script:LstTesters.Add_SelectedIndexChanged({ Hub-TestersListSelectedChanged })

$flpTestersActions = New-Object System.Windows.Forms.FlowLayoutPanel
$flpTestersActions.Dock = [System.Windows.Forms.DockStyle]::Bottom
$flpTestersActions.AutoSize = $false
$flpTestersActions.Height = 42
$flpTestersActions.WrapContents = $false
$flpTestersActions.FlowDirection = [System.Windows.Forms.FlowDirection]::LeftToRight
$flpTestersActions.Padding = New-Object System.Windows.Forms.Padding(0, 6, 0, 6)
$flpTestersActions.Margin = [System.Windows.Forms.Padding]::Empty
$flpTestersActions.BackColor = $script:HubUiPageBg

$script:BtnTestersAdd = New-Object System.Windows.Forms.Button
$script:BtnTestersAdd.Text = 'Добавить'
$script:BtnTestersAdd.AutoSize = $true
$script:BtnTestersAdd.Margin = New-Object System.Windows.Forms.Padding(0, 0, 10, 0)
Set-HubButtonStyle -Button $script:BtnTestersAdd -Variant Secondary
$script:BtnTestersAdd.Add_Click({ Hub-TestersAddNewClick })

$script:BtnTestersRemove = New-Object System.Windows.Forms.Button
$script:BtnTestersRemove.Text = 'Удалить'
$script:BtnTestersRemove.AutoSize = $true
Set-HubButtonStyle -Button $script:BtnTestersRemove -Variant Secondary
$script:BtnTestersRemove.Add_Click({ Hub-TestersRemoveClick })

[void]$flpTestersActions.Controls.Add($script:BtnTestersAdd)
[void]$flpTestersActions.Controls.Add($script:BtnTestersRemove)

# Порядок важен: последний в Controls стыкуется первым — снизу панель кнопок (Bottom), сверху заголовок (Top), список Fill между ними.
[void]$script:TestersSplit.Panel1.Controls.Add($script:LstTesters)
[void]$script:TestersSplit.Panel1.Controls.Add($lblTestList)
[void]$script:TestersSplit.Panel1.Controls.Add($flpTestersActions)

$lblTestDet = New-Object System.Windows.Forms.Label
$lblTestDet.Dock = [System.Windows.Forms.DockStyle]::Top
$lblTestDet.Height = 26
$lblTestDet.Text = 'Данные выбранного тестера'
$lblTestDet.ForeColor = $script:HubUiMuted
$lblTestDet.Font = New-Object System.Drawing.Font('Segoe UI', 8.25, [System.Drawing.FontStyle]::Bold)
$lblTestDet.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
$lblTestDet.Padding = New-Object System.Windows.Forms.Padding(0, 0, 0, 4)

$script:DgvTestersDetail = New-Object System.Windows.Forms.DataGridView
$script:DgvTestersDetail.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:DgvTestersDetail.AllowUserToAddRows = $false
$script:DgvTestersDetail.AllowUserToDeleteRows = $false
$script:DgvTestersDetail.ReadOnly = $true
$script:DgvTestersDetail.RowHeadersVisible = $false
$script:DgvTestersDetail.MultiSelect = $false
$script:DgvTestersDetail.SelectionMode = [System.Windows.Forms.DataGridViewSelectionMode]::FullRowSelect
$script:DgvTestersDetail.AutoSizeColumnsMode = [System.Windows.Forms.DataGridViewAutoSizeColumnsMode]::None
$script:DgvTestersDetail.ScrollBars = [System.Windows.Forms.ScrollBars]::Both
$script:DgvTestersDetail.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$script:DgvTestersDetail.BackgroundColor = $script:HubUiCard
$script:DgvTestersDetail.BorderStyle = [System.Windows.Forms.BorderStyle]::None
$script:DgvTestersDetail.GridColor = $script:HubUiBorder
$script:DgvTestersDetail.EnableHeadersVisualStyles = $false
$script:DgvTestersDetail.ColumnHeadersHeight = 34
$script:DgvTestersDetail.ColumnHeadersDefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(248, 250, 252)
$script:DgvTestersDetail.ColumnHeadersDefaultCellStyle.ForeColor = $script:HubUiInk
$script:DgvTestersDetail.ColumnHeadersDefaultCellStyle.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
$script:DgvTestersDetail.DefaultCellStyle.ForeColor = $script:HubUiInk
$script:DgvTestersDetail.DefaultCellStyle.SelectionBackColor = [System.Drawing.Color]::FromArgb(219, 234, 254)
$script:DgvTestersDetail.DefaultCellStyle.SelectionForeColor = $script:HubUiInk
$script:DgvTestersDetail.AlternatingRowsDefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(252, 252, 254)
try {
    $tdgv = $script:DgvTestersDetail.GetType()
    $dblTd = $tdgv.GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::NonPublic)
    if ($null -ne $dblTd) { $dblTd.SetValue($script:DgvTestersDetail, $true, $null) }
} catch { }

$cTk = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$cTk.HeaderText = 'Поле'
$cTk.Name = 'ColTesterKey'
$cTk.ReadOnly = $true
$cTk.Width = 200
$cTv = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$cTv.HeaderText = 'Значение'
$cTv.Name = 'ColTesterVal'
$cTv.ReadOnly = $true
$cTv.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::Fill
$cTa = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$cTa.Name = 'ColTesterAddr'
$cTa.HeaderText = 'Адрес (схема)'
$cTa.ReadOnly = $true
$cTa.Width = 200
$cTa.ToolTipText = 'Тот же шаблон, что в справочнике: узел wa_promt_gpt.schema_node из активного catalog.json и имя поля, напр. ${httpRequest__…}.destination.'
[void]$script:DgvTestersDetail.Columns.Add($cTk)
[void]$script:DgvTestersDetail.Columns.Add($cTv)
[void]$script:DgvTestersDetail.Columns.Add($cTa)
$script:DgvTestersDetail.Add_SizeChanged({ try { Hub-TestersApplyDgvColumnWidths } catch { } })

[void]$script:TestersSplit.Panel2.Controls.Add($script:DgvTestersDetail)
[void]$script:TestersSplit.Panel2.Controls.Add($lblTestDet)

[void]$tlpTestRoot.Controls.Add($pnlTestHead, 0, 0)
[void]$tlpTestRoot.Controls.Add($script:TestersSplit, 0, 1)
$script:TpTesters.Controls.Add($tlpTestRoot)

$script:HubLayoutTestersTab = {
        $tp = $script:TpTesters
        if ($null -eq $tp) { return }
        $w = [int]$tp.ClientSize.Width
        if ($w -lt 360) { return }
        if ($null -ne $script:TestersSplit) {
            $ts = $script:TestersSplit
            $sw = [int]$ts.SplitterWidth
            $p1W = 120
            $p2W = 280
            if ($w -le ($p1W + $p2W + $sw + 16)) { return }
            $sd = [int][Math]::Round([Math]::Max(160, [Math]::Min(400, $w * 0.30)))
            $maxSd = $w - $p2W - $sw - 8
            if ($maxSd -le $p1W) { return }
            $sd = [Math]::Max($p1W, [Math]::Min($sd, $maxSd))
            try {
                $ts.Panel1MinSize = 1
                $ts.Panel2MinSize = 1
                $ts.SplitterDistance = $sd
                $ts.Panel1MinSize = $p1W
                $ts.Panel2MinSize = $p2W
            } catch { }
        }
        try { Hub-TestersApplyDgvColumnWidths } catch { }
    }
$script:TpTesters.Add_Resize({ & $script:HubLayoutTestersTab })

Hub-ChatPeriodModeChanged

$pnlCatTop = New-Object System.Windows.Forms.Panel
$script:PnlCatalogTop = $pnlCatTop
$pnlCatTop.Dock = [System.Windows.Forms.DockStyle]::Fill
$pnlCatTop.MinimumSize = New-Object System.Drawing.Size(0, 118)
$pnlCatTop.Height = 118
$pnlCatTop.BackColor = $script:HubUiCard
$pnlCatTop.Padding = New-Object System.Windows.Forms.Padding(0, 0, 0, 8)

$script:LblCatalogPath = New-Object System.Windows.Forms.Label
$script:LblCatalogPath.Text = '(нажмите «Загрузить» после выбора компании)'
$script:LblCatalogPath.Location = New-Object System.Drawing.Point(14, 10)
$script:LblCatalogPath.Height = 56
$script:LblCatalogPath.ForeColor = $script:HubUiMuted
$script:LblCatalogPath.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Left -bor [System.Windows.Forms.AnchorStyles]::Right
$script:LblCatalogPath.AutoSize = $false
$pnlCatTop.Controls.Add($script:LblCatalogPath)

$script:BtnCatLoad = New-Object System.Windows.Forms.Button
$script:BtnCatLoad.Text = 'Загрузить'
$script:BtnCatLoad.Size = New-Object System.Drawing.Size(128, 36)
$script:BtnCatLoad.Top = 56
$script:BtnCatLoad.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Right
$script:BtnCatLoad.Add_Click({ Hub-LoadCatalogEditor })
$pnlCatTop.Controls.Add($script:BtnCatLoad)

$script:BtnCatSave = New-Object System.Windows.Forms.Button
$script:BtnCatSave.Text = 'Сохранить'
$script:BtnCatSave.Size = New-Object System.Drawing.Size(128, 36)
$script:BtnCatSave.Top = 56
$script:BtnCatSave.Anchor = [System.Windows.Forms.AnchorStyles]::Top -bor [System.Windows.Forms.AnchorStyles]::Right
$script:BtnCatSave.Add_Click({ Hub-SaveCatalogEditor })
$pnlCatTop.Controls.Add($script:BtnCatSave)

Set-HubButtonStyle -Button $script:BtnCatLoad -Variant Primary
Set-HubButtonStyle -Button $script:BtnCatSave -Variant Secondary
if ($null -ne $script:ToolTipHubSidebar) {
    $script:ToolTipHubSidebar.SetToolTip($script:BtnCatSave,
        ('Записывает catalog.json текущего загруженного проекта (путь в шапке). Значения — в дерево JSON; подписи и адреса — в ключ «{0}» (titles / addresses).' -f $script:CatalogEditorMetaKey))
}

$script:DgvCatalog = New-Object System.Windows.Forms.DataGridView
$script:DgvCatalog.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:DgvCatalog.AllowUserToAddRows = $false
$script:DgvCatalog.AllowUserToDeleteRows = $false
$script:DgvCatalog.RowHeadersVisible = $false
$script:DgvCatalog.MultiSelect = $false
$script:DgvCatalog.SelectionMode = [System.Windows.Forms.DataGridViewSelectionMode]::FullRowSelect
$script:DgvCatalog.AutoSizeColumnsMode = [System.Windows.Forms.DataGridViewAutoSizeColumnsMode]::None
$script:DgvCatalog.ScrollBars = [System.Windows.Forms.ScrollBars]::Both
$script:DgvCatalog.Font = New-Object System.Drawing.Font('Segoe UI', 9)
$script:DgvCatalog.BackgroundColor = $script:HubUiCard
$script:DgvCatalog.BorderStyle = [System.Windows.Forms.BorderStyle]::None
$script:DgvCatalog.CellBorderStyle = [System.Windows.Forms.DataGridViewCellBorderStyle]::SingleHorizontal
$script:DgvCatalog.GridColor = $script:HubUiBorder
$script:DgvCatalog.EnableHeadersVisualStyles = $false
$script:DgvCatalog.ColumnHeadersBorderStyle = [System.Windows.Forms.DataGridViewHeaderBorderStyle]::Single
$script:DgvCatalog.ColumnHeadersHeight = 38
$script:DgvCatalog.ColumnHeadersBorderStyle = [System.Windows.Forms.DataGridViewHeaderBorderStyle]::None
$script:DgvCatalog.ColumnHeadersDefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(248, 250, 252)
$script:DgvCatalog.ColumnHeadersDefaultCellStyle.ForeColor = $script:HubUiInk
$script:DgvCatalog.ColumnHeadersDefaultCellStyle.Font = New-Object System.Drawing.Font('Segoe UI', 9, [System.Drawing.FontStyle]::Bold)
$script:DgvCatalog.DefaultCellStyle.BackColor = $script:HubUiCard
$script:DgvCatalog.DefaultCellStyle.ForeColor = $script:HubUiInk
$script:DgvCatalog.DefaultCellStyle.SelectionBackColor = [System.Drawing.Color]::FromArgb(219, 234, 254)
$script:DgvCatalog.DefaultCellStyle.SelectionForeColor = $script:HubUiInk
$script:DgvCatalog.AlternatingRowsDefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(252, 252, 254)
$script:DgvCatalog.RowTemplate.Height = 26

$colTitle = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colTitle.Name = 'ColTitle'
$colTitle.HeaderText = 'Параметр'
$colTitle.ReadOnly = $false
$colTitle.Width = 220

$colVal = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colVal.Name = 'ColValue'
$colVal.HeaderText = 'Значение'
$colVal.ReadOnly = $false
$colVal.AutoSizeMode = [System.Windows.Forms.DataGridViewAutoSizeColumnMode]::Fill

$colAddr = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colAddr.Name = 'ColAddr'
$colAddr.HeaderText = 'Адрес (схема)'
$colAddr.ReadOnly = $false
$colAddr.ToolTipText = 'Узел Webitel и переменная, напр. ${httpRequest__847c788cb56c4076}.${destination} — для деплоя и поиска в JSON схемы.'

$colP = New-Object System.Windows.Forms.DataGridViewTextBoxColumn
$colP.Name = 'ColPath'
$colP.HeaderText = 'Path'
$colP.Visible = $false

[void]$script:DgvCatalog.Columns.Add($colTitle)
[void]$script:DgvCatalog.Columns.Add($colVal)
[void]$script:DgvCatalog.Columns.Add($colAddr)
[void]$script:DgvCatalog.Columns.Add($colP)

$script:DgvCatalog.Add_SizeChanged({ try { Hub-CatalogApplyDgvColumnWidths } catch { } })
$script:DgvCatalog.Add_CellValueChanged({
        param($Sender, $Ev)
        if ($script:CatalogGridSuppressEvents) { return }
        if ($Ev.RowIndex -lt 0) { return }
        if ($null -eq $script:DgvCatalog.Columns[$Ev.ColumnIndex]) { return }
        $nm = $script:DgvCatalog.Columns[$Ev.ColumnIndex].Name
        if ($nm -ne 'ColValue' -and $nm -ne 'ColTitle' -and $nm -ne 'ColAddr') { return }
        Hub-CatalogSyncEditRowFromGrid -RowIndex $Ev.RowIndex
    })
$script:DgvCatalog.Add_RowPrePaint({
        param($Sender, $Ev)
        if ($Ev.RowIndex -lt 0) { return }
        $row = $Sender.Rows[$Ev.RowIndex]
        if ($null -eq $row -or $row.IsNewRow) { return }
        $pc = $row.Cells['ColPath'].Value
        $p = if ($null -eq $pc) { '' } else { [string]$pc }
        $baseOdd = $Sender.AlternatingRowsDefaultCellStyle.BackColor
        $baseEven = $Sender.DefaultCellStyle.BackColor
        $baseBg = if (($Ev.RowIndex % 2) -eq 1) { $baseOdd } else { $baseEven }
        if ($p -match ('^(?i)' + [regex]::Escape($script:CatalogUiMissingGlobalPathPrefix) + '\.')) {
            $row.DefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(254, 226, 226)
            return
        }
        if ($p -match '(?i)^webitel_global_variables\.([^.]+)\.') {
            $gk = $Matches[1]
            $refs = $script:CatalogGlobalSchemaRefKeys
            if ($null -ne $refs -and $refs.Contains($gk)) {
                $row.DefaultCellStyle.BackColor = [System.Drawing.Color]::FromArgb(220, 252, 231)
                return
            }
        }
        $row.DefaultCellStyle.BackColor = $baseBg
    })
try {
    $dgvCatType = $script:DgvCatalog.GetType()
    $dblCat = $dgvCatType.GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::NonPublic)
    if ($null -ne $dblCat) { $dblCat.SetValue($script:DgvCatalog, $true, $null) }
} catch { }

$script:PnlCatalogBodyShell = New-Object System.Windows.Forms.Panel
$script:PnlCatalogBodyShell.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:PnlCatalogBodyShell.Margin = [System.Windows.Forms.Padding]::Empty
$script:PnlCatalogBodyShell.Padding = [System.Windows.Forms.Padding]::Empty
$script:PnlCatalogBodyShell.BackColor = $script:HubUiPageBg
try {
    $shType = $script:PnlCatalogBodyShell.GetType()
    $dblSh = $shType.GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::NonPublic)
    if ($null -ne $dblSh) { $dblSh.SetValue($script:PnlCatalogBodyShell, $true, $null) }
} catch { }

$script:PnlCatalogGroups = New-Object System.Windows.Forms.Panel
$script:PnlCatalogGroups.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:PnlCatalogGroups.Margin = [System.Windows.Forms.Padding]::Empty
$script:PnlCatalogGroups.Padding = [System.Windows.Forms.Padding]::Empty
$script:PnlCatalogGroups.BackColor = $script:HubUiCard

$script:PnlCatalogGutter = New-Object System.Windows.Forms.Panel
$script:PnlCatalogGutter.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:PnlCatalogGutter.Margin = [System.Windows.Forms.Padding]::Empty
$script:PnlCatalogGutter.Padding = [System.Windows.Forms.Padding]::Empty
$script:PnlCatalogGutter.BackColor = $script:HubUiBorder

$script:PnlCatalogGridHost = New-Object System.Windows.Forms.Panel
$script:PnlCatalogGridHost.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:PnlCatalogGridHost.Margin = [System.Windows.Forms.Padding]::Empty
$script:PnlCatalogGridHost.Padding = New-Object System.Windows.Forms.Padding(4, 0, 0, 0)
$script:PnlCatalogGridHost.BackColor = $script:HubUiCard

$lblCatGroups = New-Object System.Windows.Forms.Label
$lblCatGroups.Dock = [System.Windows.Forms.DockStyle]::Top
$lblCatGroups.AutoSize = $true
$lblCatGroups.TextAlign = [System.Drawing.ContentAlignment]::MiddleLeft
$lblCatGroups.Padding = New-Object System.Windows.Forms.Padding(2, 0, 8, 6)
$lblCatGroups.Text = 'ГРУППЫ'
$lblCatGroups.ForeColor = $script:HubUiMuted
$lblCatGroups.Font = New-Object System.Drawing.Font('Segoe UI', 8.25, [System.Drawing.FontStyle]::Bold)
$lblCatGroups.Margin = [System.Windows.Forms.Padding]::Empty

$script:FlpCatalogPills = New-Object System.Windows.Forms.FlowLayoutPanel
$script:FlpCatalogPills.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:FlpCatalogPills.WrapContents = $false
$script:FlpCatalogPills.AutoScroll = $true
$script:FlpCatalogPills.FlowDirection = [System.Windows.Forms.FlowDirection]::TopDown
$script:FlpCatalogPills.Padding = New-Object System.Windows.Forms.Padding(4, 0, 4, 8)
$script:FlpCatalogPills.BackColor = $script:HubUiCard
$script:FlpCatalogPills.Margin = [System.Windows.Forms.Padding]::Empty
$script:FlpCatalogPills.Add_Resize({ Hub-CatalogLayoutPillWidths })

$tlpCatGroupsHost = New-Object System.Windows.Forms.TableLayoutPanel
$tlpCatGroupsHost.Dock = [System.Windows.Forms.DockStyle]::Fill
$tlpCatGroupsHost.Padding = New-Object System.Windows.Forms.Padding(10, 6, 8, 8)
$tlpCatGroupsHost.BackColor = $script:HubUiCard
$tlpCatGroupsHost.ColumnCount = 1
$tlpCatGroupsHost.RowCount = 3
[void]$tlpCatGroupsHost.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, [float]100)))
[void]$tlpCatGroupsHost.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
[void]$tlpCatGroupsHost.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, [float]100)))
[void]$tlpCatGroupsHost.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::AutoSize)))
[void]$tlpCatGroupsHost.Controls.Add($lblCatGroups, 0, 0)

$script:PnlCatalogGlobalActions = New-Object System.Windows.Forms.Panel
$script:PnlCatalogGlobalActions.Dock = [System.Windows.Forms.DockStyle]::Top
$script:PnlCatalogGlobalActions.AutoSize = $true
$script:PnlCatalogGlobalActions.Margin = [System.Windows.Forms.Padding]::Empty
$script:PnlCatalogGlobalActions.Padding = New-Object System.Windows.Forms.Padding(4, 10, 4, 8)
$script:PnlCatalogGlobalActions.BackColor = $script:HubUiCard
$script:PnlCatalogGlobalActions.Visible = $false

$script:BtnCatLoadGlobals = New-Object System.Windows.Forms.Button
$script:BtnCatLoadGlobals.Text = 'Загрузить глобальные переменные'
$script:BtnCatLoadGlobals.AutoSize = $true
$script:BtnCatLoadGlobals.AutoSizeMode = [System.Windows.Forms.AutoSizeMode]::GrowAndShrink
$script:BtnCatLoadGlobals.Margin = New-Object System.Windows.Forms.Padding(0, 0, 0, 0)
$script:BtnCatLoadGlobals.Add_Click({ Hub-LoadWebitelGlobalVariablesIntoCatalog })
[void]$script:PnlCatalogGlobalActions.Controls.Add($script:BtnCatLoadGlobals)
Set-HubButtonStyle -Button $script:BtnCatLoadGlobals -Variant Secondary
if ($null -ne $script:ToolTipHubSidebar) {
    $script:ToolTipHubSidebar.SetToolTip($script:BtnCatLoadGlobals,
        ('Запрос к Webitel (curl): подбирается путь к датасету «{0}» (system%2FglobalVariables или /system/globalVariables и др.). Перезаписывает webitel_global_variables в памяти; при необходимости нажмите «Сохранить».' -f $script:WebitelGlobalVariablesDatasetId))
}

[void]$tlpCatGroupsHost.Controls.Add($script:FlpCatalogPills, 0, 1)
[void]$tlpCatGroupsHost.Controls.Add($script:PnlCatalogGlobalActions, 0, 2)

[void]$script:PnlCatalogGroups.Controls.Add($tlpCatGroupsHost)
[void]$script:PnlCatalogGridHost.Controls.Add($script:DgvCatalog)

$script:TlpCatalogInner = New-Object System.Windows.Forms.TableLayoutPanel
$script:TlpCatalogInner.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:TlpCatalogInner.Margin = [System.Windows.Forms.Padding]::Empty
$script:TlpCatalogInner.Padding = [System.Windows.Forms.Padding]::Empty
$script:TlpCatalogInner.BackColor = $script:HubUiPageBg
$script:TlpCatalogInner.ColumnCount = 3
$script:TlpCatalogInner.RowCount = 1
[void]$script:TlpCatalogInner.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 268)))
[void]$script:TlpCatalogInner.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 6)))
[void]$script:TlpCatalogInner.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, [float]100)))
[void]$script:TlpCatalogInner.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, [float]100)))
try {
    $tInner = $script:TlpCatalogInner.GetType()
    $dblIn = $tInner.GetProperty('DoubleBuffered', [System.Reflection.BindingFlags]::Instance -bor [System.Reflection.BindingFlags]::NonPublic)
    if ($null -ne $dblIn) { $dblIn.SetValue($script:TlpCatalogInner, $true, $null) }
} catch { }
[void]$script:TlpCatalogInner.Controls.Add($script:PnlCatalogGroups, 0, 0)
[void]$script:TlpCatalogInner.Controls.Add($script:PnlCatalogGutter, 1, 0)
[void]$script:TlpCatalogInner.Controls.Add($script:PnlCatalogGridHost, 2, 0)
[void]$script:PnlCatalogBodyShell.Controls.Add($script:TlpCatalogInner)

$script:TlpCatalogPageRoot = New-Object System.Windows.Forms.TableLayoutPanel
$script:TlpCatalogPageRoot.Dock = [System.Windows.Forms.DockStyle]::Fill
$script:TlpCatalogPageRoot.Margin = [System.Windows.Forms.Padding]::Empty
$script:TlpCatalogPageRoot.Padding = [System.Windows.Forms.Padding]::Empty
$script:TlpCatalogPageRoot.BackColor = $script:HubUiPageBg
$script:TlpCatalogPageRoot.ColumnCount = 1
$script:TlpCatalogPageRoot.RowCount = 2
[void]$script:TlpCatalogPageRoot.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, [float]100)))
[void]$script:TlpCatalogPageRoot.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 118)))
[void]$script:TlpCatalogPageRoot.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Percent, [float]100)))
[void]$script:TlpCatalogPageRoot.Controls.Add($pnlCatTop, 0, 0)
[void]$script:TlpCatalogPageRoot.Controls.Add($script:PnlCatalogBodyShell, 0, 1)
$tp2.Controls.Add($script:TlpCatalogPageRoot)

$script:HubLayoutCatalogTab = {
        if ($null -eq $script:PnlCatalogTop) { return }
        $iw = [int]$script:PnlCatalogTop.ClientSize.Width
        if ($iw -lt 80) { return }
        $script:LblCatalogPath.Width = [Math]::Max(120, $iw - 28)
        $script:BtnCatSave.Left = $iw - $script:BtnCatSave.Width - 12
        $script:BtnCatLoad.Left = $script:BtnCatSave.Left - $script:BtnCatLoad.Width - 10
        if ($null -eq $script:TlpCatalogInner) { return }
        $swInner = [int]$script:TlpCatalogInner.ClientSize.Width
        if ($swInner -lt 200) { return }
        $gutter = 6
        $minRight = 260
        $minLeft = 200
        $maxLeft = $swInner - $gutter - $minRight - 2
        if ($maxLeft -lt $minLeft) { return }
        $ideal = [int][Math]::Round([Math]::Min(320, [Math]::Max($minLeft, ($swInner - $gutter) * 0.28)))
        $leftW = [Math]::Min($ideal, $maxLeft)
        if ($leftW -ge $minLeft -and $script:TlpCatalogInner.ColumnStyles.Count -ge 2) {
            $script:TlpCatalogInner.ColumnStyles[0].Width = [float]$leftW
            $script:TlpCatalogInner.ColumnStyles[1].Width = [float]$gutter
            try { $script:TlpCatalogInner.PerformLayout() } catch { }
        }
        try { Hub-CatalogLayoutPillWidths } catch { }
        try { Hub-CatalogApplyDgvColumnWidths } catch { }
    }

$script:HubLayoutChatsTab = {
        $tp = $script:TpChats
        if (-not $tp) { return }
        $h = $tp.ClientSize.Height
        if ($h -lt 220) { return }
        if ($null -ne $script:PnlChatTop -and $null -ne $script:ChatSplit) {
            $cs = $script:ChatSplit
            $hdr = [Math]::Max(200, $script:PnlChatTop.Height)
            $avail = $h - $hdr - $cs.SplitterWidth - 8
            $p1H = 100
            $p2H = 100
            if ($avail -gt ($p1H + $p2H + 20)) {
                $want = [int]($avail * 0.42)
                $want = [Math]::Max($p1H, [Math]::Min($want, $avail - $p2H - 20))
                try {
                    $cs.Panel1MinSize = 1
                    $cs.Panel2MinSize = 1
                    $cs.SplitterDistance = $want
                    $cs.Panel1MinSize = $p1H
                    $cs.Panel2MinSize = $p2H
                } catch { }
            }
        }
        if ($null -ne $script:PnlChatPhoneRow) { $script:PnlChatPhoneRow.PerformLayout() }
        if ($null -ne $script:ChatTranscriptSplit -and $null -ne $script:PnlChatTranscriptShell) {
            $cw = [int]$script:PnlChatTranscriptShell.ClientSize.Width
            $sw = [int]$script:ChatTranscriptSplit.SplitterWidth
            $cts = $script:ChatTranscriptSplit
            if ($cw -gt 80) {
                try {
                    $p1Want = 180
                    $p2Want = 180
                    if ($cw -gt ($p1Want + $p2Want + $sw + 24)) {
                        $maxSd = $cw - $p2Want - $sw - 12
                        $minSd = $p1Want + 24
                        if ($maxSd -gt $minSd) {
                            $sd = [int][Math]::Round($cw * 0.5) - 3
                            $sd = [Math]::Max($minSd, [Math]::Min($sd, $maxSd))
                            $cts.Panel1MinSize = 1
                            $cts.Panel2MinSize = 1
                            $cts.SplitterDistance = $sd
                            $cts.Panel1MinSize = $p1Want
                            $cts.Panel2MinSize = $p2Want
                        }
                    }
                    else {
                        $m = [Math]::Max(1, [Math]::Min(100, [int](($cw - $sw - 8) / 2)))
                        $maxSd2 = $cw - $m - $sw - 2
                        $minSd2 = $m
                        if ($maxSd2 -gt $minSd2) {
                            $sd2 = [Math]::Max($minSd2, [Math]::Min($maxSd2, [int]($cw / 2)))
                            $cts.Panel1MinSize = 1
                            $cts.Panel2MinSize = 1
                            $cts.SplitterDistance = $sd2
                            $cts.Panel1MinSize = $m
                            $cts.Panel2MinSize = $m
                        }
                    }
                } catch { }
            }
        }
        try { Hub-ChatReflowTranscriptBubbles } catch { }
    }

$script:HubLayoutOpsTab = {
        $tp = $script:TpOperations
        if (-not $tp) { return }
        $h = $tp.ClientSize.Height
        $w = $tp.ClientSize.Width
        $pl = [int]$tp.Padding.Left
        $pr = [int]$tp.Padding.Right
        $pt = [int]$tp.Padding.Top
        $pb = [int]$tp.Padding.Bottom
        $m = 4 + $pl
        $listTop = $pt + $script:LblC.Height + 6
        $cmdH = [Math]::Max(160, [Math]::Min(400, [int]($h * 0.38)))
        $script:PnlOpsCmdHost.SetBounds($m, $listTop, [Math]::Max(200, $w - $pl - $pr - 8), $cmdH)
        $script:PnlExecStatus.Left = $m
        $script:PnlExecStatus.Top = $script:PnlOpsCmdHost.Bottom + 8
        $script:PnlExecStatus.Width = $w - $pl - $pr - 8
        if ($null -ne $script:PnlIntegrity) {
            $intTop = $script:PnlExecStatus.Bottom + 8
            $script:PnlIntegrity.SetBounds($m, $intTop, [Math]::Max(200, $w - $pl - $pr - 8), [Math]::Max(140, $h - $intTop - $pb - 4))
        }
        if ($null -ne $script:FlpOpsCommands) {
            try {
                $iw = [Math]::Max(120, $script:FlpOpsCommands.ClientSize.Width - 12)
                foreach ($c in $script:FlpOpsCommands.Controls) {
                    if ($c -is [System.Windows.Forms.Button]) { $c.Width = $iw }
                }
            } catch { }
        }
    }

$script:HubLayoutLogTab = {
        $tp = $script:TpLog
        if (-not $tp) { return }
        if ($null -eq $script:LblLog -or $null -eq $script:TxtLog) { return }
        $h = $tp.ClientSize.Height
        $w = $tp.ClientSize.Width
        $pl = [int]$tp.Padding.Left
        $pr = [int]$tp.Padding.Right
        $pt = [int]$tp.Padding.Top
        $pb = [int]$tp.Padding.Bottom
        $m = 4 + $pl
        $script:LblLog.SetBounds($m, $pt + 2, [Math]::Max(120, $w - $pl - $pr - 8), 24)
        $script:TxtLog.SetBounds($m, $script:LblLog.Bottom + 6, [Math]::Max(120, $w - $pl - $pr - 8), [Math]::Max(120, $h - $script:LblLog.Bottom - 6 - $pb))
    }

$script:HubLayoutCompanyPanel = {
        if ($null -ne $script:TlpCompanyActions) {
            $script:TlpCompanyActions.PerformLayout()
        }
    }

$tab.Add_SelectedIndexChanged({
        $tab.Invalidate()
        if ($tab.SelectedTab -eq $script:TpCatalog) {
            Hub-LoadCatalogEditor
        }
        if ($tab.SelectedTab -eq $script:TpChats) {
            & $script:HubLayoutChatsTab
            Hub-ChatRefreshChatsSectionFromArchive
        }
        if ($tab.SelectedTab -eq $script:TpTesters) {
            & $script:HubLayoutTestersTab
            Hub-RefreshTestersTab
        }
        if ($tab.SelectedTab -eq $script:TpQueues) {
            & $script:HubLayoutQueuesTab
        }
        if ($tab.SelectedTab -eq $script:TpLog) {
            & $script:HubLayoutLogTab
        }
        if ($tab.SelectedTab -eq $script:TpOperations) {
            try { & $script:HubLayoutOpsTab } catch { }
            try {
                if ($null -ne $script:DgvIntegrity -and [int]$script:DgvIntegrity.RowCount -le 0) {
                    Hub-IntegrityRefreshGrid
                }
            } catch { }
        }
    })

$tpLog.Add_Resize({ try { & $script:HubLayoutLogTab } catch { } })
$tp2.Add_Resize($script:HubLayoutCatalogTab)
$tp3.Add_Resize($script:HubLayoutChatsTab)
$tp5.Add_Resize($script:HubLayoutQueuesTab)

$form.Add_Shown({
        Hub-ApplyMainSplitLayout
        Hub-RefreshCompanyTree
        if ($null -ne $script:TimerCompanyTreeClock) {
            try { $script:TimerCompanyTreeClock.Start() } catch { }
        }
        if ($null -ne $script:TimerHubSelfUpdate) {
            try { $script:TimerHubSelfUpdate.Start() } catch { }
        }
        & $script:HubLayoutOpsTab
        & $script:HubLayoutLogTab
        & $script:HubLayoutCatalogTab
        & $script:HubLayoutChatsTab
        & $script:HubLayoutTestersTab
        & $script:HubLayoutQueuesTab
        & $script:HubLayoutCompanyPanel
        if ($null -ne $script:TabMain -and $script:TabMain.SelectedTab -eq $script:TpChats) {
            Hub-ChatRefreshChatsSectionFromArchive
        }
        if ($null -ne $script:TabMain -and $script:TabMain.SelectedTab -eq $script:TpTesters) {
            Hub-RefreshTestersTab
        }
        try { Hub-IntegrityRefreshGrid } catch {
            if ($null -ne $script:TxtLog) {
                try { Append-Log ('Целостность (авто): ' + [string]$_.Exception.Message) } catch { }
            }
        }
    })
$form.Add_Resize({
        Hub-ApplyMainSplitLayout
        & $script:HubLayoutOpsTab
        & $script:HubLayoutLogTab
        & $script:HubLayoutCatalogTab
        & $script:HubLayoutChatsTab
        & $script:HubLayoutTestersTab
        & $script:HubLayoutQueuesTab
        & $script:HubLayoutCompanyPanel
    })

Set-HubExecutionStatus -State idle
Append-Log (
    "Репозиторий: $($script:RepoRoot)" + [Environment]::NewLine +
    "Схемы: $($script:SchemasDir)" + [Environment]::NewLine +
    "Хаб: $($script:HubDir)" + [Environment]::NewLine +
    "Каталоги компаний (registry, catalog.json): $($script:HubCatalogsRoot)" + [Environment]::NewLine +
    "Архив чатов (локально, по компаниям): $($script:HubChatsArchiveRoot) — догрузка архива и очередей: кнопка «Загрузить новые чаты» на вкладке «Операции»." + [Environment]::NewLine +
    "Тестеры: $($script:HubTestersRoot)\*.json + автослияние с catalog.json → testers.people (вкладка «Тестеры»); массовая запись — команда «Импорт тестеров: catalog…» на вкладке «Операции»." + [Environment]::NewLine +
    "Слева дерево компаний → типы ботов: отметьте галочкой ботов для операций; справочник открывается по первой отмеченной паре (или по выбранному узлу). «Перечитать deploy-config» подхватывает правки JSON с диска." + [Environment]::NewLine +
    "Текстовый лог — вкладка «Логи»; на «Операциях» — чек-лист очередей и календарей по компаниям (кнопка «Проверить…»)." + [Environment]::NewLine +
    "Если AventusBotHub.ps1 на диске новее запуска, хаб перезапустится (~45 с) для применения изменений.")

[System.Windows.Forms.Application]::EnableVisualStyles()
[void]$form.ShowDialog()


