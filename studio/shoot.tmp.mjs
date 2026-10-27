// usage: node shoot.mjs <outdir> [pages...]  (run from studio/ so @playwright/test resolves)
import { chromium } from "@playwright/test";
const out = process.argv[2];
const base = "http://127.0.0.1:5180";
const all = { overview: "/", runs: "/runs", memory: "/memory", control: "/control", orchestration: "/orchestration", replay: "/replay", experiment: "/experiment" };
const pick = process.argv.slice(3);
const pages = pick.length ? Object.fromEntries(pick.map((p) => [p.split("=")[0], all[p] ?? p.split("=")[1]])) : all;
const browser = await chromium.launch({ channel: "msedge" });
const errors = [];
for (const [w, h, tag] of [[1440, 900, ""], ...(process.env.MOBILE ? [[390, 844, "-m"]] : [])]) {
  const page = await (await browser.newContext({ viewport: { width: w, height: h }, colorScheme: "dark" })).newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  for (const [name, path] of Object.entries(pages)) {
    await page.goto(base + path);
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(700);
    await page.screenshot({ path: `${out}/${name}${tag}.png`, fullPage: !!process.env.FULL });
  }
}
console.log("console errors:", errors.slice(0, 5));
await browser.close();
