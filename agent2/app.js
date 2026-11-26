/**
 * CCagent - 个人任务分诊工具前端逻辑 (v3 严谨稳定版)
 * 纯原生 JS，基于 REST API 落库，支持状态持久化、原位编辑、折叠展开、拖拽/领域改动可撤销与 Markdown/JSON 导出
 */

const AppState = {
  tasks: [],
  context: '',
  advisoryMap: {}, // B1: 缓存 expert_id -> name
  correctionsEnabled: true,
  activeCorrections: [],
  newlyCreatedIds: new Set(),
  apiConfig: {
    hasKey: false,
    model: 'gemini-3.5-flash-lite',
    baseUrl: 'https://generativelanguage.googleapis.com',
    fallback: true
  },
  // B5/B6 撤销状态机
  undoState: null,
  undoTimer: null
};

const DOMAIN_NAMES = {
  work: '工作',
  life: '生活',
  study: '学习',
  play: '娱乐'
};

const QUADRANT_NAMES = {
  q1: 'Q1',
  q2: 'Q2',
  q3: 'Q3',
  q4: 'Q4',
  candidate: '待确认'
};

// ============================================================================
// 初始化入口
// ============================================================================
document.addEventListener('DOMContentLoaded', async () => {
  initEventListeners();
  await loadAdvisoryLibrary(); // B1: 先缓存智囊库
  await loadConfig();
  await loadSettings();
  await loadContext();
  await syncTasksFromServer();
});

// ============================================================================
// API 数据同步与智囊缓存
// ============================================================================
async function loadAdvisoryLibrary() {
  try {
    const res = await fetch('api/advisory');
    if (res.ok) {
      const data = await res.json();
      const items = data.advisory || [];
      items.forEach(it => {
        if (it.id) {
          AppState.advisoryMap[it.id] = it.name;
        }
      });
    }
  } catch (e) {
    console.warn('获取智囊库失败', e);
  }
}

const PROVIDER_PRESETS = {
  gemini: { label: 'Google Gemini', model: 'gemini-3.5-flash-lite', baseUrl: 'https://generativelanguage.googleapis.com' },
  xai: { label: 'Grok (xAI)', model: 'grok-3-mini-fast', baseUrl: 'https://api.x.ai/v1' },
  deepseek: { label: 'DeepSeek', model: 'deepseek-flash', baseUrl: 'https://api.deepseek.com' }
};

async function loadConfig() {
  try {
    const res = await fetch('api/config');
    if (res.ok) {
      const data = await res.json();
      const provider = data.provider || 'gemini';
      const preset = PROVIDER_PRESETS[provider] || PROVIDER_PRESETS.gemini;
      AppState.apiConfig.provider = provider;
      AppState.apiConfig.hasKey = data.has_key;
      AppState.apiConfig.model = data.model || preset.model;
      AppState.apiConfig.baseUrl = data.base_url || preset.baseUrl;

      const provSelect = document.getElementById('cfg-provider');
      if (provSelect) {
        provSelect.value = provider;
        if (!provSelect.dataset.bound) {
          provSelect.dataset.bound = '1';
          provSelect.addEventListener('change', () => {
            const p = PROVIDER_PRESETS[provSelect.value] || PROVIDER_PRESETS.gemini;
            document.getElementById('cfg-model').value = p.model;
            document.getElementById('cfg-base-url').value = p.baseUrl;
          });
        }
      }

      const keyInput = document.getElementById('cfg-api-key');
      const serverIndicator = document.getElementById('server-key-indicator');
      const serverText = document.getElementById('server-key-text');

      if (data.has_key) {
        if (serverIndicator) serverIndicator.style.display = 'block';
        if (serverText) serverText.textContent = `本地 .env 已配置有效 Key (${data.masked_key})`;
        keyInput.placeholder = '已配置 Key，留空保持不变';
      } else {
        if (serverIndicator) serverIndicator.style.display = 'none';
        keyInput.placeholder = `在此粘贴 ${preset.label} API Key`;
      }

      document.getElementById('cfg-model').value = AppState.apiConfig.model;
      document.getElementById('cfg-base-url').value = AppState.apiConfig.baseUrl;

      updateApiBadge();
    }
  } catch (e) {
    console.warn('获取配置失败', e);
  }
}

