const state = {
  sessionId: null,
  taskId: null,
  messageId: null,
  request: null,
  plan: null,
  status: 'awaiting_input',
  messages: [],
  discovery: null,
  bootstrap: { pumps: [], workers: [], inventory: [], work_orders: [] },
  orders: [],
  timeline: [],
  calls: [],
  busy: false,
  orderFilter: '',
  pumpFilter: '',
  resourceTab: 'workers',
  auditFilter: 'all'
};

const $ = (id) => document.getElementById(id);
const esc = (value) => String(value ?? '').replace(/[&<>"']/g, (char) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[char]));
const statusLabels = { awaiting_input: '待补充', ready_for_plan: '待确认', proposed: '待确认', completed: '已完成', cancelled: '已取消', replan_required: '需重新安排', discovery_failed: '发现失败', confirmed: '待处理', in_progress: '处理中', pending: '待处理' };
const statusClass = (status) => ['completed', 'success'].includes(status) ? 'success' : ['cancelled', 'failed', 'discovery_failed'].includes(status) ? 'error' : ['ready_for_plan', 'proposed', 'confirmed', 'in_progress', 'awaiting_input', 'pending', 'replan_required'].includes(status) ? 'pending' : 'neutral';
const api = async (path, options = {}) => {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail?.message || data.detail || `请求失败（${response.status}）`);
  return data;
};
const formatDate = (value) => value ? String(value).replace('T', ' ').replace('Z', '') : '—';
const formatStatus = (value) => statusLabels[value] || value || '—';
const humanLabels = {pump_inspection:'泵体检查',electrical_inspection:'电气检查',part:'配件',tool:'工具',leader:'协调主控',resource:'资源服务',workorder:'工单服务',resource_partner:'资源服务',work_order_partner:'工单服务',request_created:'登记检查需求',request_updated:'更新检查时间',plan_generated:'生成检查方案',plan_replanned:'重新协调资源',resource_reserved:'预留资源',resources_released:'释放资源',work_order_created:'创建工单',work_order_cancelled:'取消工单',work_order_status_updated:'更新工单进度',query_resources:'查询资源',reserve_resources:'预留资源',release_resources:'释放资源',create_work_order:'创建工单',update_work_order:'更新工单',cancel_work_order:'取消工单',completed:'已完成',failed:'失败',accepted:'已接收',working:'处理中'};
const humanLabel = (value) => humanLabels[value] || value || '—';

const setStatus = (message, kind = '') => { const node = $('statusBar'); if (!node) return; node.textContent = message || ''; node.className = `status-bar ${kind}`; };
function updateActionAvailability() {
  const terminal = ['completed', 'cancelled'].includes(state.status);
  ['confirmButton', 'planConfirmButton'].forEach((id) => { if ($(id)) $(id).disabled = state.busy || !state.plan || state.status === 'cancelled'; });
  ['reviseButton', 'planReviseButton', 'cancelTaskButton', 'planCancelButton'].forEach((id) => { if ($(id)) $(id).disabled = state.busy || !state.plan || terminal; });
}
const setBusy = (busy) => {
  state.busy = busy;
  $('conversationPanel')?.classList.toggle('is-busy', busy);
  if ($('sendButton')) { $('sendButton').textContent = busy ? '处理中…' : '发送消息'; $('sendButton').disabled = busy; }
  updateActionAvailability();
};
const setBadge = (node, status) => { if (!node) return; node.textContent = formatStatus(status); node.className = `status-badge ${statusClass(status)}`; };

function updateTechnical(payload = null) {
  if ($('techSession')) $('techSession').textContent = state.sessionId || '尚未建立';
  if ($('techTask')) $('techTask').textContent = state.taskId || '尚未建立';
  if ($('techMessage')) $('techMessage').textContent = state.messageId || '尚未建立';
  if ($('techPayload') && payload) $('techPayload').textContent = JSON.stringify(payload, null, 2);
}

function addMessage(role, text) {
  if (!text) return;
  state.messages.push({ role, text, created_at: new Date().toISOString() });
  const list = $('messageList');
  if (!list) return;
  if (list.querySelector('.empty-conversation')) list.innerHTML = '';
  const node = document.createElement('div');
  node.className = `message ${role}`;
  node.innerHTML = `<span class="avatar ${role === 'assistant' ? 'leader' : ''}">${role === 'user' ? '你' : 'L'}</span><div><strong>${role === 'user' ? '你' : '工维联 Leader'}</strong><p>${esc(text)}</p><time>${new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date())}</time></div>`;
  list.appendChild(node);
  list.scrollTop = list.scrollHeight;
}

function renderMessagesFromState() {
  const list = $('messageList');
  if (!list) return;
  if (!state.messages.length) {
    list.innerHTML = `<div class="empty-conversation"><svg class="welcome-mark" viewBox="0 0 190 60" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M50 30h25m40 0h25"/><circle cx="30" cy="30" r="22"/><circle cx="95" cy="30" r="22"/><circle cx="160" cy="30" r="22"/><path d="M23 19h10l5 5v17H23zM32 19v7h6M27 31h7m-7 5h7"/><circle cx="95" cy="26" r="5"/><path d="M85 41v-4a10 10 0 0 1 20 0v4M163 19a8 8 0 0 0-9 11l-8 8 5 5 8-8a8 8 0 0 0 11-9l-6 5-5-5z"/></svg><div><strong>今天需要检查什么？</strong><p>告诉我设备、异常和检查时间。<br>协调人员与工具后，由你确认每一次安排。</p></div></div>`;
    return;
  }
  list.innerHTML = '';
  state.messages.forEach((message) => {
    const node = document.createElement('div');
    node.className = `message ${message.role}`;
    node.innerHTML = `<span class="avatar ${message.role === 'assistant' ? 'leader' : ''}">${message.role === 'user' ? '你' : 'L'}</span><div><strong>${message.role === 'user' ? '你' : '工维联 Leader'}</strong><p>${esc(message.text)}</p><time>${formatDate(message.created_at).slice(11, 16)}</time></div>`;
    list.appendChild(node);
  });
}

function updateStepper(status) {
  const index = { awaiting_input: 1, ready_for_plan: 3, proposed: 4, completed: 5, cancelled: 1, replan_required: 3, discovery_failed: 2 }[status] ?? 0;
  document.querySelectorAll('#stepper .step').forEach((step, idx) => { step.classList.toggle('active', idx <= index); step.classList.toggle('current', idx === index); });
  setBadge($('taskStatus'), status);
  setBadge($('currentTaskBadge'), status);
  setBadge($('planPageBadge'), status);
  setBadge($('proposalStatus'), state.plan ? status : 'awaiting_input');
}

function planValues(plan) {
  const request = plan?.request || state.request || {};
  return {
    device: request.pump_id || request.id || '—',
    window: [request.work_date, request.start_time && request.end_time ? `${request.start_time}–${request.end_time}` : request.start_time].filter(Boolean).join(' ') || '—',
    duration: request.duration_minutes ? `${request.duration_minutes} 分钟` : '—',
    worker: plan?.worker?.name || plan?.worker_id || '—',
    inventory: (plan?.inventory || []).map((item) => item.name || item).join('、') || '未记录',
    description: request.description || '—'
  };
}

function renderPlan(plan) {
  if (!plan) return;
  state.plan = plan;
  const values = planValues(plan);
  $('planEmpty').hidden = true;
  $('planContent').hidden = false;
  $('planDevice').textContent = values.device;
  $('planWindow').textContent = values.window;
  $('planDuration').textContent = values.duration;
  $('planWorker').textContent = values.worker;
  $('planInventory').textContent = values.inventory;
  $('planReason').textContent = plan.reason || '按技能、时间和库存匹配当前可用资源。';
  renderPlanView();
}

function renderCurrentTask() {
  const box = $('currentTaskFacts');
  const request = state.request || state.plan?.request;
  if (!box) return;
  if (!request) {
    box.innerHTML = '<div><span>设备</span><strong>等待输入</strong></div><div><span>问题描述</span><strong>—</strong></div><div><span>计划时间</span><strong>—</strong></div><div><span>预计时长</span><strong>—</strong></div><div><span>下一步</span><strong>发送异常描述</strong></div>';
    return;
  }
  const values = planValues(state.plan || { request });
  const nextStep = state.status === 'cancelled' ? '本次安排已取消' : state.status === 'completed' ? '查看工单结果' : state.plan ? '确认方案并创建工单' : state.status === 'awaiting_input' ? '补充检查信息' : state.status === 'replan_required' ? '修改时间后重新安排' : '等待资源查询';
  box.innerHTML = `<div><span>设备</span><strong>${esc(values.device)}</strong></div><div><span>问题描述</span><strong>${esc(values.description)}</strong></div><div><span>计划时间</span><strong>${esc(values.window)}</strong></div><div><span>预计时长</span><strong>${esc(values.duration)}</strong></div><div><span>下一步</span><strong>${esc(nextStep)}</strong></div>`;
}

function updateAgents() {
  const leader = $('leaderState');
  const resource = $('resourceState');
  const workorder = $('workorderState');
  if (leader) leader.textContent = state.status === 'cancelled' ? '已取消' : state.status === 'awaiting_input' ? '待补充' : state.status === 'completed' ? '已汇总' : state.request ? '处理中' : '等待';
  if (resource) resource.textContent = state.status === 'cancelled' ? '已取消安排' : state.plan ? '已返回方案' : state.request ? '已查询' : '未调用';
  if (workorder) workorder.textContent = state.status === 'cancelled' ? '未继续' : state.status === 'completed' ? '已完成' : state.plan ? '等待确认' : '未调用';
  if ($('userState')) $('userState').textContent = state.messages.length ? '已输入' : '输入';
}

function showDiscovery(result) {
  state.discovery = result.discovery || null;
  if (!result.discovery) return;
  const source = result.discovery.source === 'static_fallback' ? '本地回退' : result.discovery.selected ? '已发现' : '未找到';
  if ($('resourceState')) $('resourceState').textContent = source;
}

async function ensureSession() {
  if (state.sessionId) return;
  const result = await api('/api/conversations', { method: 'POST', body: '{}' });
  state.sessionId = result.session_id;
  state.taskId = result.task_id;
  updateTechnical();
}

async function sendMessage(text) {
  if (!text.trim() || state.busy) return;
  setBusy(true);
  try {
    await ensureSession();
    addMessage('user', text);
    setStatus('Leader 正在理解请求并检查协作条件…');
    const result = await api(`/api/conversations/${state.sessionId}/messages`, { method: 'POST', body: JSON.stringify({ text }) });
    state.messageId = result.message_id || state.messageId;
    state.status = result.plan ? 'proposed' : result.status;
    state.request = result.request || state.request;
    if (result.plan) state.plan = result.plan;
    updateTechnical(result);
    $('parserMode').textContent = result.parser_mode === 'deterministic_fallback' ? '规则解析' : '模型解析';
    updateStepper(state.status);
    if (result.question) {
      addMessage('assistant', result.question);
      $('missingBox').hidden = false;
      $('missingText').textContent = result.question;
      setStatus('还需要补充信息，确认前不会预留资源。', 'warning');
    } else if (result.plan) {
      addMessage('assistant', '信息已补齐，资源协调 Partner 已返回待确认方案。');
      $('missingBox').hidden = true;
      renderPlan(result.plan);
      showDiscovery(result);
      setStatus('方案已生成。确认前不会预留资源或创建工单。', 'success');
    } else if (result.conflict) {
      addMessage('assistant', `资源发生冲突：${result.conflict.join('、')}。请修改时间后重新安排。`);
      setStatus('发现资源冲突，未创建工单。', 'warning');
    } else if (result.status === 'discovery_failed') {
      addMessage('assistant', result.question || '暂时没有找到可用的协作者。');
      setStatus('在线发现未返回可用 Partner。', 'error');
    }
    renderCurrentTask();
    updateAgents();
    renderPlanView();
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    setBusy(false);
  }
}

async function confirmTask() {
  if (!state.taskId || state.busy) return;
  setBusy(true);
  setStatus('正在再次校验资源并创建工单…');
  try {
    const result = await api(`/api/tasks/${state.taskId}/confirm`, { method: 'POST', headers: { 'Idempotency-Key': `web-${state.taskId}` }, body: '{}' });
    state.status = 'completed';
    state.plan = result.plan || state.plan;
    updateTechnical(result);
    updateStepper('completed');
    $('resultBox').hidden = false;
    $('resultText').textContent = `任务已完成，工单 ${result.work_order?.number || '已创建'}。重复确认会返回同一工单。`;
    addMessage('assistant', `已确认方案并创建工单 ${result.work_order?.number || ''}。资源和工单 Partner 已返回完成状态。`);
    setStatus('工单创建完成，重复确认会被幂等保护。', 'success');
    renderCurrentTask();
    updateAgents();
    await loadOrders();
    renderPlanView();
  } catch (error) {
    setStatus(error.message, 'error');
  } finally {
    setBusy(false);
  }
}

async function cancelTask() {
  if (!state.taskId || state.busy) return;
  try {
    const result = await api(`/api/tasks/${state.taskId}/cancel`, { method: 'POST', body: '{}' });
    state.status = 'cancelled';
    updateTechnical(result);
    updateStepper('cancelled');
    addMessage('assistant', '任务已取消，未继续执行。');
    setStatus('任务已取消。', 'warning');
    renderCurrentTask();
    updateAgents();
    renderPlanView();
  } catch (error) { setStatus(error.message, 'error'); }
}

function reviseTask() {
  if (!state.taskId) { setStatus('请先创建一个检查任务。', 'warning'); return; }
  showView('home');
  $('messageInput').value = '刚才那个方案时间不合适，改到下午三点。';
  $('messageInput').focus();
  setStatus('请发送新的时间，系统会沿用当前任务上下文。', '');
}

async function loadBootstrap() {
  try {
    const result = await api('/api/bootstrap');
    state.bootstrap = result;
    state.orders = result.work_orders || state.orders;
    fillPumpFilter();
  } catch (error) { setStatus(`业务数据暂时无法读取：${error.message}`, 'error'); }
}

async function loadOrders() {
  try {
    state.orders = await api('/api/work-orders');
    state.bootstrap.work_orders = state.orders;
    renderOrders();
  } catch (error) { $('orderListMeta').textContent = `加载失败：${error.message}`; }
}

function fillPumpFilter() {
  const select = $('orderPumpFilter');
  if (!select) return;
  const pumps = state.bootstrap.pumps || [];
  select.innerHTML = '<option value="">全部设备</option>' + pumps.map((pump) => `<option value="${esc(pump.id)}">${esc(pump.name || pump.id)}</option>`).join('');
  select.value = state.pumpFilter;
}

function filteredOrders() {
  return state.orders.filter((order) => {
    const pumpId = order.request?.pump_id || order.request?.pump?.id || '';
    return (!state.orderFilter || order.status === state.orderFilter) && (!state.pumpFilter || pumpId === state.pumpFilter);
  });
}

function pumpLabel(request) {
  return request?.pump?.name || request?.pump_id || '—';
}

function workerLabel(order) {
  const fromPlan = order.plan?.worker?.name || order.plan?.worker_id;
  if (fromPlan) return fromPlan;
  const reservation = (order.reservations || []).find((item) => item.resource_type === 'worker');
  const worker = (state.bootstrap.workers || []).find((item) => item.id === reservation?.resource_id);
  return worker?.name || reservation?.resource_id || '—';
}

function renderOrders() {
  const rows = filteredOrders();
  const counts = state.orders.reduce((acc, order) => { acc[order.status] = (acc[order.status] || 0) + 1; return acc; }, {});
  const filterList = $('orderFilterList');
  if (filterList) filterList.innerHTML = `<button class="filter-row ${!state.orderFilter ? 'selected' : ''}" type="button" data-order-status=""><span>全部工单</span><b>${state.orders.length}</b></button>${[['confirmed', '待处理'], ['in_progress', '处理中'], ['completed', '已完成'], ['cancelled', '已取消']].map(([key, label]) => `<button class="filter-row ${state.orderFilter === key ? 'selected' : ''}" type="button" data-order-status="${key}"><span>${label}</span><b>${counts[key] || 0}</b></button>`).join('')}`;
  if ($('orderListTitle')) $('orderListTitle').textContent = state.orderFilter ? formatStatus(state.orderFilter) : '全部工单';
  if ($('orderListMeta')) $('orderListMeta').textContent = `共 ${rows.length} 张工单 · 从后端实时读取`;
  const body = $('orderTableBody');
  if (!body) return;
  if (!rows.length) { body.innerHTML = '<tr><td colspan="6"><div class="table-empty">当前筛选没有工单</div></td></tr>'; return; }
  body.innerHTML = rows.map((order) => {
    const request = order.request || {};
    const plan = order.plan || {};
    const worker = workerLabel(order);
    const device = pumpLabel(request);
    const time = [request.work_date, request.start_time].filter(Boolean).join(' ');
    return `<tr data-order-id="${esc(order.id)}"><td><button class="link-button" type="button" data-order-id="${esc(order.id)}">${esc(order.number)}</button></td><td>${esc(device)}</td><td>${esc(time || '—')}</td><td>${esc(worker)}</td><td><span class="status-badge ${statusClass(order.status)}">${esc(formatStatus(order.status))}</span></td><td><button class="icon-button" type="button" data-order-id="${esc(order.id)}" aria-label="查看工单详情">→</button></td></tr>`;
  }).join('');
  if (!state.selectedOrderId && rows[0]) renderOrderDetail(rows[0].id);
}

function renderOrderDetail(orderId) {
  const order = state.orders.find((item) => item.id === orderId);
  if (!order) return;
  state.selectedOrderId = orderId;
  const request = order.request || {};
  const plan = order.plan || {};
  const worker = workerLabel(order);
  $('orderDetailTitle').textContent = order.number || '工单详情';
  setBadge($('orderDetailBadge'), order.status);
  $('orderDetailContent').innerHTML = `<dl class="detail-list"><div><dt>设备</dt><dd>${esc(pumpLabel(request))}</dd></div><div><dt>异常描述</dt><dd>${esc(request.description || '—')}</dd></div><div><dt>计划时间</dt><dd>${esc([request.work_date, request.start_time].filter(Boolean).join(' ') || '—')}</dd></div><div><dt>预计时长</dt><dd>${request.duration_minutes ? `${esc(request.duration_minutes)} 分钟` : '—'}</dd></div><div><dt>执行人员</dt><dd>${esc(worker)}</dd></div><div><dt>创建时间</dt><dd>${esc(formatDate(order.created_at))}</dd></div></dl><div class="order-progress"><strong>处理进度</strong><div class="progress-line"><span class="done">工单已创建</span><span class="${order.status === 'in_progress' || order.status === 'completed' ? 'done' : ''}">处理中</span><span class="${order.status === 'completed' ? 'done' : ''}">处理完成</span></div></div><div class="detail-actions">${order.status !== 'cancelled' && order.status !== 'completed' ? `<button class="button primary" type="button" data-order-action="in_progress" data-order-id="${esc(order.id)}">标记处理中</button><button class="button danger" type="button" data-order-action="cancelled" data-order-id="${esc(order.id)}">取消工单</button>` : ''}${order.status === 'in_progress' ? `<button class="button secondary" type="button" data-order-action="completed" data-order-id="${esc(order.id)}">标记已完成</button>` : ''}</div>`;
}

async function updateOrderStatus(orderId, action) {
  try {
    const result = action === 'cancelled' ? await api(`/api/work-orders/${orderId}/cancel`, { method: 'POST' }) : await api(`/api/work-orders/${orderId}/status`, { method: 'POST', body: JSON.stringify({ status: action }) });
    state.orders = state.orders.map((order) => order.id === orderId ? { ...order, ...result, request: order.request, plan: order.plan } : order);
    renderOrders();
    renderOrderDetail(orderId);
    setStatus(`工单已更新为“${formatStatus(action)}”。`, 'success');
  } catch (error) { setStatus(error.message, 'error'); }
}

function renderPlanView() {
  const plan = state.plan;
  const summary = $('planConversationSummary');
  if (summary) summary.innerHTML = state.messages.length ? state.messages.slice(-4).map((message) => `<div class="summary-message ${message.role}"><span class="avatar ${message.role === 'assistant' ? 'leader' : ''}">${message.role === 'user' ? '你' : 'L'}</span><p>${esc(message.text)}</p></div>`).join('') : '<div class="empty-state compact-empty"><strong>还没有可确认的方案</strong><p>先回到主协作页描述一次检查请求。</p></div>';
  const request = state.request || plan?.request;
  if ($('requestFacts')) {
    $('requestFacts').hidden = !request;
    if (request) $('requestFacts').innerHTML = `<strong>需求事实</strong><div><span>设备</span><b>${esc(request.pump_id || '—')}</b></div><div><span>描述</span><b>${esc(request.description || '—')}</b></div>`;
  }
  const proposal = $('proposalFacts');
  if (proposal) {
    proposal.innerHTML = plan ? `<div class="proposal-table"><div><span>设备</span><strong>${esc(planValues(plan).device)}</strong></div><div><span>异常描述</span><strong>${esc(planValues(plan).description)}</strong></div><div><span>检查时间</span><strong>${esc(planValues(plan).window)}</strong></div><div><span>预计时长</span><strong>${esc(planValues(plan).duration)}</strong></div><div><span>检查人员</span><strong>${esc(planValues(plan).worker)}</strong></div><div><span>工具与配件</span><strong>${esc(planValues(plan).inventory)}</strong></div><div class="proposal-wide"><span>安排依据</span><strong>${esc(plan.reason || '按技能、时段和库存匹配。')}</strong></div></div>` : '<div class="empty-state compact-empty"><strong>方案尚未生成</strong><p>信息完整后，Leader 会显示人员、时间和库存。</p></div>';
  }
  updateActionAvailability();
  const side = $('planSideFacts');
  if (side) { const values = planValues(plan); const resourceStatus = state.status === 'completed' ? '已确认并预留' : state.status === 'cancelled' ? '已取消' : state.status === 'replan_required' ? '有冲突，需重新安排' : plan ? '已查询，待确认' : '等待查询'; const nextStep = state.status === 'completed' ? '查看工单' : state.status === 'replan_required' ? '修改时间后重新安排' : plan ? '确认并创建工单' : '等待方案'; side.innerHTML = `<div><span>设备</span><strong>${esc(values.device)}</strong></div><div><span>计划时间</span><strong>${esc(values.window)}</strong></div><div><span>资源状态</span><strong>${esc(resourceStatus)}</strong></div><div><span>下一步</span><strong>${esc(nextStep)}</strong></div>`; }
  updateStepper(state.status);
  const chain = $('planAgentChain');
  if (chain) chain.innerHTML = `<div class="agent-node"><span class="agent-icon user">你</span><div><strong>用户 / 叮当</strong><small>提出检查需求</small></div><b>已输入</b></div><span class="chain-arrow">→</span><div class="agent-node"><span class="agent-icon leader">L</span><div><strong>工维联 Leader</strong><small>理解 · 规划 · 汇总</small></div><b>${state.request ? '已处理' : '等待'}</b></div><span class="chain-arrow">→</span><div class="agent-node"><span class="agent-icon resource">R</span><div><strong>资源协调 Partner</strong><small>人员 · 技能 · 库存</small></div><b>${plan ? '已返回' : '等待'}</b></div><span class="chain-arrow">→</span><div class="agent-node"><span class="agent-icon order">W</span><div><strong>工单处理 Partner</strong><small>创建 · 生命周期</small></div><b>${state.status === 'completed' ? '已完成' : '等待确认'}</b></div>`;
}

async function loadResources() {
  try {
    await loadBootstrap();
    renderResources();
    if (state.taskId) await loadTrace();
    state.calls = await api('/api/aip-calls').catch(() => []);
    renderAudit();
  } catch (error) { setStatus(`协作记录暂时无法读取：${error.message}`, 'error'); }
}

async function loadTrace() {
  try {
    const result = await api(`/api/tasks/${state.taskId}/trace`);
    state.timeline = result.timeline || [];
    if (result.conversation?.messages?.length) state.messages = result.conversation.messages.map((message) => ({ role: message.role === 'user' ? 'user' : 'assistant', text: message.content, created_at: message.created_at }));
    state.request = result.conversation?.request || state.request;
    renderTimeline();
    renderMessagesFromState();
  } catch (error) { setStatus(`任务轨迹读取失败：${error.message}`, 'error'); }
}

function renderResources() {
  const list = $('resourceList');
  if (!list) return;
  if (state.resourceTab === 'inventory') {
    const items = state.bootstrap.inventory || [];
    list.innerHTML = items.length ? items.map((item) => `<article class="resource-card"><div class="resource-avatar inventory">□</div><div class="resource-main"><strong>${esc(item.name)}</strong><span>${esc(humanLabel(item.category || '库存'))} · ${esc(item.unit || '件')}</span><div class="resource-meta">可用 <b>${esc(item.available_qty)}</b> / ${esc(item.total_qty)}</div></div><span class="status-badge ${item.available_qty > 0 ? 'success' : 'error'}">${item.available_qty > 0 ? '可用' : '无库存'}</span></article>`).join('') : '<div class="empty-state compact-empty"><strong>暂无库存记录</strong><p>当前数据库没有可展示的库存。</p></div>';
  } else {
    const workers = state.bootstrap.workers || [];
    list.innerHTML = workers.length ? workers.map((worker) => `<article class="resource-card"><div class="resource-avatar">${esc((worker.name || '?').slice(0, 1))}</div><div class="resource-main"><strong>${esc(worker.name)}</strong><span>${esc(worker.role || '现场人员')}</span><div class="skill-list">${(worker.skills || '').split(',').filter(Boolean).map((skill) => `<em>${esc(humanLabel(skill))}</em>`).join('') || '<em>技能未记录</em>'}</div></div><span class="status-badge success">可查询</span></article>`).join('') : '<div class="empty-state compact-empty"><strong>暂无人员记录</strong><p>当前数据库没有可展示的人员。</p></div>';
  }
}

function renderTimeline() {
  const list = $('timelineList');
  if (!list) return;
  if (!$('timelineMeta')) return;
  $('timelineMeta').textContent = state.timeline.length ? `${state.timeline.length} 条真实事件` : '选择任务后显示真实事件';
  if (!state.timeline.length) { list.innerHTML = '<div class="empty-state compact-empty"><strong>暂无可显示的任务轨迹</strong><p>完成一次对话后，这里会显示 Leader 与 Partner 的事件。</p></div>'; return; }
  list.innerHTML = state.timeline.map((event) => `<div class="timeline-item"><time>${esc(formatDate(event.created_at).slice(11, 16))}</time><span class="timeline-dot"></span><div><strong>${esc(humanLabel(event.event_type || '业务事件'))}</strong><p>${esc(humanLabel(event.actor || '系统'))}</p><details><summary>技术详情</summary><pre>${esc(JSON.stringify(event.details || {}, null, 2))}</pre></details></div><span class="status-badge success">已记录</span></div>`).join('');
}

function renderAudit() {
  const rows = [];
  state.messages.slice(-12).forEach((message) => rows.push({ kind: 'message', title: message.role === 'user' ? '用户输入' : 'Leader 返回', detail: message.text, created_at: message.created_at, status: '已记录' }));
  state.timeline.slice(-12).forEach((event) => rows.push({ kind: event.event_type?.includes('partner') ? 'partner' : 'task', title: event.event_type || '业务事件', detail: event.actor || '系统', created_at: event.created_at, status: '已记录' }));
  state.calls.slice(-12).forEach((call) => rows.push({ kind: 'partner', title: call.action || call.method || 'Partner 调用', detail: call.partner || call.agent || '调用记录', created_at: call.created_at || call.timestamp, status: call.status || '已记录' }));
  const filtered = rows.filter((row) => state.auditFilter === 'all' || row.kind === state.auditFilter);
  const list = $('auditList');
  if (!list) return;
  list.innerHTML = filtered.length ? filtered.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))).map((row) => `<article class="audit-row"><time>${esc(formatDate(row.created_at).slice(11, 16))}</time><span class="audit-kind ${esc(row.kind)}">${esc({message:'消息',task:'任务',partner:'协作',session:'会话'}[row.kind] || row.kind)}</span><div><strong>${esc(humanLabel(row.title))}</strong><p>${esc(humanLabel(row.detail))}</p></div><span class="status-badge ${row.status === 'failed' ? 'error' : 'neutral'}">${esc(humanLabel(row.status))}</span></article>`).join('') : '<div class="empty-state compact-empty"><strong>暂无调用记录</strong><p>完成一次任务后，这里会汇总消息、任务和 Partner 调用。</p></div>';
  if ($('auditRaw')) $('auditRaw').textContent = JSON.stringify({ timeline: state.timeline, calls: state.calls }, null, 2);
}

