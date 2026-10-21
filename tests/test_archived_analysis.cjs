const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../digie35/html/digie35.html'), 'utf8');

test('archive analysis blocks duplicate clicks and ignores results for another viewer request', () => {
    const elements = {
        'archived-image-name': {textContent: 'project/film/frame'},
        'archived-image-run-analysis': {disabled: false},
        'archived-image-analysis-status': {}, 'archived-image-analyze-cb': {},
    };
    const calls = [];
    let draws = 0;
    const context = {window: {control_socket: {readyState: 1, OPEN: 1}},
        document: {getElementById: id => elements[id]}, sendCommand: (...args) => calls.push(args),
        adjust_archived_image_mode: () => draws++};
    vm.createContext(context);
    vm.runInContext(html.slice(html.indexOf('    function analyze_archived_preview()'), html.indexOf('    function show_lightbox(')), context);
    context.analyze_archived_preview();
    context.analyze_archived_preview();
    assert.equal(calls.length, 1);
    const request = calls[0][2];
    context.receive_archived_analysis({...request, request_id: 0, vision: {}});
    assert.equal(draws, 0);
    context.receive_archived_analysis({...request, error: 'Disk full'});
    assert.equal(elements['archived-image-run-analysis'].disabled, false);
    assert.equal(elements['archived-image-analysis-status'].textContent, 'Disk full');
    context.analyze_archived_preview();
    context.receive_archived_analysis({...calls[1][2], vision: {score: 123}});
    assert.equal(draws, 1);
    assert.equal(elements['archived-image-analyze-cb'].checked, true);
    assert.equal(context.window.archived_image_analysis.score, 123);
});
