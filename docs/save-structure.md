# Archery Duels — real save structure (discovered 2026-06-16)

Captured by `dump_one_player.py` against the live universe `10297420029`
(~1841 players at time of writing). This is the **ground truth** the Postgres
schema + ETL are modelled on — not the Lua config (which describes intent, not
on-the-wire shape).

## DataStore mechanics — identical to ocean-quest

- One standard DataStore **per player**, named `DATA/{userId}`.
- Entry keys inside each store are **numeric versions** (`1`, `2`, `3`, …);
  the latest save is the **highest** key.
- So discovery (`^DATA/(\d{5,})$`) and "fetch latest" logic port verbatim
  from ocean-quest's `dump_all_players.py`.

## Top-level keys

A combined save has four sections: `INVENTORY`, `METRICS`, `SETTINGS`, `STATS`.

### INVENTORY
```
currencies: { coins:int, crystals:int }
equipment:  { "<uuid>": { item_id:str, level:int, rank:int, dupes:int, acquiredAt:unix } }  # one entry per owned instance
equipped:   { Axe:"<uuid>", Bow:"<uuid>", Spear:"<uuid>" }   # which instance is equipped per weapon slot
revision:   int
```

### STATS  (gameplay-authoritative)
```
aggregate:  { wins, losses, matchesPlayed, arrowsFired, arrowsHit, headshots,
              currentWinStreak, longestWinStreak }   # all int
perMode:    { bot:{...same 6 combat fields...}, pvp:{...} }
dailyLogin: { dayIndex:int, lastClaimDay:str }
dailyPlaytime: { dayKey:"YYYY-MM-DD", seconds:int, claimed:{ Coins10..MythicChest:bool } }
dailyQuests:   { dayKey:str, progress:{ headshot,login,winAxe,winBot,winBow,winSpear:int }, claimed:[bool x6] }
lifetimeWinsForChests: int
moneyPotion:   { expiry:unix }
oneTimeClaims: { communityGift:bool }
revision:      int
```

### METRICS  (analytics-only; matches PlayerMetricsConfig.lua)
```
sessions:   { totalCount, totalPlaytime, longestSession, firstJoinDate, lastJoinDate,
              daysPlayed:int, daysPlayedSet:{ "YYYY-MM-DD":true } }
load:       { lastMs:int, count:int, buckets:[6] }                 # LOAD_TIME_BUCKETS
clicks:     { playMatch, playMatchSuccessful, botMatch, botMatchSuccessful, firstPlayClickAt }
matches:    { played:int, lengthBuckets:[6], firstWin:{bot,pvp}, firstLoss:{bot,pvp} }  # first*: seconds-from-first-join, 0=not yet
shootDelay: { bot:{count, buckets:[6]}, pvp:{count, buckets:[6]} }  # SHOOT_DELAY_BUCKETS
aim:        { count, buckets:[6], tapFires, withAimShots }          # AIM_HOLD_BUCKETS — the headline metric
monetization:{ robuxPurchases, firstPurchaseAt, chestOpens:{Small,Medium,Large,MythicChest}, purchaseLog:[capped] }
engagement: { dailyLoginClaims, dailyQuestClaims, screenOpens:{ "<ScreenName>":count } }
revision:   int
```

Bucket edges (single source of truth lives in `PlayerMetricsConfig.lua`):
- `AIM_HOLD_BUCKETS    = {0.15, 0.4, 0.8, 1.5, 3.0}`  (seconds; <=0.15 = "tap")
- `SHOOT_DELAY_BUCKETS = {1, 2, 4, 7, 12}`            (seconds)
- `MATCH_LENGTH_BUCKETS= {30, 60, 120, 240, 480}`     (seconds)
- `LOAD_TIME_BUCKETS   = {2000, 4000, 7000, 12000, 20000}` (ms)

Each `buckets` array is length 6 = `#edges + 1` (trailing "+" bucket).

### SETTINGS
```
aimSensitivity:float, musicVolume:num, sfxVolume:num, revision:int
```

## ETL gotchas (confirmed across sampled players)

- **Empty Lua tables serialize as JSON `[]`, not `{}`.** So map-shaped fields
  (`engagement.screenOpens`, `monetization.purchaseLog`, `daysPlayedSet`) arrive
  as a **list when empty**, a **dict when populated**, or **absent (`None`)** on
  older saves. ETL must accept all three and only iterate when it's a dict.
- `matches.firstWin/firstLoss.{bot,pvp}` are **seconds from first join to that
  milestone**, `0` = not achieved (not a count).
- Unix timestamps are seconds (e.g. `firstJoinDate`). `0` = unset.
- Treat the full blob as the safety net: store it in `data JSONB`, flatten only
  hot scalars, and reach into JSONB for the long tail.
