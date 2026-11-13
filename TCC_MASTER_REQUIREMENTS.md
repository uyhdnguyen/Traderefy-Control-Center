# TCC Master Requirements — 2026-11-13

This document is the implementation contract for future work. Do not silently drop requirements.

## Architecture
- TCC is the main large Windows trading command center, with only two main tabs: Dashboard and Journal. No Dashboard sub-tabs.
- Six NinjaTrader charts: ES, NQ, YM, each with TUS on M5 and TEE on 699 tick. TEM handles execution in NinjaTrader.
- NinjaTrader chart indicators must remain usable if TCC is disconnected.
- Real, bidirectional, instrument/account-scoped sync; heartbeat is not proof of full engine connectivity.

## Dashboard
- One screen: all three markets, TUS/TEE/TEM health, trend meter, ATR, bias, ORB, IBS/FTR/FTR-2 setups, pending approvals, active trades/orders, risk, trade plans, forward tests, strategy manager, levels, diagnostics.
- Compact existing TUS dark blue/slate visual style. Do not change approved colors without preview/approval.
- Show no fake live numbers. Clearly distinguish not-connected, stale, and verified data.

## Journal
- Preserve Trading-Journal-AI Overview, Trade Log, Calendar, Reports, R/R multiples, daily/weekly/monthly/YTD, drawdown, Exit Lab, Diary, Edge, Brain, analytics.
- Read actual TUS master trades, executions, approved trades, tags, manual groups, account resets, Playback Mode. Never double-count legs/fills. Playback must be isolated from forward tests.
- Import/sync journal data into underlying analytics with idempotency and conflict handling; preserve user annotations.

## NinjaTrader Quick Tools
- Compact, movable, collapsible overlay with exactly three equal-sized button slots per row: Candle Info, Leg Counter, ORB Range, Trend Meter, Key Levels, Sync Levels.
- Preserve chart drawings, signal markers and small NinjaTrader-local Cancel/Flatten emergency path.
- Remove oversized chart dashboard only after corresponding TCC functions are proven.

## Level Sync
- Versioned, instrument-scoped levels and labels, source chart, timestamps, add/move/delete, no duplicate loops.
- Synchronize custom levels, PDH/PDL, RTH/ORB, support/resistance and liquidity where supported between same-instrument M5/699 and TCC.

## Trade Control
- Preserve IBS/FTR/FTR-2 entries at 50%, two legs, TP1/TP2, stops, breakeven, trailing, invalidation, SIM forward tests.
- Setup status progression: coming, detected, approval pending, limit working, filled, rejected, cancelled, expired.
- TEM must independently validate SIM account, symbol, signal freshness, idempotency, risk and state. No live execution without separate authorization/testing. Existing protective orders must survive TCC disconnect.

## Telegram later
- Connect via TCC for alerts, chart screenshots, approvals/rejections and authorized SIM remote commands; authenticate, expire commands, acknowledge and prevent duplicates.

## Release discipline
- Review all affected source together. Ship coordinated, complete sources; show visual previews before visual changes; preserve working features; test backend, frontend and NinjaTrader separately; mark untested explicitly.
