// Exercise the shipped UI with a small DOM harness; all data below are test fixtures.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const nodes = new Map(), handlers = new Map();
function node(id) {
  if (!nodes.has(id)) {
    const classes = new Set();
    nodes.set(id, {value: '', textContent: '', innerHTML: '', dataset: {},
      listeners: {}, classList: {toggle(k, on) {on ? classes.add(k) : classes.delete(k);},
        remove(k) {classes.delete(k);}, contains(k) {return classes.has(k);}},
      addEventListener(k, fn) {this.listeners[k] = fn;}, querySelector() {return null;}, appendChild() {}});
  }
  return nodes.get(id);
}
let failNetwork = false, pendingTrace = null, closedOrderInventory = null, adjustedInventory = null;
const context = vm.createContext({console, Intl, Date, JSON, String, Number,
  document: {getElementById: node, querySelectorAll: () => [], createElement: () => node('temporary'),
    addEventListener(k, fn) {handlers.set(k, fn);}},
  window: {addEventListener() {}}, location: {hash: '#/home'}, history: {replaceState() {}},
  fetch: async (url) => {
    if (failNetwork) throw Error('test offline');
    if (pendingTrace && url.endsWith('/trace')) return new Promise((resolve) => {pendingTrace.resolve = resolve;});
    if (url.includes('/api/resources/inventory/') && adjustedInventory) return {ok:true,json:async()=>({item:adjustedInventory,delta:1})};
    if (url.startsWith('/api/work-orders/') && url.endsWith('/status')) return {ok: true, json: async () => ({status:'completed'})};
    if (url === '/api/bootstrap' && closedOrderInventory) return {ok:true,json:async()=>({pumps:[],workers:[],inventory:closedOrderInventory,work_orders:[]})};
    const data = url === '/health' ? {status: 'ok', transport_mode: 'local_rpc'} :
      url === '/api/agents/status' ? [{name: '资源 Partner', role: 'Partner', status: '可发现候选 / 本地回退'},
        {name: '工单 Partner', role: 'Partner', status: '可发现候选 / 本地回退'}] :
      {pumps: [], workers: [], inventory: [], work_orders: []};
    return {ok: true, json: async () => data};
  }});
