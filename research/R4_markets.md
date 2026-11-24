# R4 - Markets, comps, Japan costs (2026-11-24)

Method constraints: 25 searches used. WebFetch could reach only GitHub (not apify.com, pypi.org, federalregister.gov, docs sites), so most mechanics come from search-result text and Apify listing summaries. Everything marked "memory" is low confidence. No live tests were run (firewall); every source has `live_test.status: not_tested`.

## Source verdicts
- Grailed: direct (Algolia, public search-only key scraped from page each run; key rotates per Apify actors). Sold via a separate sold index. Index names are "reported by Apify actors, re-discover at runtime". App id is memory only.
- Mercari US: Apify (Cloudflare + DPoP-signed GraphQL; actors ~$2-2.5/1k). No trustworthy open-source scraper found; GitHub hits are 0-5 star repos.
- Mercari JP: library `mercapi` (take-kun, MIT). Search supports sort by created time desc (source comment: order "not guaranteed"), status on_sale/sold_out, pageSize 120, price/brand/category/colour filters.
- Yahoo Auctions JP: direct HTML. Search URL `search/search?p=&b=1&n=100&s1=new&o1=d` confirmed by a public gist; closed search path is memory.
- Rakuma, 2nd Street, RagTag, Kindal, Treasure Factory: not researched beyond URL guesses (budget). Capture real search URLs in browser at integration.
- Shopify / BigCartel: direct JSON, from memory.
- eBay: optional, Browse API free (active only); sold needs restricted Marketplace Insights. Vestiaire, TheRealReal, Fashionphile: skip. 1stdibs: skip unless needed (asking only).

## Things that differ from a 2025 reader's assumptions
1. US de minimis is gone (suspended for all countries/modes since 2025-08-29; CBP rules 2026-06-24; postal informal entry process ~2026-07-24; statutory repeal 2027-07-01). Japan-origin goods: combined MFN + Section 301 capped at 12.5% since 2026-07-24 (IEEPA struck down Feb 2026; Section 122 10% ran Feb 24 - Jul 24). Third-party/law-firm sources; Federal Register pages not fetched.
2. Japan Post suspended US shipping Aug 2025; resumed (EMS/ePacket/sea) from ~2026-04-14 as prepaid DDP; >$100 needs a certified provider (reported Zonos). 1 kg proxy quote Sep 2026: ECMS $24.55, DHL $36.22.
3. Buyee fee is now 500 JPY per item (was 300) since 2026-04-01. ZenMarket Mercari 800 JPY (official post: Mercari Shops 500 to 800 on 2026-04-01). White Rabbit is now "Japan Rabbit", quote-based; the 9.9% seed figure is unverified.
4. ntfy.sh free quota is per-IP, 250 messages/day; shared egress IPs (Cloudflare Workers reported in ntfy issue #1963, likely GitHub runners too) can exhaust it. Prefer self-hosted ntfy or send from a stable IP.

## Free-tier limits (one line each)
- GitHub Actions: scheduled workflows in public repos auto-disable after 60 days without repo activity; shortest cron is 5 minutes and runs can be delayed tens of minutes (https://docs.github.com/en/actions/reference/usage-limits-billing-and-administration, community threads). Free minutes for public repos: not confirmed this session (believed unlimited on standard runners; verify).
- Turso Free: 100 DBs, 5 GB, 500M row reads/mo, 10M row writes/mo; databases are blocked when any metric is exceeded with overages off (aggregators: https://basekv.com/articles/turso-pricing-free-tier-limits-2026, https://freetiertracker.com/s/turso/). Inactivity archiving: no evidence found; verify on turso.tech/pricing.
- Cloudflare Workers Free: 100,000 requests/day (shared across account, resets 00:00 UTC), 10 ms CPU per request, error 1027 when over (official: https://github.com/cloudflare/cloudflare-docs/blob/production/src/content/docs/workers/platform/limits.mdx).
- Cloudflare Pages Free: 500 builds/month, 1 concurrent build, 20 min build timeout (official: https://developers.cloudflare.com/pages/platform/limits).
- Cloudflare Access / Zero Trust Free: 50 seats per a 2020 Cloudflare blog (https://blog.cloudflare.com/teams-plans); current figure not re-verified.
- Apify Free: $5 monthly credit, no card, renews monthly, blocked (no overage) when spent (https://scrapegraphai.com/blog/apify-pricing). At ~$2/1k results that is ~2,500 Mercari US results/month, so Apify only suits sold-comps and low-frequency pulls.
- ntfy.sh: 250 messages/day, 5 emails/day, 200 MB bandwidth/day, per-IP (https://docs.ntfy.sh/publish/, https://github.com/binwiederhier/ntfy/issues/1963).

## Price evidence
Found sold prices for only about 19 band rows (single observations, mostly undated Grailed sold listings surfaced by search). Basis counts: 17 sold, 2 asking (1stdibs Strip denim jacket; Sotheby's Rick Dunk estimate). All low confidence except the Hedi shearling coat (outlier, provenance) and the Raf Riot bomber (3 sales, med). Prices are thin because search snippets do not expose Grailed sold-filter results; the Orchestrator should seed bands from the Grailed sold index at runtime (that index is the real pricing backbone) and treat this file as a fallback.

### No price evidence (left out)
Dior Homme Luster/clawmark/19cm denim (generic), Hedi Dior leather jackets; SLP L01 (listing existed, price not shown), Black Knight varsity, Wyatt boots, D02 distressed denim, palm-patch denim; Celine Hedi leather/denim; Balmain Decarnin biker jeans and military jackets; Rick Owens early leathers, DRKSHDW; Undercover 85, Scab, Arts & Crafts, T; Number (N)ine skull cashmere, tribal camo, High Streets, AW09; Beauty:Beast; 20471120; ERD early; Raf AW02/AW03 and Peter Saville parka; Helmut Lang astro biker, bondage, painter denim; Margiela artisanal/GAT; Hysteric Glamour tees; vintage Chanel jewelry/belts/bags; remaining Chrome Hearts staples (hoodies, jewelry).

## Not done
Fee pages for FromJapan/Neokyo/Sendico; real search URLs for Rakuma/2nd Street/RagTag/Kindal/Trefac; Mercari US GraphQL operation hashes; Apify prices for JP actors; mercapi last release date.