async function refreshHealth() {
  try {
    const health = await api('/health');
    const online = health.status === 'ok';
    $('leaderHealth').textContent = online ? '在线' : '待处理';
    $('leaderHealthDot').classList.toggle('good', online);
    $('runtimeMode').textContent = `${health.transport_mode === 'local_rpc' ? '直连业务模式' : '平台 MQ'} · ${online ? '运行中' : '配置待处理'}`;
    const agents = await api('/api/agents/status').catch(() => []);
    const resource = agents.find((item) => item.role === 'Partner' && String(item.name).includes('资源'));
    const workorder = agents.find((item) => item.role === 'Partner' && String(item.name).includes('工单'));
    // The current endpoint lists configured candidates, not connectivity probes.
    // Only an explicit successful health probe can turn a Partner indicator green.
    for (const [name, agent] of [['resource', resource], ['workorder', workorder]]) {
      const live = agent?.health?.status === 'ok';
      $(`${name}Health`).textContent = live ? '在线' : agent ? '未探活' : '状态未知';
      $(`${name}HealthDot`).classList.toggle('good', live);
    }
  } catch (error) {
    $('leaderHealth').textContent = '待处理';
    $('resourceHealth').textContent = '状态未知';
    $('workorderHealth').textContent = '状态未知';
    $('runtimeMode').textContent = '服务状态待处理';
    ['leaderHealthDot', 'resourceHealthDot', 'workorderHealthDot'].forEach((id) => $(id)?.classList.remove('good'));
  }
}

