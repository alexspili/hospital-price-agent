// Re-record docs/demo.gif against the live site. Needs Google Chrome, ffmpeg and node;
// Playwright drives the browser and records a video, ffmpeg turns it into the GIF.
//
//   mkdir -p /tmp/hpa-gif && cd /tmp/hpa-gif && npm init -y && npm i playwright
//   HPA_PASSWORD=... node /path/to/scripts/record_demo.mjs
//   V=$(ls video/*.webm)
//   ffmpeg -y -i "$V" -vf "fps=10,scale=1000:-1:flags=lanczos,palettegen=max_colors=128:stats_mode=diff" palette.png
//   ffmpeg -y -i "$V" -i palette.png -lavfi "fps=10,scale=1000:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle" demo.gif
//   cp demo.gif /path/to/docs/demo.gif
//
// What it shows: the recorded run on arrival, then a live scan for a head CT (every file
// is already cached, so it finishes in a second), then the side-by-side verdicts. One
// live run counts against the hourly limit.
import { chromium } from 'playwright'
import { rmSync, mkdirSync } from 'node:fs'

const SITE = process.env.HPA_SITE ?? 'https://prices.alexspi.com/'
const PASSWORD = process.env.HPA_PASSWORD
if (!PASSWORD) throw new Error('set HPA_PASSWORD to the live-scan password')
const W = 1000, H = 620
rmSync('video', { recursive: true, force: true }); mkdirSync('video')
const browser = await chromium.launch({ channel: 'chrome', headless: true })
const ctx = await browser.newContext({ viewport: { width: W, height: H }, recordVideo: { dir: 'video', size: { width: W, height: H } } })
const page = await ctx.newPage()
const t0 = Date.now(); const mark = (s) => console.log(`${((Date.now() - t0) / 1000).toFixed(1)}s ${s}`)

await page.goto(SITE, { waitUntil: 'networkidle' })
await page.waitForSelector('.hospital'); mark('recorded run on screen')
await page.waitForTimeout(2500)

const service = page.locator('input[list="recorded-services"]')
await service.click({ clickCount: 3 })
await service.pressSequentially('head ct', { delay: 70 })
await page.getByLabel('run live').check(); mark('run live ticked')
await page.waitForTimeout(400)
await page.locator('input[type="password"]').pressSequentially(PASSWORD, { delay: 60 })
await page.waitForTimeout(400)
await page.getByRole('button', { name: 'Scan live' }).click(); mark('submitted')
await page.getByText('Scanning live', { exact: false }).waitFor({ timeout: 30000 }); mark('scanning')
await page.getByText('Scanned live from each hospital', { exact: false }).waitFor({ timeout: 240000 }); mark('result arrived')
await page.waitForTimeout(800)
await page.locator('.comparisons summary').click(); mark('side by side opened')
await page.locator('.comparisons').scrollIntoViewIfNeeded()
await page.waitForTimeout(3500)
await ctx.close(); await browser.close(); mark('done')