vm.runInContext(fs.readFileSync(path.join(__dirname, '../web/app.js'), 'utf8'), context);
(async () => {
  await handlers.get('DOMContentLoaded')();
  vm.runInContext(`state.orders = [
    {id:'a', number:'QA-A', status:'confirmed', request:{pump_id:'p1'}},
    {id:'b', number:'QA-B', status:'completed', request:{pump_id:'p1'}},
    {id:'c', number:'QA-C', status:'confirmed', request:{pump_id:'p2'}}]; renderOrders();`, context);
  node('orderPumpFilter').value = 'p1';
  assert.equal(typeof node('orderPumpFilter').listeners.change, 'function', 'equipment selector must work');
  node('orderPumpFilter').listeners.change({target: node('orderPumpFilter')});
  assert.match(node('orderTableBody').innerHTML, /QA-A/);
  assert.match(node('orderTableBody').innerHTML, /QA-B/);
  assert.doesNotMatch(node('orderTableBody').innerHTML, /QA-C/);
  node('orderStatusFilter').value = 'completed';
  node('orderStatusFilter').listeners.change({target: node('orderStatusFilter')});
  assert.match(node('orderTableBody').innerHTML, /QA-B/);
  assert.doesNotMatch(node('orderTableBody').innerHTML, /QA-A|QA-C/);
  assert.equal(node('resourceHealthDot').classList.contains('good'), false, 'configured candidate is not live health');
  assert.equal(node('resourceHealth').textContent, '未探活');
  vm.runInContext("state.plan = {request:{pump_id:'p1'}}; state.status='completed'; renderPlanView(); setBusy(false);", context);
  assert.doesNotMatch(node('planSideFacts').innerHTML, /已查询，待确认/);
  assert.equal(node('planReviseButton').disabled, true, 'completed proposal cannot be overwritten');
  vm.runInContext("state.status='proposed'; setBusy(true); setBusy(false);", context);
  assert.equal(node('planReviseButton').disabled, false, 'busy state must release revision control');
  vm.runInContext("state.plan=null; state.status='awaiting_input'; setBusy(false);", context);
  assert.equal(node('planConfirmButton').disabled, true, 'empty proposal must not enable confirmation');
  vm.runInContext("state.status='cancelled'; state.request={pump_id:'p1'}; updateAgents();", context);
  assert.equal(node('leaderState').textContent, '已取消');
  assert.equal(node('workorderState').textContent, '未继续');
  failNetwork = true;
  await vm.runInContext('refreshHealth()', context);
  assert.equal(node('resourceHealth').textContent, '状态未知');
  assert.equal(node('workorderHealth').textContent, '状态未知');
  assert.equal(node('leaderHealthDot').classList.contains('good'), false);
  console.log('PASS: filters, truthful health, network failure, terminal proposal, cancellation and busy controls (10 checks)');
  vm.runInContext("state.selectedOrderId='a'; state.orderFilter='completed'; renderOrders();", context);
  assert.equal(vm.runInContext('state.selectedOrderId', context), 'b', 'detail must follow the filtered list');
  vm.runInContext("state.pumpFilter='missing'; renderOrders();", context);
  assert.equal(vm.runInContext('state.selectedOrderId', context), null, 'empty list must clear stale detail');
  assert.match(node('orderDetailContent').innerHTML, /没有符合筛选/);
  vm.runInContext(`state.bootstrap.workers=[{id:'w1',name:'测试人员',skills:'pump_inspection'}];
    state.orders=[]; state.resourceTab='workers'; renderResources();`, context);
  assert.match(node('resourceList').innerHTML, /暂无已记录安排/);
  assert.doesNotMatch(node('resourceList').innerHTML, /空闲|可查询|可用/);
  vm.runInContext(`state.orders=[{id:'qa',number:'QA',status:'confirmed',request:{work_date:'2030-01-02',start_time:'14:00',end_time:'15:00'},
    reservations:[{resource_type:'worker',resource_id:'w1',status:'active'}]}];renderResources();`,context);
  assert.match(node('resourceList').innerHTML, /2030-01-02/);
  vm.runInContext("state.orders[0].status='cancelled'; renderResources();",context);
  assert.doesNotMatch(node('resourceList').innerHTML, /2030-01-02/);
  vm.runInContext("state.status='completed'; state.plan={request:{pump_id:'p1'}}; renderPlanView();",context);
  assert.equal(node('planConfirmButton').textContent, '查看已有工单', 'completed proposal must not look unconfirmed');
  console.log('PASS: filtered detail, empty selection, truthful schedules and completed proposal (5 checks)');
  assert.equal(vm.runInContext("formatDate('2026-10-08T12:47:57+00:00')", context), '2026-10-08 20:47:57', 'UTC timestamps must display in China time');
  vm.runInContext("state.taskId='qa-incomplete';state.plan=null;state.status='awaiting_input';setBusy(false);", context);
  assert.equal(node('cancelTaskButton').disabled, false, 'incomplete task must be cancellable before starting a new task');
  vm.runInContext("state.calls=[{task_id:'qa-incomplete:resource:01',action:'current-query'},{task_id:'foreign-task:resource:01',action:'foreign-query'}];state.auditFilter='partner';renderAudit();",context);
  assert.match(node('auditList').innerHTML,/current-query/);
  assert.doesNotMatch(node('auditList').innerHTML,/foreign-query/,'another task must not appear in current task audit');
  vm.runInContext("state.taskId=null;state.timeline=[];state.messages=[];renderTimeline();renderAudit();",context);
  assert.doesNotMatch(node('auditList').innerHTML,/current-query|foreign-query/,'no task selection must have an empty audit');
  console.log('PASS: China timestamps, incomplete cancellation and task-scoped audit (3 checks)');
  failNetwork = false;
  vm.runInContext("state.taskId='old-task';state.request={pump_id:'original'};state.timeline=[];",context);
  pendingTrace = {};
  const traceRequest = vm.runInContext('loadTrace()',context);
  vm.runInContext("state.taskId='new-task';state.request={pump_id:'new-pump'};",context);
  pendingTrace.resolve({ok:true,json:async()=>({timeline:[{action:'old-step'}],conversation:{request:{pump_id:'old-pump'},messages:[{content:'old-message'}]}})});
  await traceRequest;
  pendingTrace = null;
  assert.equal(vm.runInContext('state.request.pump_id',context),'new-pump','late old trace must not overwrite a new task');
  assert.equal(vm.runInContext('state.timeline.length',context),0);
  vm.runInContext("state.orders=[{id:'active',number:'ACTIVE',status:'in_progress',request:{pump_id:'p1'}}];state.pumpFilter='';state.orderFilter='in_progress';state.selectedOrderId='active';renderOrders();",context);
  await vm.runInContext("updateOrderStatus('active','completed')",context);
  assert.equal(vm.runInContext('state.selectedOrderId',context),null);
  assert.doesNotMatch(node('orderDetailContent').innerHTML,/ACTIVE/,'status updates must not resurrect an order excluded by the current filter');
  console.log('PASS: stale trace response and filtered order status update (2 checks)');
  vm.runInContext("state.taskId='current-task';state.messages=[{role:'assistant',text:'Please confirm'}];",context);
  pendingTrace={};
  const currentTrace=vm.runInContext('loadTrace()',context);
  pendingTrace.resolve({ok:true,json:async()=>({timeline:[],conversation:{messages:[{role:'user',content:'Recorded input only'}]}})});
  await currentTrace;
  assert.equal(vm.runInContext('state.messages[0].text',context),'Please confirm','audit refresh must not erase assistant responses from the visible conversation');
  console.log('PASS: audit refresh preserves the visible conversation (1 check)');
  vm.runInContext("state.status='cancelled';state.plan={request:{pump_id:'p1'}};renderPlanView();",context);
  assert.match(node('planSideFacts').innerHTML,/新建检查任务/,'cancelled proposal must not suggest confirming the cancelled plan');
  console.log('PASS: cancelled proposal suggests a new task (1 check)');
  vm.runInContext("state.status='completed';state.plan={work_order_id:'active'};state.orders=[{id:'active',number:'ACTIVE',status:'in_progress',request:{pump_id:'p1'}}];state.orderFilter='';state.pumpFilter='';renderOrders();",context);
  assert.equal(node('resultText').textContent,'ACTIVE · 处理中','home result must use the latest matching order, not the creation snapshot');
  await vm.runInContext("updateOrderStatus('active','completed')",context);
  assert.equal(node('resultText').textContent,'ACTIVE · 已完成','order lifecycle changes must update the home result too');
  vm.runInContext("state.plan={work_order_id:'another-order'};renderOrders();",context);
  assert.equal(node('resultText').textContent,'ACTIVE · 已完成','selected foreign order must not overwrite the task result');
  console.log('PASS: live home order status and task ownership (1 check)');
  closedOrderInventory=[{id:'tool-inspection-kit',name:'检查工具包',available_qty:2,total_qty:2,unit:'套',category:'tool'}];
  vm.runInContext("state.resourceTab='inventory';state.bootstrap.inventory=[{id:'tool-inspection-kit',available_qty:1}];state.orders=[{id:'closeout',number:'CLOSED',status:'in_progress',request:{}}];",context);
  await vm.runInContext("updateOrderStatus('closeout','completed')",context);
  assert.equal(vm.runInContext('state.bootstrap.inventory[0].available_qty',context),2,'completion must refresh returned tool quantity from the real bootstrap API');
  assert.match(node('resourceList').innerHTML,/检查工具包/);
  console.log('PASS: order closeout refreshes real inventory (1 check)');
  adjustedInventory={id:'tool-inspection-kit',name:'检查工具包',available_qty:3,total_qty:3,unit:'套',category:'tool'};
  vm.runInContext("state.resourceTab='inventory';state.bootstrap.inventory=[{id:'tool-inspection-kit',name:'检查工具包',available_qty:2,total_qty:2,unit:'套',category:'tool'}];renderResources();",context);
  assert.match(node('resourceList').innerHTML,/data-inventory-total-input/, 'inventory rows must expose an editable total quantity');
  assert.match(node('resourceList').innerHTML,/data-inventory-set/, 'inventory rows must expose a save control for manual totals');
  await vm.runInContext("adjustInventory('tool-inspection-kit',1)",context);
  assert.equal(vm.runInContext('state.bootstrap.inventory[0].available_qty',context),3,'manual inventory adjustment must refresh the displayed quantity');
  assert.match(node('resourceList').innerHTML,/减少|增加|检查工具包/);
  console.log('PASS: manual inventory quantity control (1 check)');
})().catch((error) => {console.error(error); process.exitCode = 1;});