function showView(view, updateHash = true) {
  const known = ['home', 'plan', 'orders', 'resources'];
  const target = known.includes(view) ? view : 'home';
  document.querySelectorAll('[data-view-panel]').forEach((panel) => { panel.hidden = panel.dataset.viewPanel !== target; });
  document.querySelectorAll('.nav-item').forEach((item) => { item.classList.toggle('active', item.dataset.view === target); item.setAttribute('aria-current', item.dataset.view === target ? 'page' : 'false'); });
  if ($('currentViewLabel')) $('currentViewLabel').textContent = {home:'主协作',plan:'方案确认',orders:'工单中心',resources:'资源与审计'}[target];
  if (updateHash) window.scrollTo?.({top:0, behavior:'instant'});
  if (updateHash && location.hash !== `#/${target}`) history.replaceState(null, '', `#/${target}`);
  if (target === 'plan') renderPlanView();
  if (target === 'orders') { loadOrders(); }
  if (target === 'resources') { loadResources(); }
}

function initAudio() {
  $('audioFile')?.addEventListener('change', (event) => { const file = event.target.files?.[0]; $('analyzeAudioButton').disabled = !file; $('audioFileMeta').textContent = file ? `${file.name} · ${Math.round(file.size / 1024)} KB` : '尚未选择录音'; });
  $('analyzeAudioButton')?.addEventListener('click', async () => {
    const file = $('audioFile').files?.[0]; if (!file) return;
    const reader = new FileReader(); reader.onload = async () => { try { const result = await api('/api/audio/analyze', { method: 'POST', body: JSON.stringify({ filename: file.name, audio_base64: String(reader.result).split(',')[1] || '' }) }); $('audioResult').hidden = false; $('audioVerdict').textContent = result.verdict; $('audioScore').textContent = Number(result.anomaly_score).toFixed(3); $('audioModel').textContent = result.model_version; setStatus('声音辅助检测完成，结果未自动创建任务。', 'success'); } catch (error) { setStatus(error.message, 'error'); } }; reader.readAsDataURL(file);
  });
}

