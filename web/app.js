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
const statusLabels = { awaiting_input: '待补充', ready_for_plan: '待确认', proposed: '待确认', completed: '已完成', cancelled: '已取消', failed: '失败', replan_required: '需重新安排', discovery_failed: '发现失败', confirmed: '待处理', in_progress: '处理中', pending: '待处理' };
const statusClass = (status) => ['completed', 'success'].includes(status) ? 'success' : ['cancelled', 'failed', 'discovery_failed'].includes(status) ? 'error' : ['ready_for_plan', 'proposed', 'confirmed', 'in_progress', 'awaiting_input', 'pending', 'replan_required'].includes(status) ? 'pending' : 'neutral';
const api = async (path, options = {}) => {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }, ...options });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.detail?.message || data.detail || `请求失败（${response.status}）`);
  return data;
};
const formatDate = (value) => {
  if (!value) return '—';
  if (!/T.*(?:Z|[+-]\d{2}:?\d{2})$/.test(String(value))) return String(value).replace('T', ' ');
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  const parts = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hourCycle:'h23'}).formatToParts(parsed);
  const get = (type) => parts.find((part) => part.type === type).value;
  return `${get('year')}-${get('month')}-${get('day')} ${get('hour')}:${get('minute')}:${get('second')}`;
};
const formatStatus = (value) => statusLabels[value] || value || '—';
const humanLabels = {pump_inspection:'泵体检查',electrical_inspection:'电气检查',part:'配件',tool:'工具',leader:'协调主控',resource:'资源服务',workorder:'工单服务',resource_partner:'资源服务',work_order_partner:'工单服务',request_created:'登记检查需求',request_updated:'更新检查时间',plan_generated:'生成检查方案',plan_replanned:'重新协调资源',resource_reserved:'预留资源',resources_released:'释放资源',work_order_created:'创建工单',work_order_cancelled:'取消工单',work_order_status_updated:'更新工单进度',work_order_resources_closed:'结算工单资源',query_resources:'查询资源',reserve_resources:'预留资源',release_resources:'释放资源',create_work_order:'创建工单',update_work_order:'更新工单',cancel_work_order:'取消工单',completed:'已完成',failed:'失败',accepted:'已接收',working:'处理中'};
const humanLabel = (value) => humanLabels[value] || value || '—';

const setStatus = (message, kind = '') => { const node = $('statusBar'); if (!node) return; node.textContent = message || ''; node.className = `status-bar ${kind}`; };
function updateActionAvailability() {
  const terminal = ['completed', 'cancelled'].includes(state.status);
  ['confirmButton', 'planConfirmButton'].forEach((id) => { if ($(id)) $(id).disabled = state.busy || !state.plan || state.status === 'cancelled'; });
  ['reviseButton', 'planReviseButton'].forEach((id) => { if ($(id)) $(id).disabled = state.busy || !state.plan || terminal; });
  ['cancelTaskButton', 'planCancelButton'].forEach((id) => { if ($(id)) $(id).disabled = state.busy || !state.taskId || terminal; });
  if ($('cancelTaskButton')) $('cancelTaskButton').hidden = !state.taskId || terminal;
}
const setBusy = (busy) => {
  state.busy = busy;
  $('conversationPanel')?.classList.toggle('is-busy', busy);
  if ($('chatActivity')) $('chatActivity').textContent = busy ? '正在处理…' : '';
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
  node.innerHTML = `<span class="avatar ${role === 'assistant' ? 'leader' : ''}">${role === 'user' ? '你' : '工'}</span><div><strong>${role === 'user' ? '你' : '工维联'}</strong><p>${esc(text)}</p><time>${new Intl.DateTimeFormat('zh-CN', { hour: '2-digit', minute: '2-digit' }).format(new Date())}</time></div>`;
  list.appendChild(node);
  list.scrollTop = list.scrollHeight;
}

function renderMessagesFromState() {
  const list = $('messageList');
  if (!list) return;
  if (!state.messages.length) {
    list.innerHTML = '<div class="empty-conversation"><strong>今天需要检查什么？</strong><p>告诉我设备、异常和检查时间。<br>我会补齐信息、协调资源，再由你确认安排。</p></div>';
    return;
  }
  list.innerHTML = '';
  state.messages.forEach((message) => {
    const node = document.createElement('div');
    node.className = `message ${message.role}`;
    node.innerHTML = `<span class="avatar ${message.role === 'assistant' ? 'leader' : ''}">${message.role === 'user' ? '你' : '工'}</span><div><strong>${message.role === 'user' ? '你' : '工维联'}</strong><p>${esc(message.text)}</p><time>${formatDate(message.created_at).slice(11, 16)}</time></div>`;
    list.appendChild(node);
  });
}

