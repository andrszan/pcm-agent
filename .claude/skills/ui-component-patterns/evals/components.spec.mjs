import assert from "node:assert/strict"
import { createRequire } from "node:module"
import { mkdir } from "node:fs/promises"
import { resolve } from "node:path"

const [runtime, url = "http://127.0.0.1:41739", output = ".test-screenshots/ui-patterns/results"] = process.argv.slice(2)
assert(runtime, "请传入已有依赖与 fixture 的隔离宿主目录")
const require = createRequire(resolve(runtime, "package.json"))
const { chromium } = require("playwright")
const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ permissions: ["clipboard-read", "clipboard-write"], viewport: { width: 1280, height: 900 } })
const page = await context.newPage()
const errors = []
page.on("pageerror", error => errors.push(error.message))
page.on("console", message => { if (message.type() === "error") errors.push(message.text()) })
await mkdir(output, { recursive: true })
try {
  await page.goto(url)
  const reader = page.getByRole("region", { name: "Markdown 阅读", exact: true })
  await reader.getByRole("heading", { name: "阅读验证", exact: true }).waitFor()
  assert.equal(await reader.locator("table").count(), 1)
  assert.equal(await reader.locator('input[type="checkbox"]:checked').count(), 1)
  assert.equal(await reader.locator("pre").count(), 4)
  assert.equal(await reader.locator("[node]").count(), 0)
  assert.equal(await reader.locator('a[href^="javascript:"]').count(), 0)
  assert.equal(await page.evaluate(() => window.__markdownInjected), undefined)
  assert.equal(await reader.getByText("objective-c", { exact: true }).count(), 1)

  const wrap = reader.getByRole("button", { name: "自动换行", exact: true }).first()
  await wrap.focus()
  await page.keyboard.press("Enter")
  assert.equal(await reader.getByRole("button", { name: "取消自动换行", exact: true }).count(), 1)
  assert.equal(await reader.getByRole("button", { name: "自动换行", exact: true }).count(), 3)
  assert.equal(await page.evaluate(() => document.activeElement?.textContent), "取消自动换行")
  assert.equal(await reader.locator("pre").nth(0).evaluate(el => getComputedStyle(el).whiteSpace), "pre-wrap")
  assert.equal(await reader.locator("pre").nth(1).evaluate(el => getComputedStyle(el).whiteSpace), "pre")
  await page.getByRole("button", { name: "追加内容", exact: true }).click()
  assert.equal(await reader.getByRole("button", { name: "取消自动换行", exact: true }).count(), 1)

  await reader.getByRole("button", { name: "复制", exact: true }).first().click()
  await reader.getByRole("button", { name: "已复制", exact: true }).waitFor()
  const clipboard = await page.evaluate(() => navigator.clipboard.readText())
  assert.equal(clipboard, `${await reader.locator("pre code").first().textContent()}\n`)
  assert.equal(await reader.getByRole("button", { name: "已复制", exact: true }).count(), 1)

  // 仅注入权限失败分支；成功路径以上使用真实 Clipboard API。
  await page.evaluate(() => Object.defineProperty(navigator.clipboard, "writeText", { configurable: true, value: async () => { throw new DOMException("denied", "NotAllowedError") } }))
  await reader.getByRole("button", { name: "复制", exact: true }).first().click()
  await reader.getByRole("button", { name: "复制失败", exact: true }).waitFor()

  await page.evaluate(() => {
    window.__copyRequests = []
    Object.defineProperty(navigator.clipboard, "writeText", { configurable: true, value: () => new Promise((resolve, reject) => window.__copyRequests.push({ resolve, reject })) })
  })
  const racingBlock = reader.locator("pre").nth(2).locator("..")
  await racingBlock.getByRole("button", { name: "复制", exact: true }).click()
  await racingBlock.getByRole("button", { name: "复制", exact: true }).click()
  await page.evaluate(() => window.__copyRequests[1].reject(new Error("拒绝第二次复制")))
  await racingBlock.getByRole("button", { name: "复制失败", exact: true }).waitFor()
  await page.evaluate(() => window.__copyRequests[0].resolve())
  assert.equal(await racingBlock.getByRole("button", { name: "复制失败", exact: true }).count(), 1)

  await page.getByRole("button", { name: "底层操作 0", exact: true }).click()
  await page.getByRole("button", { name: "底层操作 1", exact: true }).waitFor()
  assert.equal(await page.getByRole("region", { name: "覆盖加载", exact: true }).getByRole("status").evaluate(el => getComputedStyle(el).position), "absolute")
  assert.equal(await page.getByRole("region", { name: "父容器加载", exact: true }).getByRole("status").evaluate(el => getComputedStyle(el).minHeight), "0px")

  await page.emulateMedia({ reducedMotion: "reduce" })
  assert(await page.locator(".loading-page-ring, .loading-page-orb, .loading-page-shimmer").evaluateAll(els => els.every(el => getComputedStyle(el).animationName === "none")))
  await page.emulateMedia({ reducedMotion: "no-preference" })
  assert.equal(await page.locator(".loading-page-ring").first().evaluate(el => getComputedStyle(el).animationName), "loading-page-ring-spin")

  await page.screenshot({ path: resolve(output, "desktop-light.png"), fullPage: true })
  const light = await reader.locator("pre").first().evaluate(el => getComputedStyle(el).color)
  await page.getByRole("button", { name: "切换主题", exact: true }).click()
  const dark = await reader.locator("pre").first().evaluate(el => getComputedStyle(el).color)
  assert.notEqual(light, dark)
  await page.screenshot({ path: resolve(output, "desktop-dark.png"), fullPage: true })
  await page.setViewportSize({ width: 375, height: 812 })
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), "移动端页面不得横向溢出")
  await page.screenshot({ path: resolve(output, "mobile-dark.png"), fullPage: true })
  assert.deepEqual(errors, [], "浏览器不得出现运行错误")
  console.log("PASS: Markdown/GFM、安全边界、代码块状态隔离、键盘焦点、内容追加、真实复制、复制失败、加载区域、reduced motion、明暗主题、375px响应式")
} finally {
  await browser.close()
}
