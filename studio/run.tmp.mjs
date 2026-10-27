import { chromium } from "@playwright/test";
const [out, path, ...clicks] = process.argv.slice(2);
const browser = await chromium.launch({ channel: "msedge" });
const page = await (await browser.newContext({ viewport: { width: 1440, height: Number(process.env.H ?? 900) }, colorScheme: "dark" })).newPage();
const errors = []; page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
await page.goto("http://127.0.0.1:5180" + path);
await page.waitForLoadState("networkidle"); await page.waitForTimeout(600);
for (const c of clicks) { await page.locator(c).first().click(); await page.waitForTimeout(500); }
await page.screenshot({ path: out, fullPage: true });
console.log("console errors:", errors.slice(0, 4));
await browser.close();