function updateStepper(status) {
  const index = {awaiting_input:0,ready_for_plan:1,proposed:2,completed:3,replan_required:1,discovery_failed:1,cancelled:-1}[status] ?? 0;
  document.querySelectorAll('#stepper .step').forEach((step, idx) => { step.classList.toggle('active', idx < index); step.classList.toggle('current', idx === index && !!state.taskId); });
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
    inventory: (plan?.inventory || []).map((item) => typeof item === 'string' ? item : `${item.name || item.id} ${item.quantity || item.required_qty || 1}${item.unit || '件'}`).join('、') || '未记录',
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
  box.hidden = !!state.plan || !request;
  if (!request) {
    box.innerHTML = '<div><span>设备</span><strong>等待输入</strong></div><div><span>问题描述</span><strong>—</strong></div><div><span>计划时间</span><strong>—</strong></div><div><span>预计时长</span><strong>—</strong></div><div><span>下一步</span><strong>发送异常描述</strong></div>';
    return;
  }
  const values = planValues(state.plan || { request });
  box.innerHTML = `<div><span>设备</span><strong>${esc(values.device)}</strong></div><div><span>异常</span><strong>${esc(values.description)}</strong></div><div><span>检查时间</span><strong>${esc(values.window)}</strong></div><div><span>预计时长</span><strong>${esc(values.duration)}</strong></div><div><span>技能</span><strong>${esc(humanLabel(request.required_skill || '待补充'))}</strong></div>`;
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
    setStatus('正在整理检查要求…');
    const result = await api(`/api/conversations/${state.sessionId}/messages`, { method: 'POST', body: JSON.stringify({ text }) });
    state.messageId = result.message_id || state.messageId;
    state.status = result.plan ? 'proposed' : result.status;
    state.request = result.request || state.request;
    if (result.plan) state.plan = result.plan;
    else if (['awaiting_input', 'replan_required', 'discovery_failed'].includes(result.status)) { state.plan = null; $('planContent').hidden = true; $('planEmpty').hidden = false; }
    updateTechnical(result);
    $('parserMode').textContent = result.parser_mode === 'deterministic_fallback' ? '规则解析' : '模型解析';
    updateStepper(state.status);
    if (result.question) {
      addMessage('assistant', result.question);
      $('missingBox').hidden = false;
      $('missingText').textContent = result.question;
      setStatus('还需要补充信息，确认前不会预留资源。', 'warning');
    } else if (result.plan) {
      addMessage('assistant', '人员和物品已查询，检查方案已准备好。请查看方案并确认安排。');
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
    state.selectedOrderId = result.work_order?.id || state.selectedOrderId;
    $('resultText').textContent = `${result.work_order?.number || '工单已创建'} · ${formatStatus(result.work_order?.status || 'confirmed')}`;
    addMessage('assistant', `安排已确认，工单 ${result.work_order?.number || ''} 已创建。可在工单中心查看人员、物品和处理状态。`);
    setStatus(result.idempotent ? '已找到同一工单，没有重复创建。' : '工单已创建，人员和物品已预留。', 'success');
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
  setBusy(true);
  try {
    const result = await api(`/api/tasks/${state.taskId}/cancel`, { method: 'POST', body: '{}' });
    state.status = 'cancelled';
    $('resultBox').hidden = true;
    updateTechnical(result);
    updateStepper('cancelled');
    addMessage('assistant', '任务已取消，未继续执行。');
    setStatus('任务已取消。', 'warning');
    renderCurrentTask();
    updateAgents();
    renderPlanView();
  } catch (error) { setStatus(error.message, 'error'); }
  finally { setBusy(false); }
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
  } catch (error) { $('orderListMeta').textContent = `加载失败：${error.message}`; setStatus(`工单暂时无法读取：${error.message}`, 'error'); }
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
  const pumpId = request?.pump_id || request?.pump?.id;
  return request?.pump?.name || (state.bootstrap.pumps || []).find((pump) => pump.id === pumpId)?.name || pumpId || '—';
}

