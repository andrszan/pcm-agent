const { chromium } = require(process.env.PLAYWRIGHT_CORE_PATH || 'playwright-core');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const [url, output, seedFile, overflowExpectation] = process.argv.slice(2);
const expectOverflow = overflowExpectation === 'overflow';
if (!url || !output) throw new Error('需要产品URL和专属截图目录');
fs.mkdirSync(output, { recursive: true });

(async () => {
  const browser = await chromium.launch({ channel: 'chrome', headless: true });
  const result = { checks: {}, errors: [] };
  try {
    const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    let seed;
    if (seedFile) {
      const storage = JSON.parse(fs.readFileSync(seedFile, 'utf8'));
      const entry = storage.origins.flatMap(origin => origin.localStorage).find(item => item.name === 'pcm-quality-ui-notes');
      seed = JSON.parse(entry.value);
      await context.addInitScript(notes => {
        if (localStorage.getItem('pcm-quality-ui-notes') === null) localStorage.setItem('pcm-quality-ui-notes', JSON.stringify(notes));
      }, seed);
    }
    const initialCount = seed ? seed.length : 4;
    const filteredCount = seed ? seed.filter(note => note.category === '交接').length : 2;
    const page = await context.newPage();
    page.on('pageerror', error => result.errors.push(error.message));
    page.on('console', message => { if (message.type() === 'error') result.errors.push(message.text()); });
    await page.goto(url);
    await page.getByRole('heading', { level: 1, name: '便签列表' }).waitFor();
    assert.equal(await page.locator('article').count(), initialCount);
    const savedBaseline = await page.evaluate(() => localStorage.getItem('pcm-quality-ui-notes'));
    result.initial = await page.locator('article').evaluateAll(items => items.map(item => ({
      title: item.querySelector('h2').textContent,
      body: item.querySelectorAll('p')[1].textContent,
      status: item.querySelector('.status').textContent,
    })));
    result.layout = await page.evaluate(() => ({
      cardHeight: document.querySelector('article').getBoundingClientRect().height,
      pageHeight: document.documentElement.scrollHeight,
      overflow: document.documentElement.scrollWidth > innerWidth,
    }));
    assert.equal(result.layout.overflow, expectOverflow);
    result.expectedOverflow = expectOverflow;
    await page.screenshot({ path: path.join(output, 'list-wide.png'), fullPage: true });
    await page.getByLabel('筛选分类').selectOption('交接');
    assert.equal(await page.locator('article').count(), filteredCount);
    await page.getByRole('link', { name: '确认周一交接时间', exact: true }).click();
    await page.getByRole('heading', { name: '确认周一交接时间', exact: true }).waitFor();
    await page.getByRole('link', { name: '返回便签', exact: true }).click();
    assert.equal(await page.getByLabel('筛选分类').inputValue(), '交接');
    assert.equal(await page.locator('article').count(), filteredCount);
    result.checks.filter_and_return = true;
    await page.getByRole('link', { name: '新建便签', exact: true }).click();
    await page.getByRole('heading', { name: '新建便签', exact: true }).waitFor();
    await page.getByLabel('标题', { exact: true }).fill('   ');
    await page.getByLabel('事项内容', { exact: true }).fill('不能保存空白标题');
    await page.getByRole('button', { name: '保存便签', exact: true }).click();
    await page.getByRole('alert').filter({ hasText: '请填写标题和事项内容' }).waitFor();
    assert.equal(await page.evaluate(() => localStorage.getItem('pcm-quality-ui-notes')), savedBaseline);
    result.checks.blank_rejected = true;
    await page.getByLabel('标题', { exact: true }).fill('Browser Probe 中文 ABC');
    await page.getByLabel('事项内容', { exact: true }).fill('确认结果并继续办理，不丢失原事项。');
    await page.getByRole('button', { name: '保存便签', exact: true }).click();
    await page.getByRole('heading', { name: 'Browser Probe 中文 ABC', exact: true }).waitFor();
    assert.match(await page.getByRole('status').innerText(), /便签已保存/);
    await page.getByRole('button', { name: '标记为已完成', exact: true }).click();
    await page.getByRole('button', { name: '恢复为待处理', exact: true }).waitFor();
    await page.reload();
    await page.getByRole('button', { name: '恢复为待处理', exact: true }).waitFor();
    const notes = await page.evaluate(() => JSON.parse(localStorage.getItem('pcm-quality-ui-notes')));
    assert.equal(notes.length, initialCount + 1);
    assert.equal(notes.at(-1).title, 'Browser Probe 中文 ABC');
    assert.equal(notes.at(-1).body, '确认结果并继续办理，不丢失原事项。');
    assert.equal(notes.at(-1).done, true);
    result.checks.create_complete_reload = true;
    await page.getByRole('button', { name: '恢复为待处理', exact: true }).click();
    await page.getByRole('button', { name: '标记为已完成', exact: true }).waitFor();
    result.checks.restore_pending = true;
    await page.getByRole('link', { name: '使用帮助', exact: true }).click();
    await page.getByRole('heading', { name: '使用帮助', exact: true }).waitFor();
    await page.screenshot({ path: path.join(output, 'help-wide.png'), fullPage: true });
    await page.getByRole('link', { name: '返回便签', exact: true }).click();
    await page.getByRole('heading', { name: '便签列表', exact: true }).waitFor();
    await page.setViewportSize({ width: 400, height: 800 });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), expectOverflow);
    assert.equal(await page.locator('header').count(), 1);
    await page.screenshot({ path: path.join(output, 'list-narrow-viewport.png') });
    await page.locator('article').last().scrollIntoViewIfNeeded();
    await page.screenshot({ path: path.join(output, 'list-narrow-bottom.png') });
    result.checks.narrow_layout = !expectOverflow;
    assert.deepEqual(result.errors, []);
    result.status = expectOverflow ? 'expected_defect_observed' : 'passed';
  } catch (error) {
    result.status = 'failed';
    result.failure = { name: error.name, message: error.message };
    process.exitCode = 1;
  } finally {
    await browser.close();
    result.ownBrowserClosed = true;
    fs.writeFileSync(path.join(output, 'verification.json'), JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result));
  }
})();