document.addEventListener('click', async (event) => {
  const view = event.target.closest('[data-view]');
  if (view) { showView(view.dataset.view); return; }
  const action = event.target.closest('[data-action]')?.dataset.action;
  if (action === 'refresh' || action === 'refresh-trace') { await refreshHealth(); if (state.taskId) await loadTrace(); setStatus('页面状态已刷新。', 'success'); }
  if (action === 'refresh-orders') await loadOrders();
  if (action === 'refresh-resources') await loadResources();
  if (action === 'reset-order-filters') { state.orderFilter = ''; state.pumpFilter = ''; $('orderStatusFilter').value = ''; $('orderPumpFilter').value = ''; renderOrders(); }
  const orderStatus = event.target.closest('[data-order-status]');
  if (orderStatus) { state.orderFilter = orderStatus.dataset.orderStatus; $('orderStatusFilter').value = state.orderFilter; renderOrders(); return; }
  const orderId = event.target.closest('[data-order-id]')?.dataset.orderId;
  if (orderId && !event.target.closest('[data-order-action]')) { renderOrderDetail(orderId); return; }
  const orderAction = event.target.closest('[data-order-action]');
  if (orderAction) { await updateOrderStatus(orderAction.dataset.orderId, orderAction.dataset.orderAction); return; }
  const resourceTab = event.target.closest('[data-resource-tab]');
  if (resourceTab) { state.resourceTab = resourceTab.dataset.resourceTab; document.querySelectorAll('.resource-tab').forEach((item) => item.classList.toggle('active', item === resourceTab)); renderResources(); return; }
  const auditFilter = event.target.closest('[data-audit-filter]');
  if (auditFilter) { state.auditFilter = auditFilter.dataset.auditFilter; document.querySelectorAll('.audit-filter').forEach((item) => item.classList.toggle('active', item === auditFilter)); renderAudit(); }
});

