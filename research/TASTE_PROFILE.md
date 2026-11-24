# Taste profile (Part 1 of the master prompt — the shared input for every research agent)

The user lives in the archive / "ballhog" / Japanese-archive / Hedi corner of fashion and makes
archive-fashion content. The system must tell a Hedi-era Dior Homme piece from a 2019 Dior Men
piece, and a real Number (N)ine piece from a "grunge archive style" listing.

## 1A. Core brands and eras (highest base weight)
Era resolution matters as much as the brand. Research must confirm and extend every row.

| Brand | Era that matters | Seed seasons / pieces to verify and expand |
|---|---|---|
| Dior Homme, Hedi Slimane | 2000–2007 (first collection 2001) | SS04 "Strip", "Luster"/clawmark Luster denim, 19cm/coated/waxed jeans, leather jackets, Strip sneakers. Japan-made Hedi denim is legitimate |
| Dior Homme, Kris Van Assche ("good KVA") | 2007–2018 | Which KVA seasons and pieces are respected now. Don't weight it all equally |
| Saint Laurent, Hedi | 2012–2016 | L01 biker (first-version 2012), Teddy/varsity, "Black Knight" leather-paneled varsity, 2015 palm-patch denim, distressed denim, Wyatt/Jodhpur boots, AW16 velvet/rhinestone |
| Celine, Hedi | 2018–2024 | Leather jackets, slim denim, rock-tour tailoring. Standout seasons |
| Balmain, Christophe Decarnin | ~2005–2011 | Biker jeans (incl. AW10 "Coin" bikers), SS09 washed skinnies, embellished military jackets, shoulder-pad blazers, destroyed tees |
| Rick Owens, old collections | Mainly pre-~2012 mainline + early DRKSHDW | "Dust"/"Gethsemane", "Strobe" era, Moog-era knits, early leathers, Dark Shadow line (~2006–2010). Exact grail seasons |
| Undercover, old Jun Takahashi | 1990s–~2010 | FW05 "Arts & Crafts", SS06 "T" (Cosmos bear), SS06 "Last Scream of Zamiang", "85" pieces, "We Make Noise Not Clothes" tees, SS03 "Scab" (verify) |
| Beauty:Beast, Takao Yamashita | 1991–2000s | AW98-99 giant safety-pin pieces, "Dark Knight", rabbit backpack, Undercover & 20471120 collabs |
| 20471120 | 1990s–early 2000s | Signature pieces, graphics and collabs |
| Chanel, vintage | Mainly 1990s–2000s | In the style of @glam_archive: logo jewelry, belts, bags, tweed, CC graphics. Fakes are rampant, apply the risk penalty hard |
| Enfants Riches Déprimés (ERD), "good old ERD" | ~2012–2018 early output | Which early pieces and graphics carry value |

## 1B. Adjacent brands the same buyers chase (seeds; research verifies and weights)
- Japanese archive / ballhog / onii-kei:
  - Number (N)ine: AW05 "The High Streets", AW06 "Noir", AW08 "My Own Private Portland",
    AW09 "A Closed Feeling", SS04 "Give Peace a Chance", tribal camo, skull cashmere.
  - Takahiro Miyashita The Soloist, Hysteric Glamour, 14th Addiction, L.G.B. (Le Grand Bleu),
    Ifsixwasnine, Kmrii, Tornado Mart, Goa, Share Spirit, Semantic Design, Buffalo Bobs,
    Civarize, Roen.
  - Yohji Yamamoto, Comme des Garçons / CDG Homme Plus, Junya Watanabe, Issey Miyake.
  - Kapital, only if research shows overlap.
- European archive:
  - Raf Simons (AW01 "Riot Riot Riot", AW02 "Virginia Creeper", AW03 "Closer", verify others).
  - Helmut Lang (Helmut era), Maison Martin Margiela (Martin era), Ann Demeulemeester,
    Carol Christian Poell, Julius, Boris Bidjan Saberi.
  - Jean Paul Gaultier, Vivienne Westwood, Alexander McQueen (Lee era), Gucci (Tom Ford era),
    Versace (Gianni era), early-2000s Dolce & Gabbana, Roberto Cavalli y2k, Givenchy (Tisci era),
    Balenciaga (Ghesquière and early Demna), Vetements (Demna era), Thierry Mugler.
- Rapper-uniform staples (lower base weight, high trend sensitivity): Chrome Hearts,
  True Religion, Supreme (incl. Shibuya box logo), early Off-White (Virgil), BAPE,
  Jeremy Scott/Moschino, Yeezy.

## 1C. Taste influencers and signal sources
- Underground rappers the user follows: fakemink, bleood, protect, bradygoo, osamason, 1oneam,
  maxon, pz. Adjacent scene: Nettspend, EsDeekid, Playboi Carti and the Opium orbit, newer names.
- Known datapoints: fakemink seen in 2016-era Saint Laurent, Number (N)ine, Ann Demeulemeester,
  Raf Simons, Margiela, McQueen, Balmain and Shibuya box logo tees. The ballhog scene leans on
  Number (N)ine hoodies, Undercover 85, Hysteric Glamour tees and Jeremy Scott. Grailed has an
  "osamason" tag page.
- Influencer / stylist: Junki Ichikawa (@junki_ichikawa, confirmed by the user).
- Archive Instagram pages (user-provided): @boringblind, @crybynoonarchive, @archivethreads,
  @youthwastedpoorly, @nevernined, @myprettiarchive, @glam_archive (Bangkok, 1995–2015 designer
  archive dealer: Chanel, Gucci, Margiela, Celine, Balmain, Chrome Hearts, Rick, SLP; the key
  reference for the Chanel/glam side). Seeds with evidence: @realabayan / @alabayan
  (Number (N)ine collector, RE:AL store).

## 1D. Sources (NO Depop, NO Vinted — never add them, even as optional)
| Source | Priority | Notes |
|---|---|---|
| Grailed | Core, every ~10 min | Live listings plus sold comps (the pricing backbone) |
| Mercari US | Core, every ~15–20 min | Hardest to scrape |
| Mercari Japan (buy via Buyee/ZenMarket) | High, hourly | Often the cheapest grails. Japanese keyword aliases |
| Yahoo! Auctions Japan (via proxy) | High, hourly | Strong for Raf, Dior Homme, Japanese labels. Track auction end times |
| Rakuma, 2nd Street, RagTag, Kindal, Treasure Factory | Medium, every 2–6 h | Verify which are scrapeable and carry the right brands |
| Independent archive stores (Shopify/BigCartel webshops of IG archive sellers) | Medium, hourly | Many Shopify stores expose public `/products.json` |
| eBay, Vestiaire Collective, The RealReal, 1stdibs, Farfetch pre-owned, Fashionphile (Chanel) | Low/optional, every 6–12 h | Comps and occasional finds, only if cheap and stable |

Proxy cost model for Japan (re-verify current fees): Buyee ~$2 + 5% on win; ZenMarket ~$3 per
item; White Rabbit Express ~$4 + 9.9%. Add international shipping by category weight, and
duties. Real landed costs often run 20–40% over sticker, so always compare landed cost.