function workerLabel(order) {
  const fromPlan = order.plan?.worker?.name || order.plan?.worker_id;
  if (fromPlan) return fromPlan;
  const reservation = (order.reservations || []).find((item) => item.resource_type === 'worker');
  const worker = (state.bootstrap.workers || []).find((item) => item.id === reservation?.resource_id);
  return worker?.name || reservation?.resource_id || '—';
}

function renderOrders() {
  const taskOrderId = state.plan?.work_order_id || state.plan?.work_order?.id;
  const taskOrder = taskOrderId && state.orders.find((order) => order.id === taskOrderId);
  if (taskOrder) $('resultText').textContent = `${taskOrder.number} · ${formatStatus(taskOrder.status)}`;
  const rows = filteredOrders();
  const counts = state.orders.reduce((acc, order) => { acc[order.status] = (acc[order.status] || 0) + 1; return acc; }, {});
  const filterList = $('orderFilterList');
  if (filterList) filterList.innerHTML = `<button class="filter-row ${!state.orderFilter ? 'selected' : ''}" type="button" data-order-status=""><span>全部工单</span><b>${state.orders.length}</b></button>${[['confirmed', '待处理'], ['in_progress', '处理中'], ['completed', '已完成'], ['cancelled', '已取消']].map(([key, label]) => `<button class="filter-row ${state.orderFilter === key ? 'selected' : ''}" type="button" data-order-status="${key}"><span>${label}</span><b>${counts[key] || 0}</b></button>`).join('')}`;
  if ($('orderListTitle')) $('orderListTitle').textContent = state.orderFilter ? formatStatus(state.orderFilter) : '全部工单';
  if ($('orderListMeta')) $('orderListMeta').textContent = `共 ${rows.length} 张工单 · 从后端实时读取`;
  const body = $('orderTableBody');
  if (!body) return;
  if (!rows.length) {
    state.selectedOrderId = null;
    body.innerHTML = '<tr><td colspan="6"><div class="table-empty">当前筛选没有工单</div></td></tr>';
    $('orderDetailTitle').textContent = '工单详情'; setBadge($('orderDetailBadge'), null);
    $('orderDetailContent').innerHTML = '<div class="empty-state compact-empty"><strong>没有符合筛选的工单</strong><p>调整状态或设备筛选后查看。</p></div>';
    return;
  }
  if (!rows.some((order) => order.id === state.selectedOrderId)) state.selectedOrderId = rows[0].id;
  body.innerHTML = rows.map((order) => {
    const request = order.request || {};
    const plan = order.plan || {};
    const worker = workerLabel(order);
    const device = pumpLabel(request);
    const time = [request.work_date, request.start_time].filter(Boolean).join(' ');
    return `<tr class="${state.selectedOrderId === order.id ? 'selected' : ''}" data-order-id="${esc(order.id)}"><td><button class="link-button" type="button" data-order-id="${esc(order.id)}">${esc(order.number)}</button></td><td>${esc(device)}</td><td>${esc(time || '—')}</td><td>${esc(worker)}</td><td><span class="status-badge ${statusClass(order.status)}">${esc(formatStatus(order.status))}</span></td><td><button class="icon-button" type="button" data-order-id="${esc(order.id)}" aria-label="查看工单 ${esc(order.number)} 详情">→</button></td></tr>`;
  }).join('');
  renderOrderDetail(state.selectedOrderId);
}