async function loadSettings() {
  try {
    const res = await fetch('api/settings');
    if (res.ok) {
      const data = await res.json();
      AppState.correctionsEnabled = !!data.corrections_enabled;
      const chk = document.getElementById('cfg-corrections-enabled');
      if (chk) chk.checked = AppState.correctionsEnabled;
    }
  } catch (e) {
    console.warn('获取全局设置失败', e);
  }
}

async function loadActiveCorrections() {
  const container = document.getElementById('active-corrections-list');
  if (!container) return;
  try {
    const res = await fetch('api/corrections');
    if (res.ok) {
      const data = await res.json();
      const list = data.corrections || [];
      AppState.activeCorrections = list;
      if (!list.length) {
        container.innerHTML = '<div class="text-muted" style="font-size: 11.5px; padding: 4px 0;">暂无手动调整记录</div>';
        return;
      }
      container.innerHTML = list.map(c => {
        const isIgnored = !!c.correction_ignored;
        const tag = isIgnored ? '<span style="color:#94a3b8;">[已忽略]</span>' : '<span style="color:#059669;">[生效中]</span>';
        const actionBtn = isIgnored
          ? ''
          : `<button class="btn-ignore-corr" data-id="${c.id}" data-action="ignore-corr">忽略</button>`;
        const shortTitle = (c.title || '').substring(0, 24);
        return `
          <div class="correction-row-item">
            <span>${tag} 「${escapeHtml(shortTitle)}」(${c.ai_domain}·${(c.ai_quadrant||'').toUpperCase()} → ${c.domain}·${(c.quadrant||'').toUpperCase()})</span>
            ${actionBtn}
          </div>
        `;
      }).join('');
    }
  } catch (e) {
    container.innerHTML = `<div style="color:#ef4444; font-size:11.5px;">加载失败: ${e.message}</div>`;
  }
}

function updateApiBadge() {
  const badge = document.getElementById('api-status-badge');
  if (!badge) return;
  if (AppState.apiConfig.hasKey) {
    badge.className = 'api-status-pill online';
    badge.textContent = `在线 (${AppState.apiConfig.model})`;
  } else {
    badge.className = 'api-status-pill offline';
    badge.textContent = '规则保底 (点击配置API)';
  }
}

async function loadContext() {
  try {
    const res = await fetch('api/context');
    if (res.ok) {
      const data = await res.json();
      AppState.context = data.context || '';
      document.getElementById('user-context-input').value = AppState.context;
      updateContextPreview();
    }
  } catch (e) {
    console.warn('获取 Context 失败', e);
  }
}

function updateContextPreview() {
  const preview = document.getElementById('context-summary-preview');
  if (AppState.context.trim()) {
    preview.textContent = AppState.context.trim().substring(0, 32) + (AppState.context.length > 32 ? '...' : '');
    preview.className = '';
  } else {
    preview.textContent = '未设置（展开编辑）';
    preview.className = 'text-muted';
  }
}

async function saveContext() {
  const val = document.getElementById('user-context-input').value.trim();
  if (val === AppState.context) return;
  AppState.context = val;
  updateContextPreview();
  try {
    await fetch('api/context', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ context: val })
    });
  } catch (e) {
    console.error('保存 Context 失败', e);
  }
}

async function syncTasksFromServer() {
  try {
    const res = await fetch('api/tasks');
    if (res.ok) {
      const data = await res.json();
      AppState.tasks = data.tasks || [];
      renderMatrix();
    }
  } catch (e) {
    console.error('从服务端同步任务失败', e);
  }
}

