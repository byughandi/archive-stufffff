# Grail Radar, site

SvelteKit (Svelte 5), static SPA build, plain CSS from `src/styles/tokens.css`. The Cloudflare Worker in `../worker` serves the build and the `/api` routes from one origin.

## Develop
```sh
npm install
npm run dev          # http://127.0.0.1:5173, /api is proxied to http://127.0.0.1:8787
npm run check        # svelte-check
```
You need the API running on :8787 (`cd ../worker && npx wrangler dev --port 8787`). With a dev database, fill it with fake scores first: `python ../scripts/dev_fake_feed.py data/dev/web.db` (see its docstring).

## Build
```sh
npm run build        # writes the site to ../worker/public (not committed; .gitkeep is kept)
```
Then the Worker serves everything: `cd ../worker && npx wrangler dev --port 8787` and open http://127.0.0.1:8787/.

## Notes
- SvelteKit 3: configuration lives in `vite.config.ts` (there is no `svelte.config.js`).
- Art: edit `public/art/*.svg` (via `design/build_art.py`), then `npm run art` to regenerate `src/lib/art.generated.ts`.
- Icons: `NODE_PATH=$(npm root -g) node scripts/build-icons.mjs` rasterises `public/art/favicon.svg` into `public/icons/` (needs Playwright).
- Everything is client-rendered. A 401 or 503 from `/api` shows the signed-out screen.