function renderOrderDetail(orderId) {
  const order = state.orders.find((item) => item.id === orderId);
  if (!order) return;
  state.selectedOrderId = orderId;
  document.querySelectorAll('#orderTableBody tr[data-order-id]').forEach((row) => row.classList.toggle('selected', row.dataset.orderId === orderId));
  const request = order.request || {};
  const plan = order.plan || {};
  const worker = workerLabel(order);
  $('orderDetailTitle').textContent = order.number || '工单详情';
  setBadge($('orderDetailBadge'), order.status);
  const assigned = (order.reservations || []).filter((item) => item.resource_type !== 'worker').map((item) => {
    const resource = (state.bootstrap.inventory || []).find((entry) => entry.id === item.resource_id);
    return `${resource?.name || item.resource_id} ${item.quantity || 1}${resource?.unit || '件'}`;
  });
  $('orderDetailContent').innerHTML = `<dl class="detail-list"><div><dt>设备</dt><dd>${esc(pumpLabel(request))}</dd></div><div><dt>异常描述</dt><dd>${esc(request.description || '—')}</dd></div><div><dt>检查时间</dt><dd>${esc([request.work_date, request.start_time].filter(Boolean).join(' ') || '—')}</dd></div><div><dt>预计时长</dt><dd>${request.duration_minutes ? `${esc(request.duration_minutes)} 分钟` : '—'}</dd></div><div><dt>创建时间</dt><dd>${esc(formatDate(order.created_at))}</dd></div></dl><div class="detail-section"><h3>分配资源</h3><p class="assigned-resource">${esc(worker)}${request.required_skill ? ` · ${esc(humanLabel(request.required_skill))}` : ''}</p>${assigned.map((item) => `<p class="assigned-resource">${esc(item)}</p>`).join('')}</div><div class="order-progress"><strong>处理进度</strong><div class="progress-line"><span class="done">工单已创建</span>${order.status === 'cancelled' ? '<span class="done">工单已取消</span>' : `<span class="${order.status === 'in_progress' || order.status === 'completed' ? 'done' : ''}">处理中</span><span class="${order.status === 'completed' ? 'done' : ''}">处理完成</span>`}</div></div><div class="detail-actions">${['confirmed','pending'].includes(order.status) ? `<button class="button primary" type="button" data-order-action="in_progress" data-order-id="${esc(order.id)}">开始处理</button>` : ''}${!['cancelled','completed'].includes(order.status) ? `<button class="button danger" type="button" data-order-action="cancelled" data-order-id="${esc(order.id)}">取消工单</button>` : ''}${order.status === 'in_progress' ? `<button class="button primary" type="button" data-order-action="completed" data-order-id="${esc(order.id)}">标记已完成</button>` : ''}</div>`;
}

async function updateOrderStatus(orderId, action) {
  try {
    const result = action === 'cancelled' ? await api(`/api/work-orders/${orderId}/cancel`, { method: 'POST' }) : await api(`/api/work-orders/${orderId}/status`, { method: 'POST', body: JSON.stringify({ status: action }) });
    state.orders = state.orders.map((order) => order.id === orderId ? { ...order, ...result, request: order.request, plan: order.plan } : order);
    renderOrders();
    setStatus(`工单已更新为“${formatStatus(action)}”。`, 'success');
    try {
      const resources = await api('/api/bootstrap');
      state.bootstrap.inventory = resources.inventory || [];
      state.bootstrap.workers = resources.workers || [];
      renderResources();
    } catch (error) {
      setStatus(`工单已更新，资源数据刷新失败：${error.message}。请刷新资源记录。`, 'error');
    }
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
    const values = planValues(plan);
    proposal.innerHTML = plan ? `<div class="proposal-device">${esc(pumpLabel(plan.request) || values.device)}</div><p class="proposal-description">${esc(values.description)}</p><div class="proposal-window"><strong>${esc(values.window)}</strong><span>预计 ${esc(values.duration)}</span></div><section class="proposal-section"><h3>检查安排</h3><dl><div><dt>检查技能</dt><dd>${esc(humanLabel(plan.request?.required_skill || 'pump_inspection'))}</dd></div><div><dt>检查人员</dt><dd>${esc(values.worker)}</dd></div></dl></section><section class="proposal-section"><h3>工具与配件</h3><div class="table-wrap"><table><thead><tr><th>物品名称</th><th>本次用量</th></tr></thead><tbody>${(plan.inventory || []).map((item) => `<tr><td>${esc(typeof item === 'string' ? item : item.name || item.id)}</td><td>${esc(item.quantity || item.required_qty || 1)} ${esc(item.unit || '件')}</td></tr>`).join('')}</tbody></table></div></section>` : '<div class="empty-state"><strong>还没有可确认的方案</strong><p>返回对话，补齐设备、时间和检查要求。</p><button class="text-button" type="button" data-view="home">返回主协作 →</button></div>';
    if ($('proposalExplanation')) $('proposalExplanation').textContent = state.status === 'completed' ? '方案已确认，工单已创建。' : state.status === 'cancelled' ? '本次安排已取消。' : plan ? '资源查询已完成，尚未预留。' : '';
    if ($('confirmationHint')) $('confirmationHint').textContent = state.status === 'completed' ? '查看已有工单，重复确认不会新增工单。' : state.status === 'cancelled' ? '本次安排已取消，可新建检查任务。' : '确认后预留人员和物品，并创建检查工单。';
    if ($('planConfirmButton')) $('planConfirmButton').textContent = state.status === 'completed' ? '查看已有工单' : '确认并创建工单';
  }
  updateActionAvailability();
  const side = $('planSideFacts');
  if (side) { const values = planValues(plan); const resourceStatus = state.status === 'completed' ? '已确认并预留' : state.status === 'cancelled' ? '已取消' : state.status === 'replan_required' ? '有冲突，需重新安排' : plan ? '已查询，待确认' : '等待查询'; const nextStep = state.status === 'completed' ? '查看工单' : state.status === 'cancelled' ? '新建检查任务' : state.status === 'replan_required' ? '修改时间后重新安排' : plan ? '确认并创建工单' : '等待方案'; side.innerHTML = `<div><span>设备</span><strong>${esc(values.device)}</strong></div><div><span>计划时间</span><strong>${esc(values.window)}</strong></div><div><span>资源状态</span><strong>${esc(resourceStatus)}</strong></div><div><span>下一步</span><strong>${esc(nextStep)}</strong></div>`; }
  updateStepper(state.status);
  const chain = $('planAgentChain');
  if (chain) chain.innerHTML = `<div class="agent-node"><span class="agent-icon user">你</span><div><strong>用户 / 叮当</strong><small>提出检查需求</small></div><b>已输入</b></div><span class="chain-arrow">→</span><div class="agent-node"><span class="agent-icon leader">L</span><div><strong>工维联 Leader</strong><small>理解 · 规划 · 汇总</small></div><b>${state.request ? '已处理' : '等待'}</b></div><span class="chain-arrow">→</span><div class="agent-node"><span class="agent-icon resource">R</span><div><strong>资源协调 Partner</strong><small>人员 · 技能 · 库存</small></div><b>${plan ? '已返回' : '等待'}</b></div><span class="chain-arrow">→</span><div class="agent-node"><span class="agent-icon order">W</span><div><strong>工单处理 Partner</strong><small>创建 · 生命周期</small></div><b>${state.status === 'completed' ? '已完成' : '等待确认'}</b></div>`;
}

