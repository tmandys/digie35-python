const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
function setup() {
    const elements = {};
    const el = id => elements[id] ??= {value:'',checked:true,disabled:false,textContent:''};
    el('camera-list').value='camera';el('backlight-profile-list').value='user:one';el('snapshot-sample-size').value='9';
    el('backlight-color-list').value='red+green+blue';
    const calls=[];
    const settings={color:'red+green+blue',exposure:0,gain:{red:1,green:1,blue:1}};
    const context = {console,window:{snapshot_marker_position:[.4,.6],snapshot_sample_ctx:{},snapshot_canvas_ctx:{},
        control_socket:{readyState:1},current_usbpreview:true},document:{getElementById:el,querySelectorAll:()=>[]},
        localStorage:{getItem:()=>''},preview_settings:()=>({wb_delay:1000}),
        ledPresets:{mode:()=>el('backlight-color-list').value,modes:{'red+green+blue':'RGB'}},
        backlightProfiles:{running:false,request:async(cmd,params)=>{
            calls.push([cmd,params]);
            if(cmd==='WB_BEGIN') return {token:'token',settings};
            if(cmd==='WB_STEP') return {done:true,imbalance:0,settings};
            return {settings,restored:!params.commit};
        }},
        adjust_backlight(){},sendCommand2:cmd=>calls.push([cmd]),screen_notification:msg=>calls.push(['NOTIFY',msg]),
        update_status_info:(msg,key,clear,silent)=>calls.push(['STATUS',msg,key,clear,silent]),
    };
    vm.createContext(context);
    vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../digie35/html/white_balance.js'),'utf8'),context);
    const api=context.window.whiteBalance;
    api.sampler=()=>({measure:async()=>[100,100,100]});
    return {api,context,el,calls};
}

test('WB requires marker, camera, RGB mode, profile and Analyze',async()=>{
    for(const missing of ['marker','camera','mode','profile','analyze']) {
        const h=setup();
        if(missing==='marker') h.context.window.snapshot_marker_position=null;
        if(missing==='camera') h.el('camera-list').value='';
        if(missing==='mode') h.el('backlight-color-list').value='white';
        if(missing==='profile') h.el('backlight-profile-list').value='';
        if(missing==='analyze') h.el('stream-analyze-cb').checked=false;
        h.api.update();assert.equal(h.el('snapshot-wb').disabled,true);
        await h.api.start();assert(!h.calls.some(c=>c[0].startsWith('WB_')));
    }
});

test('nonzero WB imbalance travels through the real RPC receiver as a successful step',async()=>{
    const h=setup();
    h.context.clearTimeout=clearTimeout;
    vm.runInContext(fs.readFileSync(require('node:path').join(__dirname,'../digie35/html/backlight_profiles.js'),'utf8')+'\nglobalThis.rpc=backlightProfiles;',h.context);
    const rpc=h.context.rpc;
    const reply={done:false,step:1,imbalance:1.0612431444241315,client_context:{profile_request:42}};
    const response=new Promise((resolve,reject)=>rpc.pending.set(42,{cmd:'WB_STEP',resolve,reject}));
    assert.equal(rpc.receive({cmd:'WB_STEP',payload:reply}),true);
    assert.equal((await response).imbalance,reply.imbalance);
});

test('disabled RGB channels allow WB and send their stored gains',async()=>{
    const h=setup();
    h.el('backlight-red-switch').checked=false;
    h.el('backlight-red-num').value='1.7';
    h.api.update();assert.equal(h.el('snapshot-wb').disabled,false);
    await h.api.start();
    assert.equal(h.calls.find(c=>c[0]==='WB_BEGIN')[1].enable_gains.red,1.7);
    h.api.apply({color:'red+green+blue',gain:{red:0}}, {red:1.7});
    assert.equal(h.el('backlight-red-switch').checked,false);
    assert.equal(h.el('backlight-red-num').value,1.7);
});

test('converged WB commits, then refreshes state',async()=>{
    const h=setup();await h.api.start();
    assert.deepEqual(h.calls.filter(c=>c[0].startsWith('WB_')).map(c=>c[0]),['WB_BEGIN','WB_STEP','WB_END']);
    assert.equal(h.calls.find(c=>c[0]==='WB_END')[1].commit,true);
    assert.equal(h.api.running,false);
    assert(h.calls.some(c=>c[0]==='NOTIFY'));
});

test('snapshot failure, cancellation and marker changes restore gains without committing',async()=>{
    for(const cause of ['timeout','cancel','marker']) {
        const h=setup();
        h.api.sampler=run=>({measure:async()=>{
            if(cause==='timeout') throw new Error('No fresh snapshot');
            if(cause==='cancel') await h.api.start();
            else h.context.window.snapshot_marker_position=[.1,.2];
            h.api.check(run);
        }});
        await h.api.start();
        assert(!h.calls.some(c=>c[0]==='WB_STEP'));
        assert.equal(h.calls.find(c=>c[0]==='WB_END')[1].commit,false);
        assert(h.calls.some(c=>c[0]==='STATUS' && /restored/.test(c[1])));
        assert.equal(h.api.running,false);
    }
});

test('lost begin response still requests server restoration',async()=>{
    const h=setup(), request=h.context.backlightProfiles.request;
    h.context.backlightProfiles.request=async(cmd,params)=>{
        if(cmd==='WB_BEGIN') throw new Error('timeout');
        return request(cmd,params);
    };
    await h.api.start();
    assert.equal(h.calls.find(c=>c[0]==='WB_END')[1].commit,false);
});

test('snapshot outage allows explicit keep or restore of unfinished WB', async()=>{
    for (const keep of [true,false]) {
        const h=setup();
        h.api.sampler=()=>({measure:async()=>{throw Object.assign(new Error('No frames'),{snapshotUnavailable:true});}});
        h.api.choosePartial=async()=>keep;
        await h.api.start();
        const end=h.calls.find(c=>c[0]==='WB_END');
        assert.equal(end[1].commit,keep);
        assert.equal(!!end[1].keep_partial,keep);
        assert.equal(h.api.running,false);
    }
});