// ============================================================================
// 事件绑定
// ============================================================================
function initEventListeners() {
  document.getElementById('btn-run-triage').addEventListener('click', runTriage);
  document.getElementById('btn-clear-input').addEventListener('click', () => {
    document.getElementById('task-raw-input').value = '';
    const dupBar = document.getElementById('duplicate-hint-bar');
    if (dupBar) dupBar.style.display = 'none';
  });

  document.getElementById('btn-copy-md').addEventListener('click', copyMarkdownExport);
  document.getElementById('btn-download-md').addEventListener('click', downloadMarkdownFile);
  document.getElementById('btn-download-json').addEventListener('click', downloadJsonFile);
  document.getElementById('btn-clear-matrix').addEventListener('click', clearMatrixTasks);

  // 重点 Context 折叠与保存
  document.getElementById('btn-toggle-context').addEventListener('click', () => {
    const body = document.getElementById('context-drawer-body');
    const arrow = document.getElementById('context-toggle-arrow');
    const isHidden = body.style.display === 'none';
    body.style.display = isHidden ? 'block' : 'none';
    arrow.textContent = isHidden ? '▴' : '▾';
  });
  document.getElementById('user-context-input').addEventListener('blur', saveContext);

  // 模态框打开与关闭
  document.getElementById('btn-toggle-settings').addEventListener('click', async () => {
    openModal('modal-settings');
    await loadActiveCorrections();
  });
  document.getElementById('btn-close-settings').addEventListener('click', () => closeModal('modal-settings'));

  document.getElementById('btn-toggle-advisory').addEventListener('click', () => {
    openModal('modal-advisory');
    loadAdvisoryModal();
  });
  document.getElementById('btn-close-advisory').addEventListener('click', () => closeModal('modal-advisory'));
  document.getElementById('btn-close-advisory-footer').addEventListener('click', () => closeModal('modal-advisory'));

  // 密码显示切换
  document.getElementById('btn-toggle-key-vis').addEventListener('click', () => {
    const input = document.getElementById('cfg-api-key');
    const btn = document.getElementById('btn-toggle-key-vis');
    const isPw = (input.type === 'password');
    input.type = isPw ? 'text' : 'password';
    btn.textContent = isPw ? '隐藏' : '显示';
  });
  document.getElementById('btn-test-api').addEventListener('click', testApiConnection);
  document.getElementById('btn-save-api').addEventListener('click', saveApiConfig);

  // 设置抽屉内部事件：忽略纠正按钮
  const activeCorrContainer = document.getElementById('active-corrections-list');
  if (activeCorrContainer) {
    activeCorrContainer.addEventListener('click', async (e) => {
      const btn = e.target.closest('[data-action="ignore-corr"]');
      if (!btn) return;
      const taskId = btn.getAttribute('data-id');
      if (taskId) {
        btn.disabled = true;
        btn.textContent = '处理中...';
        await fetch(`api/tasks/${taskId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ correction_ignored: 1 })
        });
        await loadActiveCorrections();
      }
    });
  }

  // 撤销 Toast 按钮
  document.getElementById('btn-undo-action').addEventListener('click', handleUndoAction);

  // 拖拽事件监听 (象限区域)
  document.querySelectorAll('.quadrant').forEach(zone => {
    zone.addEventListener('dragover', handleDragOver);
    zone.addEventListener('drop', handleDrop);
  });

  // 卡片操作全局事件委托
  document.querySelector('.matrix-section').addEventListener('click', handleCardActionClick);

  // A7: 原位编辑按 Enter 提交禁止换行
  document.querySelector('.matrix-section').addEventListener('keydown', (e) => {
    if (e.target.matches('[data-action="edit-title"]') && e.key === 'Enter') {
      e.preventDefault();
      e.target.blur();
    }
  });

  // 点击空白处关闭领域浮层
  document.addEventListener('click', (e) => {
    const pop = document.getElementById('domain-popover');
    if (pop && pop.style.display !== 'none') {
      if (!e.target.closest('.domain-badge-wrap') && !e.target.closest('.domain-popover')) {
        pop.style.display = 'none';
      }
    }
  });

  // 领域浮层菜单点击项
  document.getElementById('domain-popover').addEventListener('click', handleDomainPopoverClick);
}

// ============================================================================
// 核心智能分诊入口 (B8: 秒数计时与去重提示)
// ============================================================================
async function runTriage() {
  const inputEl = document.getElementById('task-raw-input');
  const text = inputEl.value.trim();
  const dupBar = document.getElementById('duplicate-hint-bar');
  dupBar.style.display = 'none';

  if (!text) {
    alert('请先输入或粘贴待分诊的文字内容！');
    return;
  }

  const btn = document.getElementById('btn-run-triage');
  const tag = document.getElementById('engine-tag-display');
  const reasonTag = document.getElementById('fallback-reason-display');

  btn.disabled = true;
  let elapsed = 0;
  btn.textContent = `分流中 0s`;
  const timer = setInterval(() => {
    elapsed += 1;
    if (elapsed > 45) {
      btn.textContent = `分流中 ${elapsed}s (输入较长，仍在处理)`;
    } else {
      btn.textContent = `分流中 ${elapsed}s`;
    }
  }, 1000);

  try {
    let byok = {};
    try { byok = JSON.parse(localStorage.getItem('ccagent_shared_byok') || '{}'); } catch (_) {}
    const reqBody = {
      text,
      fallback: document.getElementById('cfg-fallback').checked
    };
    if (byok.provider) reqBody.provider = byok.provider;
    if (byok.model) reqBody.model = byok.model;
    if (byok.api_key) reqBody.api_key = byok.api_key;
    if (byok.base_url) reqBody.base_url = byok.base_url;

    const res = await fetch('api/triage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(reqBody)
    });

    clearInterval(timer);

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `HTTP ${res.status}`);
    }

    const data = await res.json();
    tag.className = `card-engine-tag ${data.engine}`;
    tag.textContent = data.engine === 'ai' ? `大模型 (${data.model})` : '规则保底';

    // B7 保底原因展示
    if (data.fallback_reason) {
      reasonTag.style.display = 'inline-block';
      reasonTag.textContent = data.fallback_reason;
    } else {
      reasonTag.style.display = 'none';
    }

    const createdCount = (data.tasks || []).length;
    const skippedCount = data.skipped_duplicates || 0;

    // B2 去重提示逻辑
    if (skippedCount > 0) {
      dupBar.style.display = 'block';
      if (createdCount === 0) {
        dupBar.className = 'duplicate-hint-bar warning';
        dupBar.textContent = `没有新增事项（${skippedCount} 条均与已有任务重复）`;
      } else {
        dupBar.className = 'duplicate-hint-bar';
        dupBar.textContent = `已跳过 ${skippedCount} 条重复事项`;
      }
    }

    // 若新增为 0，不清空输入框；若有新增，则清空
    if (createdCount > 0) {
      inputEl.value = '';
    }

    // 记录新生成的任务 ID 用于轻量高亮动效
    AppState.newlyCreatedIds = new Set((data.tasks || []).map(t => t.id));
    setTimeout(() => {
      AppState.newlyCreatedIds.clear();
      document.querySelectorAll('.card-highlight-new').forEach(el => el.classList.remove('card-highlight-new'));
    }, 2000);

    await syncTasksFromServer();
  } catch (err) {
    clearInterval(timer);
    alert(`分诊请求失败: ${err.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = '开始分诊';
  }
}

// ============================================================================
// 四象限矩阵渲染 (B1 智囊名称、B4 AI 原判展示)
// ============================================================================
function renderMatrix() {
  const lists = {
    q1: document.getElementById('list-q1'),
    q2: document.getElementById('list-q2'),
    q3: document.getElementById('list-q3'),
    q4: document.getElementById('list-q4'),
    candidate: document.getElementById('list-candidate')
  };

  Object.values(lists).forEach(el => el ? el.innerHTML = '' : null);

  const activeTasks = AppState.tasks.filter(t => t.status !== 'removed');
  const countEl = document.getElementById('matrix-total-count');
  if (countEl) countEl.textContent = `共 ${activeTasks.length} 项进行中`;

  if (activeTasks.length === 0) {
    const emptyGuide = document.createElement('div');
    emptyGuide.className = 'empty-guide-box';
    emptyGuide.textContent = '把待办流水账粘贴到上方，点击“开始分诊”即可生成四象限清单';
    document.querySelector('.eisenhower-grid').appendChild(emptyGuide);
    return;
  } else {
    const existingGuide = document.querySelector('.empty-guide-box');
    if (existingGuide) existingGuide.remove();
  }

  let hasCandidate = false;

  activeTasks.forEach(task => {
    const card = createCardElement(task);
    if (task.quadrant === 'candidate') {
      hasCandidate = true;
      if (lists.candidate) lists.candidate.appendChild(card);
    } else if (lists[task.quadrant]) {
      lists[task.quadrant].appendChild(card);
    }
  });

  const candWrapper = document.getElementById('candidate-wrapper');
  if (candWrapper) {
    candWrapper.style.display = hasCandidate ? 'block' : 'none';
  }
}

function createCardElement(t) {
  const card = document.createElement('div');
  card.className = `task-card ${AppState.newlyCreatedIds.has(t.id) ? 'card-highlight-new' : ''}`;
  card.setAttribute('draggable', 'true');
  card.setAttribute('data-id', t.id);

  card.addEventListener('dragstart', handleDragStart);
  card.addEventListener('dragend', handleDragEnd);

  const domName = DOMAIN_NAMES[t.domain] || t.domain;

  // B1: 智囊名称显示
  const archetypeDisplay = t.expert_id ? (AppState.advisoryMap[t.expert_id] || '') : '';
  const archeHtml = archetypeDisplay
    ? `<div style="font-size:11px; color:#4b5563; margin-top:2px;">智囊原型：${escapeHtml(archetypeDisplay)}</div>`
    : '';

  // 事实因子详情
  const factors = typeof t.factors === 'string' ? JSON.parse(t.factors || '{}') : (t.factors || {});
  const assumptions = typeof t.assumptions === 'string' ? JSON.parse(t.assumptions || '[]') : (t.assumptions || []);

  const factorsHtml = `
    <div class="task-factors-box" id="factors-${t.id}" style="display: none;">
      <div class="factor-item"><span>截止期限：</span>${escapeHtml(factors.deadline || '无硬性要求')}</div>
      <div class="factor-item"><span>潜在后果：</span>${escapeHtml(factors.consequence || '无明确损失')}</div>
      <div class="factor-item"><span>后果可逆：</span>${factors.reversible ? '是' : '否'}</div>
      ${factors.waiting_party ? `<div class="factor-item"><span>等待响应：</span>${escapeHtml(factors.waiting_party)}</div>` : ''}
      ${factors.money_related ? `<div class="factor-item"><span>现金关联：</span>直接挂钩</div>` : ''}
      ${assumptions.length ? `<div class="factor-item"><span>前提假设：</span>${escapeHtml(assumptions.join('；'))}</div>` : ''}
      <div class="factor-item"><span>置信度：</span>${t.confidence || 'medium'}</div>
      ${archeHtml}
    </div>
  `;

  const probeHtml = t.probe 
    ? `<div class="task-probe-line">待确认：${escapeHtml(t.probe)}</div>` 
    : '';

  // B4: AI 原判展示逻辑
  const isMoved = (t.quadrant !== t.ai_quadrant);
  let reasonHtml = '';
  let adviceHtml = '';

  if (isMoved) {
    const aiQuadName = (t.ai_quadrant || '').toUpperCase();
    reasonHtml = `<div class="task-reason-line ai-override">AI 原判 ${aiQuadName}：${escapeHtml(t.reason || '无原判理由')}</div>`;
    adviceHtml = ''; // 隐藏 advice 行避免与当前象限产生逻辑冲突
  } else {
    reasonHtml = `<div class="task-reason-line">理由：${escapeHtml(t.reason || '常规待办')}</div>`;
    adviceHtml = t.advice ? `<div class="task-advice-line">建议：${escapeHtml(t.advice)}</div>` : '';
  }

  const movedBadge = isMoved ? `<span class="card-moved-tag">已调整</span>` : '';

  card.innerHTML = `
    <div class="card-top">
      <div class="card-title-wrap">
        <span class="domain-badge-wrap domain-${t.domain} clickable" data-action="open-domain-menu" data-id="${t.id}" title="点击切换领域">
          <span class="domain-dot"></span>
          <span>${domName}</span>
        </span>
        <div class="task-title-text" contenteditable="true" data-action="edit-title" data-id="${t.id}">${escapeHtml(t.title)}</div>
        ${movedBadge}
      </div>
      <button class="btn-card-delete" data-action="delete" data-id="${t.id}" title="删除任务">✕</button>
    </div>
    ${reasonHtml}
    ${adviceHtml}
    ${probeHtml}
    <div class="task-expand-toggle-wrap">
      <button class="btn-toggle-factors" data-action="toggle-factors" data-id="${t.id}">依据 ▾</button>
    </div>
    ${factorsHtml}
  `;

  return card;
}

// 全局卡片事件处理
async function handleCardActionClick(e) {
  const target = e.target.closest('[data-action]');
  if (!target) return;

  const action = target.getAttribute('data-action');
  const taskId = target.getAttribute('data-id');

  // 1. 删除任务
  if (action === 'delete') {
    if (confirm('确定要删除此任务吗？')) {
      await fetch(`api/tasks/${taskId}`, { method: 'DELETE' });
      await syncTasksFromServer();
    }
    return;
  }

  // 2. 展开/折叠“依据”
  if (action === 'toggle-factors') {
    const factorBox = document.getElementById(`factors-${taskId}`);
    if (factorBox) {
      const isHidden = factorBox.style.display === 'none';
      factorBox.style.display = isHidden ? 'block' : 'none';
      target.textContent = isHidden ? '收起 ▴' : '依据 ▾';
    }
    return;
  }

  // 3. 点击领域徽章弹出切换菜单 (B6)
  if (action === 'open-domain-menu') {
    e.stopPropagation();
    openDomainPopover(target, taskId);
    return;
  }
}

// 原位编辑标题失去焦点监听
document.addEventListener('focusout', async (e) => {
  if (e.target.matches('[data-action="edit-title"]')) {
    const taskId = e.target.getAttribute('data-id');
    const newTitle = e.target.textContent.trim();
    const task = AppState.tasks.find(t => t.id === taskId);
    if (task && newTitle && newTitle !== task.title) {
      task.title = newTitle;
      await fetch(`api/tasks/${taskId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ title: newTitle })
      });
    }
  }
});

// ============================================================================
// B5/B6 撤销机制与 Toast 提示
// ============================================================================
function showUndoToast(message, undoAction) {
  const toast = document.getElementById('undo-toast');
  const msgEl = document.getElementById('undo-toast-message');
  msgEl.textContent = message;
  AppState.undoAction = undoAction;

  toast.style.display = 'flex';
  if (AppState.undoTimer) clearTimeout(AppState.undoTimer);
  AppState.undoTimer = setTimeout(() => {
    toast.style.display = 'none';
    AppState.undoAction = null;
  }, 6000);
}

async function handleUndoAction() {
  if (AppState.undoAction && typeof AppState.undoAction === 'function') {
    const act = AppState.undoAction;
    AppState.undoAction = null;
    const toast = document.getElementById('undo-toast');
    if (toast) toast.style.display = 'none';
    await act();
  }
}

// ============================================================================
// B6 领域菜单交互
// ============================================================================
let activeDomainTaskId = null;

function openDomainPopover(anchorEl, taskId) {
  activeDomainTaskId = taskId;
  const pop = document.getElementById('domain-popover');
  const rect = anchorEl.getBoundingClientRect();
  pop.style.top = `${rect.bottom + window.scrollY + 4}px`;
  pop.style.left = `${rect.left + window.scrollX}px`;
  pop.style.display = 'block';
}

async function handleDomainPopoverClick(e) {
  const item = e.target.closest('.domain-popover-item');
  if (!item || !activeDomainTaskId) return;

  const newDomain = item.getAttribute('data-domain');
  const taskId = activeDomainTaskId;
  const pop = document.getElementById('domain-popover');
  pop.style.display = 'none';

  const task = AppState.tasks.find(t => t.id === taskId);
  if (!task || task.domain === newDomain) return;

  const oldDomain = task.domain;
  task.domain = newDomain;

  await fetch(`api/tasks/${taskId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ domain: newDomain })
  });

  await syncTasksFromServer();

  showUndoToast(`已将「${task.title.substring(0, 15)}」领域修改为 ${DOMAIN_NAMES[newDomain]}`, async () => {
    task.domain = oldDomain;
    await fetch(`api/tasks/${taskId}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ domain: oldDomain })
    });
    await syncTasksFromServer();
  });
}

// ============================================================================
// 拖拽改象限 (B5: 带撤销与重算)
// ============================================================================
let draggedTaskId = null;

function handleDragStart(e) {
  draggedTaskId = this.getAttribute('data-id');
  this.style.opacity = '0.5';
  e.dataTransfer.setData('text/plain', draggedTaskId);
  e.dataTransfer.dropEffect = 'move';
}

function handleDragEnd() {
  this.style.opacity = '1';
  draggedTaskId = null;
}

function handleDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
}

async function handleDrop(e) {
  e.preventDefault();
  const zone = e.target.closest('.quadrant');
  if (!zone) return;
  const targetQuadrant = zone.getAttribute('data-quadrant');
  const taskId = e.dataTransfer.getData('text/plain') || draggedTaskId;

  if (taskId && targetQuadrant) {
    const task = AppState.tasks.find(t => t.id === taskId);
    if (task && task.quadrant !== targetQuadrant) {
      const oldQuadrant = task.quadrant;
      task.quadrant = targetQuadrant;
      await fetch(`api/tasks/${taskId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quadrant: targetQuadrant })
      });
      await syncTasksFromServer();

      const quadLabel = QUADRANT_NAMES[targetQuadrant] || targetQuadrant.toUpperCase();
      showUndoToast(`已将「${task.title.substring(0, 15)}」移到 ${quadLabel}`, async () => {
        task.quadrant = oldQuadrant;
        await fetch(`api/tasks/${taskId}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ quadrant: oldQuadrant })
        });
        await syncTasksFromServer();
      });
    }
  }
}

// ============================================================================
// 清空矩阵看板 (可选择清空，不清空则后续录入在原来基础上分诊)
// ============================================================================
async function clearMatrixTasks() {
  const activeTasks = AppState.tasks.filter(t => t.status !== 'removed');
  if (activeTasks.length === 0) {
    alert('当前四象限看板已经是空的，无需清空。');
    return;
  }

  const ok = confirm(`确定要清空看板中的 ${activeTasks.length} 项任务吗？\n（任务将归档移出看板，不影响数据库历史日志与统计）`);
  if (!ok) return;

  const backupTasks = [...activeTasks];

  try {
    const res = await fetch('api/tasks', { method: 'DELETE' });
    if (res.ok) {
      await syncTasksFromServer();
      showUndoToast(`已清空四象限看板 (${backupTasks.length} 项)`, async () => {
        // 撤销清空：将这批任务状态恢复为 open
        for (const t of backupTasks) {
          await fetch(`api/tasks/${t.id}`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ status: t.status || 'open' })
          });
        }
        await syncTasksFromServer();
      });
    } else {
      const err = await res.json().catch(() => ({}));
      alert(`清空失败: ${err.error || '服务器异常'}`);
    }
  } catch (e) {
    alert(`网络异常: ${e.message}`);
  }
}

// ============================================================================
// 导出处理 (Markdown 与 JSON)
// ============================================================================
async function copyMarkdownExport() {
  try {
    const res = await fetch('api/export?format=md&status=open');
    if (!res.ok) throw new Error('导出接口异常');
    const md = await res.text();
    await navigator.clipboard.writeText(md);

    const btn = document.getElementById('btn-copy-md');
    const orig = btn.innerHTML;
    btn.innerHTML = '已复制';
    btn.style.borderColor = '#15803d';
    btn.style.color = '#15803d';
    setTimeout(() => {
      btn.innerHTML = orig;
      btn.style.borderColor = '';
      btn.style.color = '';
    }, 2000);
  } catch (e) {
    alert(`复制失败: ${e.message}`);
  }
}

function downloadMarkdownFile() {
  window.open('api/export?format=md&status=open', '_blank');
}

function downloadJsonFile() {
  window.open('api/export?format=json&status=open', '_blank');
}

// ============================================================================
// 智囊库弹窗与设置模态框
// ============================================================================
function openModal(id) {
  document.getElementById(id).classList.add('active');
}

function closeModal(id) {
  document.getElementById(id).classList.remove('active');
}

async function loadAdvisoryModal() {
  const container = document.getElementById('advisory-cards-container');
  if (!container) return;
  try {
    const res = await fetch('api/advisory');
    if (res.ok) {
      const data = await res.json();
      const items = data.advisory || [];
      if (!items.length) {
        container.innerHTML = '<div style="color:#6b7280; font-size:13px;">暂无智囊库数据</div>';
        return;
      }
      container.innerHTML = items.map(item => `
        <div class="advisory-card-item" style="background:#fafafa; border:1px solid #e5e7eb; border-radius:6px; padding:9px 11px; margin-bottom:8px;">
          <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:4px;">
            <strong style="font-size:13px; color:#111827;">${escapeHtml(item.name)}</strong>
            <span class="domain-badge-wrap domain-${item.domain}">
              <span class="domain-dot"></span>
              <span>${DOMAIN_NAMES[item.domain] || item.domain}</span>
            </span>
          </div>
          <div style="font-size:12px; color:#4b5563; margin-bottom:3px;">
            <strong>典型信号：</strong>${escapeHtml((item.typical_signals || []).join('、'))}
          </div>
          <div style="font-size:12px; color:#1f2937; margin-bottom:3px;">
            <strong>建议风格：</strong>${escapeHtml(item.advice_style || '')}
          </div>
          ${item.hidden_pitfalls ? `<div style="font-size:11.5px; color:#991b1b;"><strong>隐藏陷阱：</strong>${escapeHtml(item.hidden_pitfalls)}</div>` : ''}
        </div>
      `).join('');
    }
  } catch (e) {
    container.innerHTML = `<div style="color:#ef4444; font-size:13px;">加载智囊库失败: ${e.message}</div>`;
  }
}

async function saveApiConfig() {
  const provider = (document.getElementById('cfg-provider')?.value || 'gemini').trim();
  const keyInput = document.getElementById('cfg-api-key').value.trim();
  const model = document.getElementById('cfg-model').value.trim();
  const baseUrl = document.getElementById('cfg-base-url').value.trim();
  const correctionsEnabled = document.getElementById('cfg-corrections-enabled').checked;

  const updates = { provider, model, base_url: baseUrl };
  if (keyInput && !keyInput.includes('...')) {
    updates.api_key = keyInput;
  }

  try {
    // 1. 保存 API 配置
    const res = await fetch('api/save-config', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates)
    });
    // 2. 保存纠偏开关设置 (B3)
    await fetch('api/settings', {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ corrections_enabled: correctionsEnabled })
    });

    if (res.ok) {
      alert('设置已成功保存！');
      closeModal('modal-settings');
      await loadConfig();
      await loadSettings();
    }
  } catch (e) {
    alert(`保存失败: ${e.message}`);
  }
}

async function testApiConnection() {
  const provider = (document.getElementById('cfg-provider')?.value || 'gemini').trim();
  const keyInput = document.getElementById('cfg-api-key').value.trim();
  const model = document.getElementById('cfg-model').value.trim();
  const baseUrl = document.getElementById('cfg-base-url').value.trim();
  const resBox = document.getElementById('test-result-box');

  const preset = PROVIDER_PRESETS[provider] || PROVIDER_PRESETS.gemini;
  resBox.style.display = 'block';
  resBox.className = 'test-result-box';
  resBox.textContent = `正在测试与 ${preset.label} (${model}) 连通性...`;

  try {
    const res = await fetch('api/test-connection', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        provider,
        api_key: keyInput,
        model,
        base_url: baseUrl
      })
    });
    const data = await res.json();
    if (res.ok && data.status === 'ok') {
      resBox.className = 'test-result-box success';
      resBox.textContent = `${data.message}`;
    } else {
      resBox.className = 'test-result-box error';
      resBox.textContent = `${data.message || data.error}`;
    }
  } catch (err) {
    resBox.className = 'test-result-box error';
    resBox.textContent = `测试请求失败: ${err.message}`;
  }
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