async function loadResources() {
  try {
    await loadBootstrap();
    renderResources();
    if (state.taskId) await loadTrace();
    else { state.timeline = []; renderTimeline(); }
    state.calls = (await api('/api/aip-calls')).filter(callBelongsToCurrentTask);
    renderAudit();
  } catch (error) { setStatus(`协作记录暂时无法读取：${error.message}`, 'error'); }
}

async function loadTrace() {
  const taskId = state.taskId;
  if (!taskId) return;
  try {
    const result = await api(`/api/tasks/${taskId}/trace`);
    if (state.taskId !== taskId) return;
    state.timeline = result.timeline || [];
    if (!state.messages.length && result.conversation?.messages?.length) state.messages = result.conversation.messages.map((message) => ({ role: message.role === 'user' ? 'user' : 'assistant', text: message.content, created_at: message.created_at }));
    state.request = result.conversation?.request || state.request;
    renderTimeline();
    renderMessagesFromState();
  } catch (error) { if (state.taskId === taskId) setStatus(`任务轨迹读取失败：${error.message}`, 'error'); }
}

function renderResources() {
  const list = $('resourceList');
  if (!list) return;
  if (state.resourceTab === 'inventory') {
    const items = state.bootstrap.inventory || [];
    list.innerHTML = items.length ? `<table><thead><tr><th>物品</th><th>类别</th><th>剩余 / 总量</th><th>手动调整总量</th></tr></thead><tbody>${items.map((item) => `<tr><td class="resource-name">${esc(item.name)}</td><td>${esc(humanLabel(item.category))}</td><td><strong>${esc(item.available_qty)}</strong> / ${esc(item.total_qty)} ${esc(item.unit || '件')}</td><td><div class="inventory-adjust" data-inventory-id="${esc(item.id)}"><button class="quantity-button" type="button" data-inventory-id="${esc(item.id)}" data-inventory-delta="-1" aria-label="减少${esc(item.name)}总量">−</button><span class="available-count" aria-label="可用数量" aria-live="polite">${esc(item.available_qty)}</span><span class="quantity-divider">/</span><input class="quantity-input" type="number" min="0" step="1" value="${esc(item.total_qty)}" data-inventory-total-input="${esc(item.id)}" aria-label="设置${esc(item.name)}总量"><button class="quantity-button" type="button" data-inventory-id="${esc(item.id)}" data-inventory-delta="1" aria-label="增加${esc(item.name)}总量">＋</button><button class="quantity-set" type="button" data-inventory-id="${esc(item.id)}" data-inventory-set aria-label="保存${esc(item.name)}总量">保存</button></div></td></tr>`).join('')}</tbody></table>` : '<div class="empty-state"><strong>暂无库存记录</strong><p>当前数据没有可展示的库存。</p></div>';
  } else {
    const workers = state.bootstrap.workers || [];
    list.innerHTML = workers.length ? `<table><thead><tr><th>人员</th><th>技能</th><th>已记录安排</th></tr></thead><tbody>${workers.map((worker) => {
      const schedules = state.orders.filter((order) => order.status !== 'cancelled' && (order.reservations || []).some((item) => item.resource_type === 'worker' && item.resource_id === worker.id && item.status !== 'released')).map((order) => [order.request?.work_date, [order.request?.start_time,order.request?.end_time].filter(Boolean).join('–')].filter(Boolean).join(' '));
      return `<tr><td class="resource-name">${esc(worker.name)}</td><td><div class="skill-list">${String(worker.skills || '').split(',').filter(Boolean).map((skill) => `<em>${esc(humanLabel(skill))}</em>`).join('、') || '<em>技能未记录</em>'}</div></td><td>${schedules.length ? schedules.map((time) => `<span class="schedule-line">${esc(time)}</span>`).join('') : '<span class="schedule-line empty">暂无已记录安排</span>'}</td></tr>`;
    }).join('')}</tbody></table>` : '<div class="empty-state"><strong>暂无人员记录</strong><p>当前数据没有可展示的人员。</p></div>';
  }
}

