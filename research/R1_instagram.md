# R1 Instagram / archive-seller notes (2026-11-24)

Output: `data/taxonomy/sellers.yaml` (54 accounts, 2 webshops, 5 hashtags, 42-handle weekly list).

## Honest status
- Result is below the 50 *verified* target. 54 entries exist, but only 7 are confidence high and 28 med; 19 are low/verify (handle seen only as a search-result title, no content).
- "Verified" here means the handle string appeared in a source URL (article or imginn.com mirror page). I could not open Instagram or any article: WebFetch failed with DNS errors for imginn.com, highsnobiety.com, dazeddigital.com, sabukaru.online (hosts not in the session network allowlist). Everything comes from WebSearch snippets (24 of 25 searches used, 0 fetches succeeded).
- Seeds (crybynoonarchive, archivethreads, youthwastedpoorly, nevernined, myprettiarchive, junki_ichikawa, realabayan) are user-provided; searches returned nothing independent for them, so they are `med` + `verify: true`, sourced to research/TASTE_PROFILE.md. `alabayan` is low (name seen only as "Al Abayan" in an archivepdf.net interview title).
- Follower bands, regions and brand focus are mostly UNKNOWN or inferred from the snippet; do not trust them without checking.

## What worked
- Query pattern `Instagram story viewer archive <brand list>` returns imginn.com profile mirrors, whose URL proves the handle exists and whose snippet shows stock. Best source of real sellers (verifyd.archive, archivalcloset, hitpoint.arch, hikikomourning, shopveldt, swgscool, archivepluh, trashedpalace, trynaflip, boringblind).
- Editorial lists (Dazed, Russh, Fader, ZoneModa 2023 study) yield curator/fan-archive handles, not sellers; useful for taste signal, low for deal flow. Weighted 0.2-0.5.
- Snippet-level evidence: boringblind is Miami-based, ~2.2k followers, Raf Simons and Dior focus. glam_archive: Dazed article. swgscool listed Dior Homme AW05 "Blue Luster" waxed denim, Rick Owens FW07 "Exploder" jacket. archivepluh: Rick Owens FW03 "Trucker"-era jacket, Saint Laurent Chelsea boots. verifyd.archive: Number (N)ine SS07 cargo zip hoodie and AW05 piece.

## Thin sub-scenes
- ballhog and y2k_designer: no seller handles found beyond trashedpalace (Balmain). No ballhog-specific accounts surfaced.
- chanel_glam: only glam_archive plus fan archives (chanel_archive, chanel_archives).
- jp_archive stores: Tokyo shops (Kindal, Bazz Store) have handles only from travel guides; Archive Store Shibuya, Rinkan, ZSC, Kissmet, Amore: handles NOT found (names in sabukaru/timeout results).
- Grailed usernames: zero found. Named Grailed sellers without handles: DHCULT (2019 Hedi sale), Little Sister New York (2018 Number (N)ine "A Closed Feeling" and Undercover "Rebel Clothes" sales). Next step: search Grailed directly.
- Webshops: only two Shopify-pattern URLs (driewgarments.com, marais.com.au); IG owner handles unknown. Neither is a verified IG seller's shop; products.json untested.
- Hashtags: only seed tags (archivefashion, ballhog, diorhomme, hedislimane, numbernine); in-use status not verified because tag pages are not reachable.

## Surprises
- Search tool is poor at handle discovery; imginn mirrors were the only productive channel.
- hedislimanehomme (Hedi's own 2024 account) is a useful era-reference feed, not a seller.
- Non-Instagram leads seen but excluded or not used: eBay stores, Carousell, Vestiaire profiles (no Depop/Vinted used).

## Sources (key)
- https://imginn.com/<handle>/ for each seller entry (see per-account sources)
- https://www.dazeddigital.com/fashion/article/70733/1/glam-archive-rare-fashion-dealer-bangkok-best-dressed-2010s-fashion
- https://zmj.unibo.it/article/download/20921/19194/88327
- https://www.russh.com/best-vintage-fashion-instagram-accounts/
- https://www.klook.com/en-AU/blog/streetwear-guide-tokyo
- https://www.archivepdf.net/articles/uncovering-number-nine-interview-with-al-abayan
