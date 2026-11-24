# R2 taxonomy notes (2026-11-24)

## Method and limits
- 25 web searches used. All WebFetch calls failed (hosts such as grailed.com, trussarchive.com, wikipedia.org did not resolve in this session), so every fact comes from search snippets or background knowledge. Anything not seen in a snippet is `confidence: low` + `verify: true`.
- Not consulted: r/QualityReps, Reddit, Vogue Runway pages. Fake red flags are written from general knowledge and a few authentication guides, for risk scoring only.
- Files: `data/taxonomy/{brands,eras,seasons,archetypes,exemplars,blocklist,aliases_ja}.yaml`. Brand id `"20471120"` must stay quoted (bare YAML parses it as an integer). `years: [x, null]` means ongoing. Extra optional keys I added: `dispute`, `match: word` (blocklist), `ja_verification`.

## Seed corrections (TASTE_PROFILE)
1. Dior Homme "Luster": a Wikipedia-derived table gives AW03 (Berlin electro, "Change Yourself" by Bosco), while Grailed sellers title Luster waxed/clawmark denim "AW05". Stored as `dior_homme__aw03` with a `dispute` note; `luster` is also an alias of aw05. A runway source is needed to settle it.
2. Dior Homme "Strip" = SS04 confirmed. Other Wikipedia-derived names: AW01 Solitaire, AW04 "Victim of the Crime" (unofficial), SS06 "The World Was a Mess, But His Hair Was Perfect", AW06 "These Grey Days" (unofficial), SS07 "We Look Good Together". First Dior men's denim = spring 2003.
3. Number (N)ine "Give Peace a Chance" is AW04, not SS04 (Truss Archive). "The High Streets" AW05, "Noir" AW06-07, "My Own Private Portland" F/W08 are confirmed. "A Closed Feeling" and Hypebeast's "Last Songs" are both filed as Fall 2009; treated as aliases. "Touch Me I'm Sick" is SS03 vs AW03 in sources (stored as AW03, disputed). SS08 "Birds" added.
4. Rick Owens: "Gethsemane" = Men's AW21 and "Strobe" = FW22, both RECENT, not old Rick. "Dust" is a colour (warm grey), not a collection. "Moog" could not be found anywhere and is not stored as a season. Verified old-Rick fixed points: FW08 "Stag" (FIT), SS16 "Cyclops", DRKSHDW FW09 exists.
5. Balmain AW10 "Coin" bikers: nothing found. Fall 2010 is verified as the menswear debut with biker jeans, and "coin" is not used as a name.
6. Undercover: SS03 "Scab" and SS06 "T" confirmed; AW04 "But Beautiful" added. FW05 "Arts & Crafts" is unconfirmed (kept, low). "Last Scream of Zamiang" could not be tied to SS06 or any season and is not stored as a season.
7. Beauty:Beast: AW1998 collab was with COSPA, not Undercover or 20471120. Founding year 1990 or 1991 depending on source.
8. Raf Simons AW01/SS02/AW02/SS03/AW03 verified. "Radioactivity" and "Black Palms" not found.
9. Number (N)ine eras: Miyashita 1997-2009; he relaunched "Number (N)ine by Takahiro Miyashita" in 2025, and the original name was run by a parent company in between. This is a third era (`number_nine__relaunch`) the engine must not confuse with archive.

## Documented cues the engine can use
- Dior Homme apparel tags: reference code leads with ONE year digit (example `5EH1015678 E47 B6A8` = SS05). The digit repeats every decade, so it is only a consistency check against a stated season. No regex written.
- Made in Italy and Japan are both legitimate for Hedi denim (museum record plus Heddels MIJ 21cm). "19cm" and "21cm" are leg-opening cuts attributed to Hedi.
- Saint Laurent: "Yves" dropped June 2012; SS15 men's jacket carries woven satin "SAINT LAURENT / PARIS". Hedi's final collection AW16; Vaccarello from 2016.
- Celine: Hedi joined Jan 2018, exit announced 2 Oct 2024, Michael Rider effective early 2025. The accent-drop date is unverified.
- Balmain: Decarnin out April 2011 (Rousteing named then); Rousteing stepped down Nov 2025 (fashionsnap headline, verify).
- Helmut Lang: Prada 51% 1999, full 2004, Lang left Jan 2005, Link Theory 2006, Fast Retailing 2009; MAK archive covers 1986-2005.
- Margiela: Martin left 2009, Galliano 2014; four white stitches are factory-original. Date of "Martin" disappearing from labels is unverified.

## Remaining UNKNOWN / low confidence (all `season_code_regex` are UNKNOWN)
- Tag/season code regexes: Dior Homme (one example only), Saint Laurent, Rick Owens (the brief's "RU/RP + season + year" was NOT verified), Undercover, Number (N)ine, Chanel (96A/95P style is seller vocabulary, not source-verified).
- Which KVA seasons are "respected": not verifiable; only SS08 and AW09 are stored, low weight, as placeholders.
- Season names for Saint Laurent (all UNKNOWN), Celine standout seasons (only SS19), Helmut Lang, Margiela, Chanel, ERD: no season entries beyond those listed. Season count is 47, short of the 60-100 target, because fetches failed and I would not invent names.
- Piece-to-season mappings in exemplars for SLP (L01 first version, Black Knight, palm-patch) come from the seed, not from a source.
- Gucci/Versace/D&G/Cavalli/Givenchy/Balenciaga/Mugler/Supreme/Off-White/BAPE/Yeezy eras: designer tenure dates are basic knowledge without a URL seen.
- Japanese spellings for most brands are from memory; `ja_verification` in aliases_ja.yaml lists what was and wasn't seen.
- Brand `price_floor_usd` values are conservative tripwires, not market prices; 26 lighter-depth brands have no era entries.

## Design decisions for the rules engine
- Short/collision forms are `ambiguous_aliases` (dh, uc, ro, rick, celine, raf, ccp, lgb, goa, bb, ch, sup). Require brand-context words or a second brand cue.
- `negative_context` in brands.yaml is the first line of defence (perfume, jersey, Disney, first names). `blocklist.yaml` holds cross-brand rules. The bare word "style" is NOT blocked; only "-style", "style of", "in the style of", "inspired", "vibes", "similar to". `rep`, `ua`, `copy`, `fake`, `replica` are whole-word and have allow-lists (Margiela Replica, fake fur, copy of receipt).
- Era resolution order suggested: explicit era alias or JP era term, then label/model cues, then season code in listing text, then year in title; anti_cues demote.
- `exemplars.yaml` texts are synthetic and some short groups end with templated filler lines.