async function adjustInventory(itemId, delta) {
  try {
    const result = await api(`/api/resources/inventory/${encodeURIComponent(itemId)}/adjust`, { method: 'POST', body: JSON.stringify({ delta }) });
    const item = result.item;
    const index = (state.bootstrap.inventory || []).findIndex((entry) => entry.id === item.id);
    if (index >= 0) state.bootstrap.inventory[index] = item;
    renderResources();
    setStatus(`${item.name} 数量已${delta > 0 ? '增加' : '减少'} ${Math.abs(delta)}。`, 'success');
  } catch (error) {
    setStatus(error.message, 'error');
  }
}

async function setInventoryTotal(itemId, total) {
  const item = (state.bootstrap.inventory || []).find((entry) => entry.id === itemId);
  if (!item) return;
  if (!Number.isInteger(total) || total < 0) {
    setStatus('总量必须是大于等于 0 的整数。', 'error');
    return;
  }
  const delta = total - Number(item.total_qty);
  if (delta === 0) {
    setStatus(`${item.name} 总量没有变化。`);
    return;
  }
  await adjustInventory(itemId, delta);
}

function renderTimeline() {
  const list = $('timelineList');
  if (!list) return;
  if (!$('timelineMeta')) return;
  $('timelineMeta').textContent = state.timeline.length ? `${state.timeline.length} 条真实事件` : '选择任务后显示真实事件';
  if (!state.timeline.length) { list.innerHTML = '<div class="empty-state compact-empty"><strong>暂无可显示的任务轨迹</strong><p>完成一次对话后，这里会显示信息补充、资源查询和工单处理过程。</p></div>'; return; }
  list.innerHTML = state.timeline.map((event) => `<div class="timeline-item"><time>${esc(formatDate(event.created_at).slice(11, 16))}</time><span class="timeline-dot"></span><div><strong>${esc(humanLabel(event.event_type || '业务事件'))}</strong><p>${esc(humanLabel(event.actor || '系统'))}</p><details><summary>技术详情</summary><pre>${esc(JSON.stringify(event.details || {}, null, 2))}</pre></details></div><span class="status-badge success">已记录</span></div>`).join('');
}

function callBelongsToCurrentTask(call) {
  const task = call.task_id || call.taskId || call.parent_task_id;
  return !!state.taskId && !!task && (task === state.taskId || String(task).startsWith(`${state.taskId}:`));
}

