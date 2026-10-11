const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(require('node:path').join(__dirname,'../digie35/html/led_presets.js'),'utf8');
function setup(stored = new Map()) {
    class Option {
        constructor(text,value) {Object.assign(this,{text,value,dataset:{},disabled:false});}
    }
    const select = {value:'white', children:[], get options() {return this.children.flatMap(c=>c.children || [c]);},
        appendChild(c) {c.parent=this;this.children.push(c);},
        querySelectorAll(selector) {return selector.startsWith('optgroup') ? this.children.filter(c=>c.children) : this.options.filter(o=>o.dataset.ledAction);}};
    for (const [value,text] of [['','OFF'],['white','White'],['red+green+blue','RGB'],['white+red+green+blue','RGB+White'],['amber+white+red+green+blue','RGBAW']]) select.appendChild(new Option(text,value));
    const elements = {'backlight-color-list':select,'backlight-exposure':{value:'2'}};
    const el = id => elements[id] ??= {value:'1',checked:true,textContent:'',disabled:false};
    const light = {adapter_class:'Light',adapter_id:'RGB',serial_number:'1'};
    const preset = {id:'one',name:'Test',mode:'white+red+green+blue',light,
        gains:{white:1,red:1.2,green:0.7,blue:2},enabled:{white:false,red:true,green:true,blue:false}};
    const catalog = {light,modes:['red+green+blue','white+red+green+blue'],presets:[preset]};
    const calls=[];
    const context = {console,Option,window:{last_backlight_color:'white'},
        document:{getElementById:el,createElement() {return {dataset:{},children:[],appendChild(c){this.children.push(c);},remove(){this.parent.children=this.parent.children.filter(c=>c!==this);}};}},
        localStorage:{getItem:k=>stored.get(k),setItem:(k,v)=>stored.set(k,v)},
        backlightProfiles:{running:false,request:async (cmd,params)=>{calls.push([cmd,params]);return catalog;}},
        adjust_backlight(){calls.push(['SET',context.api.mode(),el('backlight-exposure').value]);context.api.changed();},
        sendCommand2:cmd=>calls.push([cmd]),update_status_info:msg=>calls.push(['ERROR',msg]),confirm:()=>true,show_modal:()=>{},
        screen_notification:msg=>calls.push(['NOTIFY',msg]),
    };
    vm.createContext(context);vm.runInContext(source+'\nglobalThis.api=ledPresets;',context);
    context.api.init();
    return {api:context.api,context,el,select,catalog,stored,calls,preset};
}

test('base modes precede nonempty preset groups; EV is unchanged on selection', async()=>{
    const h=setup(); await h.api.refresh();
    assert.deepEqual(h.select.children.filter(c=>!c.children).map(c=>c.value),['','white','red+green+blue','white+red+green+blue','amber+white+red+green+blue']);
    assert.deepEqual(h.select.children.filter(c=>c.children).map(c=>c.label),['Presets RGB+White']);
    h.select.value='preset:one';await h.api.choose();
    assert.equal(h.select.value,'preset:one');
    assert.equal(h.api.mode(),'white+red+green+blue');
    assert.equal(h.api.baseOptions.find(o=>o.value===h.api.mode()).text,'RGB+White');
    assert.equal(h.el('backlight-exposure').value,'2');
    assert.equal(h.el('backlight-blue-num').value,2);
    assert.equal(h.el('backlight-blue-switch').checked,false);
    assert.match(h.el('header-backlight-color').textContent,/Test/);
    assert.deepEqual(h.select.querySelectorAll('option[data-led-action]').map(o=>o.value),['action:save','action:update','action:delete']);
});

test('manual gain edits survive OFF, refresh and ON; exposure alone is not dirty',async()=>{
    const h=setup();await h.api.refresh();h.select.value='preset:one';await h.api.choose();
    h.el('backlight-exposure').value='4';h.api.changed();assert.equal(h.api.dirty(),false);
    h.el('backlight-red-num').value='1.8';h.api.changed();assert.equal(h.api.dirty(),true);
    h.select.value='';await h.api.choose();
    assert.equal(h.api.state.selected,'one');assert.equal(h.api.state.on,false);
    assert.equal(h.select.querySelectorAll('option[data-led-action]').length,0);
    const reloaded=setup(h.stored);await reloaded.api.refresh(true);
    assert.equal(reloaded.select.value,'');assert.equal(reloaded.api.state.gains.red,1.8);
    assert.equal(reloaded.context.window.last_backlight_color,'white+red+green+blue');
    assert(!reloaded.calls.some(c=>c[0]==='SET' && c[1]!==''));
    reloaded.api.toggle();
    assert.equal(reloaded.el('backlight-red-num').value,1.8);
    assert.equal(reloaded.el('backlight-blue-switch').checked,false);
    assert.equal(reloaded.api.dirty(),true);
});