document.addEventListener('DOMContentLoaded', async () => {
  $('orderPumpFilter').addEventListener('change', (event) => { state.pumpFilter = event.target.value; renderOrders(); });
  $('orderStatusFilter').addEventListener('change', (event) => { state.orderFilter = event.target.value; renderOrders(); });
  $('chatForm').addEventListener('submit', (event) => { event.preventDefault(); const text = $('messageInput').value; $('messageInput').value = ''; sendMessage(text); });
  $('messageInput').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('chatForm').requestSubmit(); } });
  document.querySelectorAll('[data-prompt]').forEach((button) => button.addEventListener('click', () => { $('messageInput').value = button.dataset.prompt; $('messageInput').focus(); }));
  $('confirmButton').addEventListener('click', confirmTask); $('planConfirmButton').addEventListener('click', confirmTask);
  $('cancelTaskButton').addEventListener('click', cancelTask); $('planCancelButton').addEventListener('click', cancelTask);
  $('reviseButton').addEventListener('click', reviseTask); $('planReviseButton').addEventListener('click', reviseTask);
  window.addEventListener('hashchange', () => showView(location.hash.replace('#/', '') || 'home', false));
  initAudio();
  await Promise.all([refreshHealth(), loadBootstrap()]);
  renderMessagesFromState(); renderOrders(); renderResources(); renderPlanView();
  showView(location.hash.replace('#/', '') || 'home', false);
});
