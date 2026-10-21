const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../digie35/html/digie35.html'), 'utf8');

function setup(curve) {
    const context = {
        window: {snapshot_frame: {sequence: 1}},
        document: {getElementById: () => ({})},
        clear_focus_score() {}, redraw_snapshot_marker() {}, update_status_info() {},
        preview_settings: () => ({wb_delay: 100, timeout: 1000}),
    };
    vm.createContext(context);
    const start = html.indexOf('    window.autoFocus = {');
    vm.runInContext(html.slice(start, html.indexOf('    const SNAPSHOT_FOCUS_SIZE', start)), context);
    const af = context.window.autoFocus;
    let position = 0;
    const moves = [];
    af.pair = () => ({near: 'near', far: 'far'});
    af.score = async () => curve(position);
    af.move = async direction => {
        moves.push(direction);
        position += direction === 'far' ? 1 : -1;
        return curve(position);
    };
    return {af, context, moves, position: () => position};
}

test('AF continues through improving scores and returns from 90 to the 110 peak', async () => {
    const s = setup(position => [50, 60, 90, 110, 90][position] ?? 10);
    const result = await s.af.run();
    assert.equal(s.position(), 3);
    assert.equal(result.score, 110);
    assert.deepEqual(s.moves, ['far', 'far', 'far', 'far', 'near']);
});

test('AF searches the opposite direction and restores its maximum', async () => {
    const s = setup(position => 250 - Math.abs(position + 4) * 20);
    const result = await s.af.run();
    assert.equal(s.position(), -4);
    assert.equal(result.score, 250);
});

test('AF returns to the start when both probes are worse', async () => {
    const s = setup(position => 250 - Math.abs(position) * 20);
    const result = await s.af.run();
    assert.equal(s.position(), 0);
    assert.equal(result.score, 250);
});

test('AF reports measured return score instead of claiming the historical maximum', async () => {
    const s = setup(position => [50, 60, 90, 110, 90][position] ?? 10);
    const move = s.af.move;
    s.af.move = async direction => {
        const score = await move(direction);
        return direction === 'near' ? score - 15 : score;
    };
    const result = await s.af.run();
    assert.equal(result.score, 95);
    assert.equal(result.bestScore, 110);
});

test('monotonic improvement stops at a bounded search limit and reports it', async () => {
    const s = setup(position => 50 + position * 10);
    const result = await s.af.run();
    assert.equal(s.moves.length, 33);
    assert.equal(result.limited, true);
});

test('frame received during settling is not accepted as fresh', async () => {
    const s = setup(() => 0);
    s.af.sleep = async () => { s.context.window.snapshot_frame.sequence = 2; };
    s.af.waitFor = async predicate => {
        assert.equal(predicate(), false);
        s.context.window.snapshot_frame.sequence = 3;
        assert.equal(predicate(), true);
    };
    await s.af.waitForFrame(1);
});