test('base mode detaches preset without changing gains; save as works while selected',async()=>{
    const h=setup();await h.api.refresh();h.select.value='preset:one';await h.api.choose();
    h.select.value='action:save';await h.api.choose();
    assert.equal(h.api.editing.id,null);
    assert.equal(h.el('led-preset-name').value,'');
    assert.equal(h.select.value,'preset:one');
    h.select.value=h.preset.mode;await h.api.choose();
    assert.equal(h.api.state.selected,null);
    assert.equal(h.select.value,h.preset.mode);
    assert.equal(h.el('backlight-red-num').value,1.2);
    assert.equal(h.el('header-backlight-color').textContent,'RGB+White');
    assert.deepEqual(h.select.querySelectorAll('option[data-led-action]').map(o=>o.value),['action:save']);
    h.select.value='white';await h.api.choose();
    assert.equal(h.select.querySelectorAll('option[data-led-action]').length,0);
    h.catalog.modes=[];await h.api.refresh();
    assert.equal(h.select.children.filter(c=>c.children).length,0);
});

test('update saves selected name and id immediately without a dialog',async()=>{
    const h=setup();await h.api.refresh();h.select.value='preset:one';await h.api.choose();
    h.context.show_modal=()=>assert.fail('Update must not open a dialog');
    h.el('backlight-red-num').value='1.8';h.api.changed();
    h.context.backlightProfiles.request=async(cmd,params)=>{
        h.calls.push([cmd,params]);
        if(cmd==='LED_PRESET_SAVE') {
            Object.assign(h.preset,params.settings);
            return h.preset;
        }
        return h.catalog;
    };
    h.select.value='action:update';await h.api.choose();
    const saved=h.calls.find(c=>c[0]==='LED_PRESET_SAVE')[1];
    assert.equal(saved.id,'one');assert.equal(saved.name,'Test');assert.equal(saved.settings.gains.red,1.8);
    assert.equal(h.api.dirty(),false);assert.equal(h.select.value,'preset:one');
});

test('calibration changes do not replace saved preset state',async()=>{
    const h=setup();await h.api.refresh();h.select.value='preset:one';await h.api.choose();
    const saved=JSON.stringify(h.api.state);
    h.context.backlightProfiles.running=true;
    h.el('backlight-red-num').value='3';h.api.changed();
    assert.equal(JSON.stringify(h.api.state),saved);
});

test('calibration ending OFF restores last mode and working controls for next ON',async()=>{
    const h=setup();await h.api.refresh();h.select.value='preset:one';await h.api.choose();
    h.select.value='';await h.api.choose();
    h.context.backlightProfiles.running=true;
    h.el('backlight-red-num').value='3';h.context.window.last_backlight_color='red+green+blue';
    h.api.changed();
    h.context.backlightProfiles.running=false;h.api.changed();
    assert.equal(h.context.window.last_backlight_color,'white+red+green+blue');
    assert.equal(h.el('backlight-red-num').value,1.2);
    assert.equal(h.el('backlight-blue-switch').checked,false);
});

test('deleted presets disappear but working gains remain',async()=>{
    const h=setup();await h.api.refresh();h.select.value='preset:one';await h.api.choose();
    let modal=null;
    h.context.show_modal=id=>{modal=id;};
    h.context.get_modal=()=>({id:modal});
    h.context.close_modal=()=>{modal=null;};
    h.context.confirm=()=>assert.fail('Native confirmation must not be used');
    h.context.backlightProfiles.request=async(cmd,params)=>{
        h.calls.push([cmd,params]);
        if(cmd==='LED_PRESET_DELETE') h.catalog.presets=[];
        return h.catalog;
    };
    h.select.value='action:delete';await h.api.choose();
    assert.equal(modal,'led-preset-delete-modal');
    assert(!h.calls.some(c=>c[0]==='LED_PRESET_DELETE'));
    await h.api.confirmRemove();
    assert.equal(modal,null);
    assert.equal(h.calls.filter(c=>c[0]==='LED_PRESET_DELETE').length,1);
    assert.equal(h.api.state.selected,null);
    assert.equal(h.api.state.gains.red,1.2);
    assert.deepEqual(h.select.children.filter(c=>c.children).map(c=>c.label),['Manage LED presets']);
});