function renderAudit() {
  const rows = [];
  if (state.sessionId && state.messages.length) rows.push({kind:'session',title:'本次检查对话',detail:`${state.messages.length} 条消息`,created_at:state.messages[0].created_at,status:'已记录'});
  state.messages.slice(-12).forEach((message) => rows.push({ kind: 'message', title: message.role === 'user' ? '用户输入' : '工维联回复', detail: message.text, created_at: message.created_at, status: '已记录' }));
  state.timeline.slice(-12).forEach((event) => rows.push({ kind: event.event_type?.includes('partner') ? 'partner' : 'task', title: event.event_type || '业务事件', detail: event.actor || '系统', created_at: event.created_at, status: '已记录' }));
  state.calls.filter(callBelongsToCurrentTask).slice(-12).forEach((call) => rows.push({ kind: 'partner', title: call.action || call.method || call.event || '协作调用', detail: call.partner || call.agent || '业务服务', created_at: call.created_at || call.timestamp || call.time_utc, status: call.status || '已记录' }));
  const filtered = rows.filter((row) => state.auditFilter === 'all' || row.kind === state.auditFilter);
  const list = $('auditList');
  if (!list) return;
  list.innerHTML = filtered.length ? filtered.sort((a, b) => String(b.created_at).localeCompare(String(a.created_at))).map((row) => `<article class="audit-row"><time>${esc(formatDate(row.created_at).slice(11, 16))}</time><span class="audit-kind ${esc(row.kind)}">${esc({message:'消息',task:'任务',partner:'协作',session:'会话'}[row.kind] || row.kind)}</span><div><strong>${esc(humanLabel(row.title))}</strong><p>${esc(humanLabel(row.detail))}</p></div><span class="status-badge ${row.status === 'failed' ? 'error' : 'neutral'}">${esc(humanLabel(row.status))}</span></article>`).join('') : '<div class="empty-state compact-empty"><strong>暂无调用记录</strong><p>完成一次任务后，这里会汇总消息、任务和协作调用。</p></div>';
  if ($('auditRaw')) $('auditRaw').textContent = JSON.stringify({ timeline: state.timeline, calls: state.calls }, null, 2);
}

