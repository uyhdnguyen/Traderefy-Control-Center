# Traderefy Control Center R10 - end-to-end pipeline check (read-only).
# Run while TCC is open:   powershell -ExecutionPolicy Bypass -File tools\Verify-TCC.ps1
# Optional:                -Base http://127.0.0.1:8010  -Import   (runs an import first)
param([string]$Base = 'http://127.0.0.1:8010', [switch]$Import)

$ErrorActionPreference = 'Stop'
$fail = 0
function Ok($m)   { Write-Host "  [OK]   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Bad($m)  { Write-Host "  [FAIL] $m" -ForegroundColor Red; $script:fail++ }
function Get-Api($path) { Invoke-RestMethod -Uri ($Base + $path) -TimeoutSec 20 }

Write-Host "`n1. TCC backend at $Base"
try { $d = Get-Api '/api/tcc/diagnostics'; Ok "TCC $($d.tcc_version) responding (database: $($d.database_path))" }
catch { Bad "No R10 backend on $Base ($($_.Exception.Message)). Is TCC R10 installed and open? The desktop app uses port 8010."; exit 1 }
if ($d.tcc_version -ne 'R10') { Warn "VERSION reports '$($d.tcc_version)', expected R10 - an older build may be installed." }

Write-Host "`n2. NinjaTrader folders"
if ($d.ninjatrader_dir) { Ok "NinjaTrader folder: $($d.ninjatrader_dir)" } else { Bad "NinjaTrader 8 folder not found. Checked: $($d.ninjatrader_candidates -join ' | ')" }
if ($d.journal_root) { Ok "TUS journal: $($d.journal_root)" } else { Bad "TUS_Trade_Master.csv not found. Checked: $(($d.journal_paths_checked | ForEach-Object { $_.path }) -join ' | ')" }
$tmp = $d.bridge_discovery.tmp_count
if ($tmp -gt 1000) { Warn "$tmp abandoned .tmp files in tus_sim_bridge (cleanup instructions in R10_RELEASE_NOTES.md)" }

Write-Host "`n3. Journal import (TUS -> Trading Journal database)"
if ($Import) { $r = Invoke-RestMethod -Method Post -Uri ($Base + '/api/tus/import/run') -TimeoutSec 60; Write-Host "     import: inserted=$($r.inserted) updated=$($r.updated) unchanged=$($r.unchanged) error=$($r.error)" }
$s = Get-Api '/api/tus/import/status'
if ($s.last_successful_import) { Ok "Last import $($s.last_successful_import.finished_at): seen $($s.last_successful_import.seen), new $($s.last_successful_import.inserted)" }
else { Bad "No successful import yet. Auto-import enabled: $($s.auto_import.enabled); last error: $($s.auto_import.last_error)" }
foreach ($a in $s.accounts) {
  $mode = if ($a.playback) { 'Playback (excluded from All Accounts)' } else { 'SIM/live' }
  Write-Host ("     {0,-22} {1,-38} trades={2,-4} net={3}" -f $a.tus_account, $mode, $a.journal_trades, $a.net_pnl)
}
$j = Get-Api '/api/tus/journal/snapshot'
$missing = @($j.trades | Where-Object { -not $_.journal })
if ($j.trade_count -gt 0 -and $missing.Count -eq 0) { Ok "All $($j.trade_count) TUS trades are in the journal database" }
elseif ($j.trade_count -gt 0) { Bad "$($missing.Count) of $($j.trade_count) TUS trades not imported yet (run with -Import)" }

Write-Host "`n4. Live engines per market (each engine checked from its own file)"
$live = Get-Api '/api/tcc/live'
Write-Host "     Market session: $(if ($live.market_session.open) {'open'} else {'closed'}) ($($live.market_session.et_time) ET); automation mode: $($live.execution_mode.value)"
foreach ($m in $live.markets) {
  if (-not $m.root) { Warn "$($m.family): no TUS/TEE charts publishing ($($m.detail))"; continue }
  $e = $m.engines
  $line = "{0} ({1} {2}): TUS M5={3} ({4}s)  TEE 699={5} ({6}s)  TEM={7} ({8}/{9} live)" -f $m.family, $m.root, $m.instrument,
    $e.tus_m5.state, $e.tus_m5.age_seconds, $e.tee_699.state, $e.tee_699.age_seconds, $e.tem.state, $e.tem.live_instances, $e.tem.instances
  if ($m.state -eq 'live') { Ok $line } elseif ($live.market_session.open) { Warn $line } else { Write-Host "  [INFO] $line (market closed)" }
  if ($m.levels.orb.high) { Write-Host "     ORB $($m.levels.orb.high) / $($m.levels.orb.low); trend overall=$($m.trend.overall) PP=$($m.trend.pp) M15=$($m.trend.m15) M60=$($m.trend.m60)" }
}

Write-Host "`nResult: $(if ($fail) {"$fail check(s) failed"} else {'all required checks passed'})`n"
exit $fail
