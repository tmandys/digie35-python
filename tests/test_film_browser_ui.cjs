// Run with Node and Playwright available on NODE_PATH.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const assert = require('node:assert/strict');
(async () => {
    const browser = await chromium.launch({headless: true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel: process.env.PLAYWRIGHT_CHANNEL} : {})});
    try {
        const page = await browser.newPage({viewport: {width: 1000, height: 800}});
        const root = path.resolve(__dirname, '../digie35/html');
        const html = fs.readFileSync(path.join(root, 'digie35.html'), 'utf8');
        const start = html.indexOf('<div id="capture-info-modal"');
        const end = html.indexOf('<div id="capture-warning-modal"', start);
        await page.setContent(`<style>${html.match(/<style>([\s\S]*?)<\/style>/)[1]}${fs.readFileSync(path.join(root, 'film_browser.css'), 'utf8')}</style><input id="project_id" value="p"><input id="film_id" value="f"><select id="film-list"><option>none</option><option selected>f</option></select>${html.slice(start, end)}`);
        await page.evaluate(() => {
            window.current_volume = true; window.control_socket = {readyState: 1};
            window.modal_stack = [];
            window.get_modal = () => document.querySelector('.modal-active');
            window.show_modal = id => { get_modal()?.classList.remove('modal-active'); document.getElementById(id).classList.add('modal-active'); };
            window.close_modal = () => show_modal('capture-info-modal');
            window.get_stream_url = () => 'data:image/png;base64,invalid';
            window.show_lightbox = name => window.openedImage = name;
            window.sendCommand = (...args) => window.lastCommand = args;
        });
        await page.addScriptTag({path: path.join(root, 'film_browser.js')});
        await page.evaluate(() => {
            const projects = document.createElement('select'); projects.id = 'project-list'; document.body.append(projects);
            for (const [id, films] of [['p', ['f', 'other']], ['q', ['destination']]]) {
                const option = new Option(id, id); option._custom_data = {id, film_list: films.map(id => ({id}))}; projects.add(option);
            }
            const files = [{name: 'one.nef', size: 20000000, modified: 100, preview: true, xmp: true, preview_json: true}, {name: 'two.nef', modified: 200, camera_only: true}];
            document.getElementById('film-list').selectedOptions[0]._custom_data = {captured: files};
            window.adjust = () => filmBrowser.update(document.getElementById('film-list').selectedOptions[0]._custom_data.captured);
            adjust(); show_modal('capture-info-modal');
        });
        assert.equal(await page.locator('.film-item').count(), 2);
        assert.equal(await page.locator('.film-item').last().locator('button.film-open').count(), 0);
        await page.waitForFunction(() => !document.querySelector('.film-item img'));
        const heights = await page.locator('.film-open').evaluateAll(nodes => nodes.map(n => n.getBoundingClientRect().height));
        assert.equal(heights[0], heights[1]);
        await page.locator('.film-item input').first().check();
        await page.locator('#film-view').selectOption('details');
        assert.equal(await page.locator('.film-item').last().locator('span.film-open').textContent(), 'two.nef');
        assert.equal(await page.locator('.film-item input').first().isChecked(), true);
        await page.locator('[data-sort="modified"]').click();
        assert.equal(await page.locator('.film-item .film-open').first().textContent(), 'two.nef');
        assert.equal(await page.locator('th[aria-sort="descending"]').count(), 1);
        assert.equal(await page.locator('.film-item input').last().isChecked(), true);
        await page.locator('[data-sort="modified"]').click();
        assert.equal(await page.locator('.film-item .film-open').first().textContent(), 'one.nef');
        assert.equal(await page.locator('th[aria-sort="ascending"]').count(), 1);
        await page.locator('[data-sort="name"]').click();
        await page.locator('#film-view').selectOption('list');
        assert.equal(await page.locator('.film-item').last().locator('button.film-open').count(), 0);
        await page.locator('.film-open').first().click();
        assert.equal(await page.evaluate(() => window.openedImage), 'p/f/one.nef');
        await page.locator('#film-delete').click();
        assert.equal(await page.locator('#film-delete-modal').evaluate(n => n.classList.contains('modal-active')), true);
        await page.locator('#film-delete-confirm').click();
        assert.deepEqual(await page.evaluate(() => window.lastCommand[2].names), ['one.nef']);
        await page.evaluate(() => filmBrowser.receive({cmd: 'DELETE_CAPTURES', payload: {request_id: filmBrowser.pending.request_id, deleted: [], errors: {'one.nef': 'Permission denied'}}}));
        assert.match(await page.locator('#film-delete-status').textContent(), /Permission denied/);
        await page.evaluate(() => close_modal());
        assert.equal(await page.locator('.film-item input').first().isChecked(), true);
        await page.locator('#film-view').selectOption('thumbnails');
        await page.locator('.film-info').last().click();
        assert.match(await page.locator('#film-file-info').textContent(), /two.nef/);
        await page.evaluate(() => close_modal());
        await page.locator('#film-move').click();
        assert.equal(await page.locator('#film-move-film option[value="f"]').count(), 0);
        assert.equal(await page.locator('#film-move-confirm').isDisabled(), true);
        await page.locator('#film-move-project').selectOption('q');
        await page.locator('#film-move-film').selectOption('destination');
        await page.locator('#film-move-confirm').click();
        assert.deepEqual(await page.evaluate(() => [window.lastCommand[0], window.lastCommand[2].target_project, window.lastCommand[2].target_film]), ['MOVE_CAPTURES', 'q', 'destination']);
        await page.evaluate(() => filmBrowser.receive({cmd: 'MOVE_CAPTURES', payload: {request_id: filmBrowser.pending.request_id, moved: [], error: 'Destination already contains one.nef'}}));
        assert.match(await page.locator('#film-move-status').textContent(), /already contains/);
        assert.equal(await page.locator('#film-move-confirm').isDisabled(), false);
        await page.locator('#film-move-confirm').click();
        await page.evaluate(() => filmBrowser.receive({cmd: 'MOVE_CAPTURES', payload: {request_id: filmBrowser.pending.request_id, moved: ['one.nef']}}));
        assert.equal(await page.locator('.film-item').count(), 1);
        assert.equal(await page.locator('.film-item input').isChecked(), false);
        console.log('Film browser UI: views, selection, delete confirmation, move destinations, collision error, successful move and touch details passed.');
    } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