async function refreshHealth() {
  try {
    const health = await api('/health');
    const online = health.status === 'ok';
    $('leaderHealth').textContent = online ? '在线' : '待处理';
    $('leaderHealthDot').classList.toggle('good', online);
    $('serviceHealthLabel').textContent = online ? '业务服务可用' : '业务服务待处理';
    $('serviceHealthDot').classList.toggle('good', online);
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
    $('serviceHealthLabel').textContent = '业务服务连接失败';
    $('serviceHealthDot').classList.remove('good');
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
  if (action === 'open-audio') { $('audioDrawer').open = true; $('audioFile').focus(); return; }
  if (action === 'new-conversation') {
    if (state.busy) return;
    if (state.taskId && !['completed','cancelled'].includes(state.status)) { showView('home'); setStatus('当前检查尚未结束，请先确认或取消安排，再新建任务。', 'warning'); return; }
    Object.assign(state, {sessionId:null,taskId:null,messageId:null,request:null,plan:null,status:'awaiting_input',messages:[],timeline:[],calls:[],discovery:null});
    $('planContent').hidden = true; $('planEmpty').hidden = false; $('missingBox').hidden = true; $('resultBox').hidden = true;
    $('messageInput').value = ''; $('techPayload').textContent = '发送消息后显示结构化响应。';
    renderMessagesFromState(); renderCurrentTask(); renderPlanView(); renderTimeline(); renderAudit(); updateTechnical(); showView('home'); setStatus('可以开始新的检查任务。'); $('messageInput').focus(); return;
  }
  if (action === 'refresh' || action === 'refresh-trace') { await refreshHealth(); if (state.taskId) await loadTrace(); }
  if (action === 'refresh-orders') await loadOrders();
  if (action === 'refresh-resources') await loadResources();
  if (action === 'reset-order-filters') { state.orderFilter = ''; state.pumpFilter = ''; $('orderStatusFilter').value = ''; $('orderPumpFilter').value = ''; renderOrders(); }
  const orderStatus = event.target.closest('[data-order-status]');
  if (orderStatus) { state.orderFilter = orderStatus.dataset.orderStatus; $('orderStatusFilter').value = state.orderFilter; renderOrders(); return; }
  const orderId = event.target.closest('[data-order-id]')?.dataset.orderId;
  if (orderId && !event.target.closest('[data-order-action]')) { renderOrderDetail(orderId); return; }
  const orderAction = event.target.closest('[data-order-action]');
  if (orderAction) { await updateOrderStatus(orderAction.dataset.orderId, orderAction.dataset.orderAction); return; }
  const inventorySet = event.target.closest('[data-inventory-set]');
  if (inventorySet) {
    const wrapper = inventorySet.closest('.inventory-adjust');
    const input = wrapper?.querySelector('[data-inventory-total-input]');
    await setInventoryTotal(inventorySet.dataset.inventoryId, Number(input?.value));
    return;
  }
  const inventoryAdjustment = event.target.closest('[data-inventory-id]');
  if (inventoryAdjustment) { await adjustInventory(inventoryAdjustment.dataset.inventoryId, Number(inventoryAdjustment.dataset.inventoryDelta)); return; }
  const resourceTab = event.target.closest('[data-resource-tab]');
  if (resourceTab) { state.resourceTab = resourceTab.dataset.resourceTab; document.querySelectorAll('.resource-tab').forEach((item) => { item.classList.toggle('active', item === resourceTab); item.setAttribute('aria-selected', String(item === resourceTab)); item.tabIndex = item === resourceTab ? 0 : -1; }); $('resourceList').setAttribute('aria-labelledby', resourceTab.id); renderResources(); return; }
  const recordTab = event.target.closest('[data-record-tab]');
  if (recordTab) { document.querySelectorAll('.record-tab').forEach((item) => { item.classList.toggle('active', item === recordTab); item.setAttribute('aria-selected', String(item === recordTab)); item.tabIndex = item === recordTab ? 0 : -1; }); $('businessRecords').hidden = recordTab.dataset.recordTab !== 'business'; $('callRecords').hidden = recordTab.dataset.recordTab !== 'calls'; return; }
  const auditFilter = event.target.closest('[data-audit-filter]');
  if (auditFilter) { state.auditFilter = auditFilter.dataset.auditFilter; document.querySelectorAll('.audit-filter').forEach((item) => { item.classList.toggle('active', item === auditFilter); item.setAttribute('aria-pressed', String(item === auditFilter)); }); renderAudit(); }
});

document.addEventListener('keydown', (event) => {
  const tab = event.target.closest?.('[role="tab"]');
  if (!tab || !['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
  const tabs = Array.from(tab.closest('[role="tablist"]').querySelectorAll('[role="tab"]'));
  const index = tabs.indexOf(tab);
  const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
  event.preventDefault(); tabs[next].click(); tabs[next].focus();
});

document.addEventListener('DOMContentLoaded', async () => {
  $('orderPumpFilter').addEventListener('change', (event) => { state.pumpFilter = event.target.value; renderOrders(); });
  $('orderStatusFilter').addEventListener('change', (event) => { state.orderFilter = event.target.value; renderOrders(); });
  $('chatForm').addEventListener('submit', (event) => { event.preventDefault(); const text = $('messageInput').value; $('messageInput').value = ''; sendMessage(text); });
  $('messageInput').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('chatForm').requestSubmit(); } });
  document.querySelectorAll('[data-prompt]').forEach((button) => button.addEventListener('click', () => { $('messageInput').value = button.dataset.prompt; $('messageInput').focus(); }));
  $('confirmButton').addEventListener('click', confirmTask); $('planConfirmButton').addEventListener('click', () => state.status === 'completed' ? showView('orders') : confirmTask());
  $('cancelTaskButton').addEventListener('click', cancelTask); $('planCancelButton').addEventListener('click', cancelTask);
  $('reviseButton').addEventListener('click', reviseTask); $('planReviseButton').addEventListener('click', reviseTask);
  window.addEventListener('hashchange', () => showView(location.hash.replace('#/', '') || 'home', false));
  initAudio();
  await Promise.all([refreshHealth(), loadBootstrap()]);
  renderMessagesFromState(); renderOrders(); renderResources(); renderCurrentTask(); renderPlanView();
  showView(location.hash.replace('#/', '') || 'home', false);
});
