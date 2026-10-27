// usage: node el.mjs <out> <path> <selector> [clicks...]
import { chromium } from "@playwright/test";
const [out, path, sel, ...clicks] = process.argv.slice(2);
const browser = await chromium.launch({ channel: "msedge" });
const page = await (await browser.newContext({ viewport: { width: 1440, height: Number(process.env.H ?? 900) }, colorScheme: "dark", deviceScaleFactor: 1 })).newPage();
const errors = []; page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
await page.goto("http://127.0.0.1:5180" + path); await page.waitForLoadState("networkidle"); await page.waitForTimeout(700);
for (const c of clicks) { await page.locator(c).first().click(); await page.waitForTimeout(600); }
await page.locator(sel).first().screenshot({ path: out });
console.log("console errors:", errors.slice(0, 4));
await browser.close();
