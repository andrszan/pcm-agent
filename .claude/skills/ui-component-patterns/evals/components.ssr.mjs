import assert from 'node:assert/strict'
import { createRequire } from 'node:module'
import { readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { pathToFileURL } from 'node:url'

const runtime = resolve(process.argv[2])
const require = createRequire(resolve(runtime, 'package.json'))
const { createElement } = require('react')
const { renderToString } = require('react-dom/server')
const { TestApp } = await import(pathToFileURL(resolve(runtime, 'dist-ssr/main.js')).href)
const html = renderToString(createElement(TestApp))
assert(html.includes('<pre'), 'SSR需输出可读代码块')
assert(!html.includes('react-syntax-highlighter-line-number'), '首次渲染保持稳定，挂载后启用高亮')
const index = readFileSync(resolve(runtime, 'dist/index.html'), 'utf8')
assert(index.includes('<div id="root"></div>'))
writeFileSync(resolve(runtime, 'dist/ssr.html'), index.replace('<div id="root"></div>', `<div id="root">${html}</div>`))
console.log('PASS: Node SSR已生成，使用components.spec.mjs对/ssr.html验证hydration')
