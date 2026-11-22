/**
 * CCagent - 管理者任务分诊台 (Task Triage Studio)
 * 核心交互逻辑与智能分诊引擎 (集成 Google Gemini API 与 离线保底规则)
 */

function sanitizeModel(model) {
  if (!model || model === 'gemini-2.0-flash' || model === 'gemini-1.5-flash' || model === 'gemini-2.5-flash') {
    return 'gemini-3.5-flash';
  }
  return model;
}

// 状态中心
const AppState = {
  tasks: [],
  currentView: 'matrix', // 'matrix' | 'linear'
  eventLibrary: [],
  cozePrompt: '',
  yuanqiPrompt: '',
  mantra: '管理者的精力，绝不能被别人转嫁的假火警吃掉。识别单向门决策，将琐事大胆下放！',
  apiConfig: {
    localKey: localStorage.getItem('ccagent_gemini_key') || '',
    model: sanitizeModel(localStorage.getItem('ccagent_gemini_model')),
    baseUrl: localStorage.getItem('ccagent_gemini_base_url') || 'https://generativelanguage.googleapis.com',
    fallback: localStorage.getItem('ccagent_fallback') !== 'false',
    backendAvailable: false,
    serverHasKey: false,
    serverMaskedKey: ''
  }
};

// 预设高管测试案例
const PRESETS = {
  tech_director: `已完成：
- 核心支付链路压测报告已审阅并批注
- 上周研发产能周报已抄送分管VP

今日顺延（未完成）：
- 跨部门数据仓库接口字段撕扯（对方开发一直未给回执，卡住）

明日与近期任务：
- 【线上】主站搜索模块偶现白屏报警，需24小时内止损
- 下属小张空手来问新微服务架构是用Go还是Rust（未提具体对比）
- 参加下午2:00常规研发例会（约20人，主要是各组流水账进度同步）
- 梳理团队Q3核心骨干激励与晋升面谈方案
- 老板周日深夜转发了一篇行业AI Agent趋势文章，附言“技术部怎么看？”
- 批量处理OA流程中堆积的14条报销与请假审批
- 对后台旧版配置界面的CSS样式做一轮视觉对齐重构`,

  biz_manager: `今日已完成：
- 华东大区重点KA客户续约合同初审签字

未完成顺延：
- 销售二组的提成争议协调（双方还在互踢皮球）

明日计划与待办：
- 核心大客户要求明天上午10点前必须给出降级赔偿方案（否则威胁解约）
- 华南区销售总监突然私信要我们部门出调拨支持（未走正式周流程）
- 本周业务分析周会（听取各省区业绩汇报）
- 针对下属新人小李最近连续两周业绩垫底且情绪低落的情况安排1v1复盘
- 审批待办里的差旅与餐费报销（共8笔）
- 竞品今天早上上线了新的分销打法，群里销售都在躁动问要不要跟做`,

  mixed_dump: `昨天的自动化测试脚本改完了。
今天本来想把接口文档补完，但被拉去开了3个临时会，没写完，明天得弄。
明天要给新员工做入职培训。
核心数据库CPU偶尔飙高到90%，得尽快查根因。
有个下属说想转岗，还没定哪天聊。
看了一篇关于提示词工程的博客，想在团队里试试看。
等HR发招聘HC的回复。`
};

// 分诊提示词的唯一来源是 prompts/triage_prompt.md（服务端与前端直连模式共用），这里不再重复存一份。

// ============================================================================
// 任务持久化与恢复 (LocalStorage Persistence)
// ============================================================================
function saveTasksToStorage() {
  try {
    localStorage.setItem('ccagent_tasks_v1', JSON.stringify(AppState.tasks));
    localStorage.setItem('ccagent_mantra_v1', AppState.mantra);
    if (AppState.lastTriageInfo) {
      localStorage.setItem('ccagent_triage_info_v1', JSON.stringify(AppState.lastTriageInfo));
    }
  } catch (e) {
    console.warn('任务保存到 localStorage 失败:', e);
  }
}

function loadTasksFromStorage() {
  try {
    const raw = localStorage.getItem('ccagent_tasks_v1');
    if (raw) {
      const parsed = JSON.parse(raw);
      if (Array.isArray(parsed) && parsed.length > 0) {
        AppState.tasks = parsed.map(migrateTask);
        const savedMantra = localStorage.getItem('ccagent_mantra_v1');
        if (savedMantra) AppState.mantra = savedMantra;
        const savedInfo = localStorage.getItem('ccagent_triage_info_v1');
        if (savedInfo) {
          const info = JSON.parse(savedInfo);
          setTriageBanner(info.type, info.title, info.desc);
        }
        return true;
      }
    }
  } catch (e) {
    console.warn('从 localStorage 加载任务失败:', e);
  }
  return false;
}

// 初始化入口
document.addEventListener('DOMContentLoaded', async () => {
  initEventListeners();
  await initApiStatus();
  await loadStaticResources();

  // 1. 尝试从 localStorage 恢复用户之前的工作区状态 (不再每次打开自动诊断)
  const hasSavedTasks = loadTasksFromStorage();
  if (hasSavedTasks) {
    updateStatsAndMantra();
    renderMatrixView();
  } else {
    // 首次进入无缓存时，只填充示例文本供参考，绝不自动调用诊断
    loadPreset('tech_director');
    setTriageBanner('idle', '引擎就绪：尚未分诊', '请在上方确认待办文本后，点击「⚡ 一键智能分诊」开始');
  }
});

// 加载外部提示词与事件库资源
async function loadStaticResources() {
  try {
    const resEvents = await fetch('prompts/event_library_v2.json');
    if (resEvents.ok) {
      AppState.eventLibrary = await resEvents.json();
      renderEventsModal();
    }
  } catch (e) {
    console.warn('事件库加载跳过，使用内置模式', e);
  }

  try {
    const resTriage = await fetch('prompts/triage_prompt.md');
    if (resTriage.ok) AppState.triagePrompt = await resTriage.text();
  } catch (e) {
    console.warn('分诊提示词加载跳过（仅影响无后端的前端直连模式）', e);
  }

  try {
    const resCoze = await fetch('prompts/coze_prompt.md');
    if (resCoze.ok) {
      AppState.cozePrompt = await resCoze.text();
      document.getElementById('text-coze-prompt').value = AppState.cozePrompt;
    }
    const resYuanqi = await fetch('prompts/yuanqi_prompt.md');
    if (resYuanqi.ok) {
      AppState.yuanqiPrompt = await resYuanqi.text();
      document.getElementById('text-yuanqi-prompt').value = AppState.yuanqiPrompt;
    }
  } catch (e) {
    console.warn('平台提示词加载跳过', e);
  }
}

// 初始化 API 状态与同步
async function initApiStatus() {
  // 清理旧版本可能存入的脏数据
  if (localStorage.getItem('ccagent_gemini_key') === 'server-configured') {
    localStorage.removeItem('ccagent_gemini_key');
  }

  const storedLocalKey = localStorage.getItem('ccagent_gemini_key') || '';
  AppState.apiConfig.localKey = storedLocalKey;

  try {
    const resp = await fetch('/api/config');
    if (resp.ok) {
      const serverConfig = await resp.json();
      AppState.apiConfig.backendAvailable = true;
      AppState.apiConfig.serverHasKey = serverConfig.has_key;
      AppState.apiConfig.serverMaskedKey = serverConfig.masked_key || '';
      if (serverConfig.model) AppState.apiConfig.model = sanitizeModel(serverConfig.model);
      if (serverConfig.base_url) AppState.apiConfig.baseUrl = serverConfig.base_url;
    }
  } catch (e) {
    AppState.apiConfig.backendAvailable = false;
  }

  // 同步到设置弹窗的表单：严禁将 'server-configured' 填入输入框！
  const keyInput = document.getElementById('cfg-api-key');
  const serverIndicator = document.getElementById('server-key-indicator');
  const serverText = document.getElementById('server-key-text');

  if (AppState.apiConfig.serverHasKey) {
    if (serverIndicator) serverIndicator.style.display = 'block';
    if (serverText) serverText.textContent = `🟢 本地服务端 .env 已配置有效 Key (${AppState.apiConfig.serverMaskedKey})`;
    keyInput.placeholder = '已配置真实 Key，留空则保持不变';
    keyInput.value = AppState.apiConfig.localKey; // 只有用户在前端显式输入过才填入，否则留空
  } else {
    if (serverIndicator) serverIndicator.style.display = 'none';
    keyInput.placeholder = '在此粘贴您的 Google API Key (以 AIzaSy 或 AQ 开头)';
    keyInput.value = AppState.apiConfig.localKey;
  }

  document.getElementById('cfg-model').value = AppState.apiConfig.model;
  document.getElementById('cfg-base-url').value = AppState.apiConfig.baseUrl;
  document.getElementById('cfg-fallback').checked = AppState.apiConfig.fallback;

  updateApiBadge();
}

function updateApiBadge() {
  const badge = document.getElementById('api-status-badge');
  const hasKey = Boolean(AppState.apiConfig.localKey || (AppState.apiConfig.backendAvailable && AppState.apiConfig.serverHasKey));
  if (hasKey) {
    badge.className = 'api-status-pill online';
    badge.textContent = `Gemini 在线 (${AppState.apiConfig.model})`;
    badge.title = 'Google Gemini API 已接入并就绪';
  } else {
    badge.className = 'api-status-pill offline';
    badge.textContent = '离线模式 (点击接入API)';
    badge.title = '尚未配置 API Key，当前使用内置专家规则保底';
  }
}

// 统一的引擎提示横幅设置
function setTriageBanner(type, title, desc) {
  AppState.lastTriageInfo = { type, title, desc };
  const banner = document.getElementById('engine-source-banner');
  const icon = document.getElementById('engine-badge-icon');
  const titleEl = document.getElementById('engine-badge-title');
  const descEl = document.getElementById('engine-badge-desc');
  const tipTag = document.getElementById('engine-tip-tag');
  if (!banner || !icon || !titleEl) return;

  if (type === 'ai') {
    banner.className = 'engine-source-banner banner-ai';
    icon.textContent = '🤖';
    titleEl.textContent = title;
    descEl.textContent = desc;
    tipTag.textContent = '实时大模型';
    tipTag.style.background = '#dcfce7';
    tipTag.style.color = '#15803d';
  } else if (type === 'fallback') {
    banner.className = 'engine-source-banner banner-fallback';
    icon.textContent = '⚠️';
    titleEl.textContent = title;
    descEl.textContent = desc;
    tipTag.textContent = '规则兜底';
    tipTag.style.background = '#fef3c7';
    tipTag.style.color = '#b45309';
  } else {
    banner.className = 'engine-source-banner banner-idle';
    icon.textContent = '⚪';
    titleEl.textContent = title;
    descEl.textContent = desc;
    tipTag.textContent = '准备就绪';
    tipTag.style.background = '';
    tipTag.style.color = '';
  }
}

// 绑定事件监听
function initEventListeners() {
  // 清空看板重置
  const btnResetBoard = document.getElementById('btn-reset-board');
  if (btnResetBoard) {
    btnResetBoard.addEventListener('click', () => {
      if (confirm('确定要清空当前四象限看板和归档列表吗？此操作将重置本地缓存。')) {
        AppState.tasks = [];
        localStorage.removeItem('ccagent_tasks_v1');
        localStorage.removeItem('ccagent_triage_info_v1');
        updateStatsAndMantra();
        renderMatrixView();
        if (AppState.currentView === 'linear') renderLinearView();
        setTriageBanner('idle', '引擎就绪：尚未分诊', '工作区已清空，可输入新待办重新分诊');
      }
    });
  }
  // 视图切换
  document.getElementById('view-matrix-btn').addEventListener('click', () => switchView('matrix'));
  document.getElementById('view-linear-btn').addEventListener('click', () => switchView('linear'));

  // 预设按钮
  document.querySelectorAll('.quick-examples .pill-btn[data-preset]').forEach(btn => {
    btn.addEventListener('click', () => {
      const presetKey = btn.getAttribute('data-preset');
      loadPreset(presetKey);
    });
  });

  // 清空按钮
  document.getElementById('btn-clear-input').addEventListener('click', () => {
    document.getElementById('task-raw-input').value = '';
    document.getElementById('task-raw-input').focus();
  });

  // 一键分诊
  document.getElementById('btn-run-triage').addEventListener('click', runTriage);

  // 弹窗控制
  document.getElementById('btn-open-settings-modal').addEventListener('click', () => {
    document.getElementById('test-result-box').style.display = 'none';
    openModal('modal-settings');
  });
  document.getElementById('btn-open-prompt-modal').addEventListener('click', () => openModal('modal-prompts'));
  document.getElementById('btn-open-events-modal').addEventListener('click', () => openModal('modal-events'));
  document.getElementById('btn-export-card').addEventListener('click', () => {
    updateShareCardPreview();
    openModal('modal-card');
  });

  // 设置弹窗内的操作
  document.getElementById('btn-toggle-key-vis').addEventListener('click', () => {
    const input = document.getElementById('cfg-api-key');
    input.type = input.type === 'password' ? 'text' : 'password';
  });

  document.getElementById('btn-test-api').addEventListener('click', testApiConnection);
  document.getElementById('btn-save-api').addEventListener('click', saveApiConfig);

  // 提示词模态框内的 Tab 切换
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      const targetTab = btn.getAttribute('data-tab');
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(targetTab).classList.add('active');
    });
  });

  // 备选区折叠的“已归档”切换
  document.getElementById('btn-toggle-done').addEventListener('click', () => {
    const listDone = document.getElementById('list-done');
    listDone.classList.toggle('collapsed');
  });

  // 下载战报图片
  document.getElementById('btn-download-image').addEventListener('click', downloadCardImage);
}

// 保存 API 设置 (严防将占位符写回 .env)
async function saveApiConfig() {
  const keyInput = document.getElementById('cfg-api-key').value.trim();
  const rawModel = document.getElementById('cfg-model').value.trim();
  const model = sanitizeModel(rawModel);
  const baseUrl = document.getElementById('cfg-base-url').value.trim();
  const fallback = document.getElementById('cfg-fallback').checked;

  AppState.apiConfig.model = model;
  AppState.apiConfig.baseUrl = baseUrl;
  AppState.apiConfig.fallback = fallback;

  localStorage.setItem('ccagent_gemini_model', model);
  localStorage.setItem('ccagent_gemini_base_url', baseUrl);
  localStorage.setItem('ccagent_fallback', String(fallback));

  const updates = { model, base_url: baseUrl };

  // 严格检查：只有当用户输入了真正的新 Key 时才更新；留空绝对不传 api_key，严禁覆盖 .env
  if (keyInput && keyInput !== 'server-configured' && !keyInput.includes('...') && !keyInput.includes('已在')) {
    AppState.apiConfig.localKey = keyInput;
    localStorage.setItem('ccagent_gemini_key', keyInput);
    updates.api_key = keyInput;
  } else if (!keyInput) {
    // 留空意味着继续使用服务端 .env，清除本地存储的覆写
    AppState.apiConfig.localKey = '';
    localStorage.removeItem('ccagent_gemini_key');
  }

  // 同步到本地服务端（如果运行中）
  if (AppState.apiConfig.backendAvailable) {
    try {
      await fetch('/api/save-config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(updates)
      });
    } catch (e) {
      console.warn('服务端同步保存跳过', e);
    }
  }

  updateApiBadge();
  closeModal('modal-settings');
  alert('API 配置已保存！');
}

// 测试连通性
async function testApiConnection() {
  const keyInput = document.getElementById('cfg-api-key').value.trim();
  const rawModel = document.getElementById('cfg-model').value.trim();
  const model = sanitizeModel(rawModel);
  const baseUrl = document.getElementById('cfg-base-url').value.trim();
  const resultBox = document.getElementById('test-result-box');

  // 判断是否有有效 Key
  const isRealInputKey = keyInput && keyInput !== 'server-configured' && !keyInput.includes('...') && !keyInput.includes('已在');
  const effectiveKey = isRealInputKey ? keyInput : (AppState.apiConfig.localKey || '');

  if (!effectiveKey && !AppState.apiConfig.serverHasKey) {
    resultBox.style.display = 'block';
    resultBox.className = 'test-result-box error';
    resultBox.textContent = '❌ 请先输入 Google API Key 再进行测试！';
    return;
  }

  resultBox.style.display = 'block';
  resultBox.className = 'test-result-box';
  resultBox.textContent = `⏳ 正在向 Google Gemini (${model}) 发起轻量测试连通中...`;

  try {
    // 优先通过本地后端测试 (解决跨域/代理并能读取服务端的 .env)
    if (AppState.apiConfig.backendAvailable) {
      const resp = await fetch('/api/test-connection', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ 
          api_key: isRealInputKey ? keyInput : '', // 留空则服务端自动读取 .env
          model, 
          base_url: baseUrl 
        })
      });
      const data = await resp.json();
      if (resp.ok && data.status === 'ok') {
        resultBox.className = 'test-result-box success';
        resultBox.textContent = `✅ 连通成功！Google Gemini (${model}) 响应正常。`;
        return;
      } else {
        throw new Error(data.message || '后端连通失败');
      }
    }

    // 纯前端直连测试 (仅当本地后端未运行且前端有有效 Key)
    const endpoint = `${baseUrl.replace(/\/+$/, '')}/v1beta/models/${model}:generateContent?key=${effectiveKey}`;
    const resp = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        contents: [{ parts: [{ text: 'Respond with 1 word: Pong' }] }]
      })
    });

    if (resp.ok) {
      resultBox.className = 'test-result-box success';
      resultBox.textContent = `✅ 连通成功！Google Gemini (${model}) 直连测试通过。`;
    } else {
      const errData = await resp.json().catch(() => ({}));
      throw new Error(errData?.error?.message || `HTTP ${resp.status}`);
    }
  } catch (err) {
    resultBox.className = 'test-result-box error';
    resultBox.innerHTML = `❌ 连接失败: ${escapeHtml(err.message)}<br><small>💡 提示：国内网络如无法直连谷歌官方域名，请使用科学网络或在 Base URL 中填写反代中转地址。</small>`;
  }
}

// 加载预设文本
function loadPreset(key) {
  if (PRESETS[key]) {
    document.getElementById('task-raw-input').value = PRESETS[key];
  }
}

// 视图切换
function switchView(viewName) {
  AppState.currentView = viewName;
  const matrixBtn = document.getElementById('view-matrix-btn');
  const linearBtn = document.getElementById('view-linear-btn');
  const matrixView = document.getElementById('view-matrix');
  const linearView = document.getElementById('view-linear');

  if (viewName === 'matrix') {
    matrixBtn.classList.add('active');
    linearBtn.classList.remove('active');
    matrixView.classList.add('active');
    linearView.classList.remove('active');
  } else {
    matrixBtn.classList.remove('active');
    linearBtn.classList.add('active');
    matrixView.classList.remove('active');
    linearView.classList.add('active');
    renderLinearView();
  }
}

// ============================================================================
// 核心智能分诊入口 (调用 Google Gemini API 或 离线保底引擎)
// ============================================================================
async function runTriage() {
  const rawText = document.getElementById('task-raw-input').value.trim();
  if (!rawText) {
    alert('请先输入或粘贴待办事项文本！');
    return;
  }

  const btn = document.getElementById('btn-run-triage');
  const originalBtnHtml = btn.innerHTML;

  // 1. 如果配置了 Google API Key (无论在本地还是浏览器)，优先走真实大模型分诊
  const hasKey = Boolean(AppState.apiConfig.localKey || (AppState.apiConfig.backendAvailable && AppState.apiConfig.serverHasKey));
  if (hasKey) {
    btn.innerHTML = '<span class="icon">🤖</span> Gemini AI 正在穿透分诊中...';
    btn.disabled = true;

    try {
      const aiResult = await callGeminiTriage(rawText);
      if (aiResult && Array.isArray(aiResult.tasks) && aiResult.tasks.length > 0) {
        applyAiTriageResult(aiResult);
        return;
      } else {
        throw new Error('Gemini 返回的任务数组为空或格式异常');
      }
    } catch (err) {
      console.warn('Gemini API 调用异常:', err);
      if (AppState.apiConfig.fallback) {
        runLocalHeuristicTriage(rawText, `Gemini 响应异常 (${err.message})`);
      } else {
        alert(`❌ 调用 Gemini 失败: ${err.message}`);
      }
    } finally {
      btn.innerHTML = originalBtnHtml;
      btn.disabled = false;
    }
    return;
  }

  // 2. 未配置 Key：使用内置专家逻辑保底
  runLocalHeuristicTriage(rawText, '尚未配置 API Key，直接走本地专家逻辑');
}

// 前端直连模式使用：与服务端同一份提示词文件，并拼入事件库精简索引
function buildClientSystemPrompt() {
  if (!AppState.triagePrompt) throw new Error('分诊提示词 prompts/triage_prompt.md 未加载');
  const index = (AppState.eventLibrary || [])
    .map(e => `- ${e.id}｜${e.name}｜${e.feature}`)
    .join('\n') || '（事件库不可用，所有任务的 eventId 一律填 null）';
  return AppState.triagePrompt.replace('{{EVENT_INDEX}}', index);
}

// 调用 Google Gemini API (支持本地中继代理与前端直接调用)
async function callGeminiTriage(text) {
  const { localKey, model, baseUrl, backendAvailable } = AppState.apiConfig;
  const safeModel = sanitizeModel(model);

  // 方案 A: 本地服务端中继转发 (避免浏览器 CORS 与本地代理配置烦恼)
  if (backendAvailable) {
    const resp = await fetch('/api/triage', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        text, 
        api_key: localKey, // 如果留空，服务端会自动使用 .env 中的真实 Key
        model: safeModel, 
        base_url: baseUrl 
      })
    });
    if (!resp.ok) {
      const errJson = await resp.json().catch(() => ({}));
      throw new Error(errJson.error || `HTTP ${resp.status}`);
    }
    return await resp.json();
  }

  // 方案 B: 纯前端 Fetch 直连 Google Gemini API
  const endpoint = `${baseUrl.replace(/\/+$/, '')}/v1beta/models/${safeModel}:generateContent?key=${localKey}`;
  const payload = {
    system_instruction: {
      parts: [{ text: buildClientSystemPrompt() }]
    },
    contents: [
      {
        role: "user",
        parts: [{ text: `请对以下管理者的任务进行结构化分诊：\n\n${text}` }]
      }
    ],
    generationConfig: {
      temperature: 0.2,
      response_mime_type: "application/json"
    }
  };

  const resp = await fetch(endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });

  if (!resp.ok) {
    const errData = await resp.json().catch(() => ({}));
    throw new Error(errData?.error?.message || `HTTP ${resp.status}`);
  }

  const data = await resp.json();
  const rawTextOut = data.candidates?.[0]?.content?.parts?.[0]?.text;
  if (!rawTextOut) throw new Error('Gemini API 未返回文本内容');

  // 清洗可能存在的 markdown 代码块
  let cleanJson = rawTextOut.trim();
  if (cleanJson.startsWith('```json')) cleanJson = cleanJson.slice(7);
  if (cleanJson.startsWith('```')) cleanJson = cleanJson.slice(3);
  if (cleanJson.endsWith('```')) cleanJson = cleanJson.slice(0, -3);

  return JSON.parse(cleanJson.trim());
}

// 将 AI 返回的结构化结果注入应用状态
function applyAiTriageResult(aiResult) {
  if (aiResult.mantra) {
    AppState.mantra = aiResult.mantra;
    document.getElementById('mantra-text').textContent = aiResult.mantra;
  }

  // 字段统一规范化：非法的 action / eventId / 时间一律修正，模型编造的事件 id 会被丢弃
  AppState.tasks = aiResult.tasks.map((item, i) => normalizeTask(item, i + 1, 'ai'));

  const activeTasks = AppState.tasks.filter(t => !t.isDone);
  const hitCount = activeTasks.filter(t => t.eventId).length;

  // 明确标识为 AI 大模型生成
  setTriageBanner(
    'ai',
    '【Google Gemini AI 大模型生成】',
    `模型：${AppState.apiConfig.model || 'gemini-3.5-flash'} · 事件库命中 ${hitCount}/${activeTasks.length} 项`
  );

  updateStatsAndMantra();
  saveTasksToStorage();
  renderMatrixView();
  if (AppState.currentView === 'linear') renderLinearView();
}

// ============================================================================
// 离线高管专家规则分诊引擎 (Local Fallback Engine)
// ============================================================================
function runLocalHeuristicTriage(rawText, fallbackReason = '') {
  // 明确标出这是规则兜底，不是 AI
  setTriageBanner(
    'fallback',
    '【这是规则兜底，不是 AI】',
    fallbackReason ? `触发原因：${fallbackReason}` : '未启用 AI 大模型，当前由内置高管专家规则保底分诊'
  );

  const lines = rawText.split('\n').map(l => l.trim()).filter(l => l.length > 0);
  const tasks = [];
  let currentSource = 'tomorrow';
  let idCounter = 1;

  for (let line of lines) {
    if (/^(已完成|完成|做完|今日已完成|Done)[:：]/i.test(line)) {
      currentSource = 'done';
      line = line.replace(/^(已完成|完成|做完|今日已完成|Done)[:：]/i, '').trim();
      if (!line) continue;
    } else if (/^(今日顺延|顺延|未完成|未完|延期|Rollover)[:：]/i.test(line)) {
      currentSource = 'rollover';
      line = line.replace(/^(今日顺延|顺延|未完成|未完|延期|Rollover)[:：]/i, '').trim();
      if (!line) continue;
    } else if (/^(明日计划|明天|明日|计划|待办|Tomorrow)[:：]/i.test(line)) {
      currentSource = 'tomorrow';
      line = line.replace(/^(明日计划|明天|明日|计划|待办|Tomorrow)[:：]/i, '').trim();
      if (!line) continue;
    } else if (/^(未来|以后|远期|备选|设想|Future)[:：]/i.test(line)) {
      currentSource = 'future';
      line = line.replace(/^(未来|以后|远期|备选|设想|Future)[:：]/i, '').trim();
      if (!line) continue;
    }

    const cleanTitle = line.replace(/^[-*•\d+.\s]+/, '').trim();
    if (!cleanTitle) continue;

    const taskItem = finalizeFallbackTask(triageSingleTask(cleanTitle, currentSource, `rule-${Date.now()}-${idCounter++}`));
    taskItem.engine = 'fallback';
    tasks.push(taskItem);
  }

  AppState.tasks = tasks;
  updateStatsAndMantra();
  saveTasksToStorage();
  renderMatrixView();
  if (AppState.currentView === 'linear') {
    renderLinearView();
  }
}

function triageSingleTask(title, source, id) {
  if (source === 'done') {
    return {
      id,
      title,
      source: 'done',
      quadrant: 'candidate',
      isDone: true,
      reason: '今日战果复盘归档',
      order: 999
    };
  }

  if (
    /^(看下|想想|研究|试试|了解|随便|转岗|等|纠结|待定)/.test(title) ||
    /还没定|不确定|等.*回复|拿不准/.test(title) ||
    title.length <= 4
  ) {
    return {
      id,
      title,
      source,
      quadrant: 'candidate',
      isDone: false,
      reason: '事项定义模糊或依赖外部未定条件',
      eventId: /转岗|离职/.test(title) ? 'EVT-06' : null,
      pendingProbe: '❓ 反问：这件事如果两周内彻底搁置，会发生不可逆的业务损失吗？',
      order: 50
    };
  }

  // 跨部门推诿死锁：按 EVT-08 的思路设时间锚点、必要时升级，不属于「立刻救火」
  if (/撕扯|踢皮球|互踢|推诿|扯皮/.test(title)) {
    return {
      id,
      title,
      source,
      quadrant: 'q2',
      isDone: false,
      reason: '职责边界卡死、多轮扯皮没有结果。按事件库思路：拉短会定边界并设时间锚点，到点未定则升级给共同上级。',
      eventId: 'EVT-08',
      order: 12
    };
  }

  if (
    /线上.*(报警|故障|崩|挂|死锁|不可用|白屏)|紧急.*(客诉|解约|赔偿)|致命bug|24小时内|最高等级|关键单向门/i.test(title) ||
    (source === 'rollover' && /卡住|阻断|严重/i.test(title))
  ) {
    return {
      id,
      title,
      source,
      quadrant: 'q1',
      isDone: false,
      reason: '关乎核心系统稳定性或关键客户关系，属单向门高危交付，必须亲自盯防并建立指挥线。',
      eventId: 'EVT-05',
      order: 1
    };
  }

  if (/空手来问|怎么弄|哪个框架|请示.*选型|帮忙看下/.test(title)) {
    return {
      id,
      title,
      source,
      quadrant: 'q3',
      isDone: false,
      reason: '下属反向委派（猴子跳回背上）。应打回并要求提供2个对比方案与利弊依据。',
      eventId: 'EVT-01',
      order: 30
    };
  }

  if (/常规.*(周会|例会|通气会|早会|站会)|跨部门.*(催|支持|取数)|报销|审批|签字|oa流程|发票/i.test(title)) {
    return {
      id,
      title,
      source,
      quadrant: 'q3',
      isDone: false,
      reason: '事务性流程或常规沟通。建议每日统一安排在下午 17:30 集中批处理，或委托骨干代会。',
      eventId: /报销|审批|签字|oa流程|发票/i.test(title) ? 'EVT-09' : (/常规.*(周会|例会|通气会|早会|站会)/.test(title) ? 'EVT-04' : 'EVT-02'),
      order: 31
    };
  }

  if (
    /老板.*(深夜|周末).*文章|竞品.*跟做|重构.*css|微调.*样式|过早优化|无意义/i.test(title) ||
    /随便看看|刷一刷/.test(title)
  ) {
    return {
      id,
      title,
      source,
      quadrant: 'q4',
      isDone: false,
      reason: '高精力消耗但低业务ROI，属非火警事项。老板想法周一再盘，竞品噱头先观察一周。',
      eventId: /老板/.test(title) ? 'EVT-03' : (/竞品/.test(title) ? 'EVT-10' : null),
      order: 40
    };
  }

  if (/架构|规划|基建|激励|晋升|复盘|1v1|面谈|绩效|治理|技术债|深度|培训/i.test(title)) {
    return {
      id,
      title,
      source,
      quadrant: 'q2',
      isDone: false,
      reason: '高价值深水区建设，决定部门中长期战斗力。需避开碎片打扰，预留2小时大块时间攻坚。',
      eventId: /情绪|低落|离职|转岗/.test(title) ? 'EVT-06' : (/架构|治理|技术债/.test(title) ? 'EVT-07' : null),
      order: 10
    };
  }

  if (source === 'rollover') {
    return {
      id,
      title,
      source,
      quadrant: 'q2',
      isDone: false,
      reason: '今日未完成的顺延事项。顺延不等于紧急，先确认它为什么没做完：是被打断、被阻塞，还是本来就不重要。',
      order: 2
    };
  }

  return {
    id,
    title,
    source,
    quadrant: 'q2',
    isDone: false,
    reason: '业务推进事项。建议在完成紧急火警后，作为下午第一段专注任务执行。',
    order: 15
  };
}

// ============================================================================
// 渲染四象限与备选区 (View 1: Matrix View)
// ============================================================================
function renderMatrixView() {
  const quadrants = ['q1', 'q2', 'q3', 'q4', 'candidate'];
  quadrants.forEach(q => {
    const listEl = document.getElementById(`list-${q}`);
    if (listEl) listEl.innerHTML = '';
  });

  const doneListEl = document.getElementById('list-done');
  doneListEl.innerHTML = '';

  let doneCount = 0;

  AppState.tasks.forEach(task => {
    if (task.isDone || task.source === 'done') {
      doneCount++;
      const doneCard = createDoneCardElement(task);
      doneListEl.appendChild(doneCard);
      return;
    }

    const card = createTaskCardElement(task);
    const container = document.getElementById(`list-${task.quadrant}`);
    if (container) {
      container.appendChild(card);
    }
  });

  document.getElementById('done-count-inner').textContent = doneCount;
}

// 创建单个任务卡片
function createTaskCardElement(task) {
  const card = document.createElement('div');
  card.className = 'task-card';
  card.setAttribute('draggable', 'true');
  card.setAttribute('data-id', task.id);

  card.addEventListener('dragstart', handleDragStart);
  card.addEventListener('dragend', handleDragEnd);
  // 卡片级拖拽监听：支持同象限内拖动排序以及精准插入
  card.addEventListener('dragover', handleCardDragOver);
  card.addEventListener('dragleave', handleCardDragLeave);
  card.addEventListener('drop', handleCardDrop);

  let sourceTagHtml = '';
  if (task.source === 'rollover') {
    sourceTagHtml = `<span class="source-tag rollover">⚠️ 今日顺延</span>`;
  } else if (task.source === 'tomorrow') {
    sourceTagHtml = `<span class="source-tag tomorrow">明日待办</span>`;
  } else if (task.source === 'future') {
    sourceTagHtml = `<span class="source-tag future">远期设想</span>`;
  }

  let engineTagHtml = '';
  if (task.engine === 'ai') {
    engineTagHtml = `<span class="card-engine-tag ai">AI判定</span>`;
  } else if (task.engine === 'fallback') {
    engineTagHtml = `<span class="card-engine-tag fallback">规则兜底</span>`;
  }

  card.innerHTML = `
    <div class="card-top">
      <div style="display: flex; align-items: center; gap: 5px;">
        ${sourceTagHtml}
        ${engineTagHtml}
      </div>
      <div class="card-actions-quick">
        <button class="btn-card-icon" title="标记已完成" onclick="markTaskDone('${task.id}')">✓</button>
        <button class="btn-card-icon delete" title="删除" onclick="deleteTask('${task.id}')">✕</button>
      </div>
    </div>
    <div class="task-title" contenteditable="true" onblur="handleTitleEdit('${task.id}', this)">${escapeHtml(task.title)}</div>
    ${taskMetaHtml(task)}
    ${task.reason ? `<div class="task-reason">💡 ${escapeHtml(task.reason)}</div>` : ''}
    ${task.pendingProbe ? `<div class="task-pending-probe">${escapeHtml(task.pendingProbe)}</div>` : ''}
    ${eventAdviceHtml(task)}
  `;

  return card;
}

function createDoneCardElement(task) {
  const el = document.createElement('div');
  el.className = 'done-card-mini';
  // 归档卡片也设为可拖拽：支持直接拖回任一象限
  el.setAttribute('draggable', 'true');
  el.setAttribute('data-id', task.id);
  el.addEventListener('dragstart', handleDragStart);
  el.addEventListener('dragend', handleDragEnd);

  const quadNames = {
    q1: 'Q1必做',
    q2: 'Q2排期',
    q3: 'Q3授权',
    q4: 'Q4延后/砍掉',
    candidate: '备选区'
  };
  const targetLabel = task.originalQuadrant ? (quadNames[task.originalQuadrant] || '原象限') : '备选区';

  el.innerHTML = `
    <div class="done-card-left">
      <span class="done-check-icon">✓</span>
      <span class="done-title-text" title="${escapeHtml(task.title)}">${escapeHtml(task.title)}</span>
    </div>
    <div class="done-actions">
      <button class="btn-restore-task" onclick="restoreTask('${task.id}')" title="恢复回 ${targetLabel}">↩ 恢复</button>
      <button class="btn-delete-done" onclick="deleteTask('${task.id}')" title="彻底删除">✕</button>
    </div>
  `;
  return el;
}

// ============================================================================
// 拖拽核心实现 (HTML5 Drag & Drop - 跨象限、同区排序与归档拖回)
// ============================================================================
let draggedTaskId = null;

function handleDragStart(e) {
  draggedTaskId = this.getAttribute('data-id');
  this.classList.add('dragging');
  e.dataTransfer.setData('text/plain', draggedTaskId);
  e.dataTransfer.effectAllowed = 'move';
}

function handleDragEnd(e) {
  this.classList.remove('dragging');
  document.querySelectorAll('.quadrant, .candidate-dock, .done-section-dock').forEach(el => {
    el.classList.remove('drag-over');
  });
  document.querySelectorAll('.task-card').forEach(el => {
    el.classList.remove('drag-over-top', 'drag-over-bottom');
  });
}

// 卡片悬停：计算鼠标在卡片上半部还是下半部，显示上下插入高亮线
function handleCardDragOver(e) {
  e.preventDefault();
  e.stopPropagation();
  e.dataTransfer.dropEffect = 'move';
  const targetCard = e.currentTarget;
  if (!draggedTaskId || targetCard.getAttribute('data-id') === draggedTaskId) return;

  const rect = targetCard.getBoundingClientRect();
  const midY = rect.top + rect.height / 2;
  if (e.clientY < midY) {
    targetCard.classList.add('drag-over-top');
    targetCard.classList.remove('drag-over-bottom');
  } else {
    targetCard.classList.add('drag-over-bottom');
    targetCard.classList.remove('drag-over-top');
  }
}

function handleCardDragLeave(e) {
  e.currentTarget.classList.remove('drag-over-top', 'drag-over-bottom');
}

// 在卡片上释放：实现同象限内精准排序，或精准插入目标象限的位置
function handleCardDrop(e) {
  e.preventDefault();
  e.stopPropagation();
  const targetCard = e.currentTarget;
  const isInsertBefore = targetCard.classList.contains('drag-over-top');
  targetCard.classList.remove('drag-over-top', 'drag-over-bottom');

  const targetId = targetCard.getAttribute('data-id');
  if (!draggedTaskId || targetId === draggedTaskId) return;

  const draggedTask = AppState.tasks.find(t => t.id === draggedTaskId);
  const targetTask = AppState.tasks.find(t => t.id === targetId);
  if (!draggedTask || !targetTask) return;

  // 1. 若是从归档区拖出来的任务，恢复为未归档
  if (draggedTask.isDone) {
    draggedTask.isDone = false;
  }

  // 2. 变更象限为目标卡片所在象限
  applyUserMove(draggedTask, targetTask.quadrant);
  if (draggedTask.quadrant === 'candidate' && !draggedTask.pendingProbe) {
    draggedTask.pendingProbe = '❓ 反问：该事项是否已明确截止日期与主要验收人？若两周不推会有损失吗？';
  }

  // 3. 数组排序重组：将 draggedTask 插入在 targetTask 的前或后
  AppState.tasks = AppState.tasks.filter(t => t.id !== draggedTaskId);
  const targetIndex = AppState.tasks.findIndex(t => t.id === targetId);
  if (targetIndex !== -1) {
    const insertIndex = isInsertBefore ? targetIndex : targetIndex + 1;
    AppState.tasks.splice(insertIndex, 0, draggedTask);
  } else {
    AppState.tasks.push(draggedTask);
  }

  saveTasksToStorage();
  updateStatsAndMantra();
  renderMatrixView();
  if (AppState.currentView === 'linear') renderLinearView();
}

// 象限容器悬停
function handleDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  e.currentTarget.classList.add('drag-over');
}

// 释放到象限空白处：追加到该象限末尾
function handleDrop(e, targetQuadrant) {
  e.preventDefault();
  e.currentTarget.classList.remove('drag-over');

  if (!draggedTaskId) return;

  const draggedTask = AppState.tasks.find(t => t.id === draggedTaskId);
  if (!draggedTask) return;

  // 若拖拽的是归档项，将其唤醒恢复
  if (draggedTask.isDone) {
    draggedTask.isDone = false;
  }

  applyUserMove(draggedTask, targetQuadrant);
  if (targetQuadrant === 'candidate' && !draggedTask.pendingProbe) {
    draggedTask.pendingProbe = '❓ 反问：该事项是否已明确截止日期与主要验收人？若两周不推会有损失吗？';
  }

  // 移到同象限末尾
  AppState.tasks = AppState.tasks.filter(t => t.id !== draggedTaskId);
  AppState.tasks.push(draggedTask);

  saveTasksToStorage();
  updateStatsAndMantra();
  renderMatrixView();
  if (AppState.currentView === 'linear') renderLinearView();
}

// 归档区域拖拽事件：支持将活动卡片直接拖入归档
function handleDragOverDone(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  const dock = document.getElementById('done-section-dock');
  if (dock) dock.classList.add('drag-over');
}

function handleDragLeaveDone(e) {
  const dock = document.getElementById('done-section-dock');
  if (dock) dock.classList.remove('drag-over');
}

function handleDropDone(e) {
  e.preventDefault();
  const dock = document.getElementById('done-section-dock');
  if (dock) dock.classList.remove('drag-over');

  if (!draggedTaskId) return;

  const draggedTask = AppState.tasks.find(t => t.id === draggedTaskId);
  if (draggedTask && !draggedTask.isDone) {
    // 拖入归档区：标记完成并保存原始象限
    draggedTask.originalQuadrant = draggedTask.quadrant;
    draggedTask.isDone = true;
    saveTasksToStorage();
    updateStatsAndMantra();
    renderMatrixView();
    if (AppState.currentView === 'linear') renderLinearView();
  }
}

// ============================================================================
// 渲染优先级线性序列 (View 2: Linear Pipeline)
// ============================================================================
// renderLinearView（时间阶梯）已移到 scheduler.js

// ============================================================================
// 数据统计与动态管理者格言 (Stats & Dynamic Mantras)
// ============================================================================
function updateStatsAndMantra() {
  const counts = { q1: 0, q2: 0, q3: 0, q4: 0, candidate: 0, done: 0 };

  AppState.tasks.forEach(t => {
    if (t.isDone || t.source === 'done') {
      counts.done++;
    } else if (counts[t.quadrant] !== undefined) {
      counts[t.quadrant]++;
    }
  });

  document.getElementById('count-q1').textContent = counts.q1;
  document.getElementById('count-q2').textContent = counts.q2;
  document.getElementById('count-q3').textContent = counts.q3;
  document.getElementById('count-q4').textContent = counts.q4;
  document.getElementById('count-candidate').textContent = counts.candidate;
  document.getElementById('count-done').textContent = counts.done;

  if (AppState.mantra) {
    document.getElementById('mantra-text').textContent = AppState.mantra;
  }
}

// ============================================================================
// 任务操作 (Task Operations - 持久化与归档可恢复)
// ============================================================================
function markTaskDone(taskId) {
  const task = AppState.tasks.find(t => t.id === taskId);
  if (task) {
    // 关键：记住原象限，为后续恢复打下基础
    task.originalQuadrant = task.quadrant;
    task.isDone = true;
    saveTasksToStorage();
    updateStatsAndMantra();
    renderMatrixView();
    if (AppState.currentView === 'linear') renderLinearView();
  }
}

function restoreTask(taskId) {
  const task = AppState.tasks.find(t => t.id === taskId);
  if (task) {
    task.isDone = false;
    // 恢复规则：回到原象限；如果原本就是「已完成」来源的条目（没有原象限），则进入备选区，让你重新决定
    if (task.originalQuadrant && ['q1', 'q2', 'q3', 'q4'].includes(task.originalQuadrant)) {
      task.quadrant = task.originalQuadrant;
    } else {
      task.quadrant = 'candidate';
      task.action = 'clarify';
      if (!task.pendingProbe) {
        task.pendingProbe = '❓ 该任务已从归档区恢复，请重新评估其重要性与紧急度。';
      }
    }
    saveTasksToStorage();
    updateStatsAndMantra();
    renderMatrixView();
    if (AppState.currentView === 'linear') renderLinearView();
  }
}

function deleteTask(taskId) {
  AppState.tasks = AppState.tasks.filter(t => t.id !== taskId);
  saveTasksToStorage();
  updateStatsAndMantra();
  renderMatrixView();
  if (AppState.currentView === 'linear') renderLinearView();
}

function handleTitleEdit(taskId, el) {
  const task = AppState.tasks.find(t => t.id === taskId);
  if (task) {
    task.title = el.innerText.trim();
    saveTasksToStorage();
  }
}

function promptAddTask(quadrant) {
  const title = prompt('请输入新事项名称：');
  if (title && title.trim()) {
    const newTask = finalizeFallbackTask(triageSingleTask(title.trim(), 'tomorrow', `t-${Date.now()}`));
    newTask.quadrant = quadrant;
    newTask.aiQuadrant = quadrant;
    newTask.action = defaultActionFor(quadrant);
    newTask.eventId = null;
    newTask.engine = 'manual';
    AppState.tasks.push(newTask);
    saveTasksToStorage();
    updateStatsAndMantra();
    renderMatrixView();
    if (AppState.currentView === 'linear') renderLinearView();
  }
}

// ============================================================================
// 战报卡片渲染与 PNG 图片导出
// ============================================================================
function updateShareCardPreview() {
  const counts = { q1: 0, q2: 0, q3: 0, q4: 0 };
  let q1Highlight = '暂无核心必做事项';
  let q3Highlight = '暂无授权事项';

  AppState.tasks.forEach(t => {
    if (!t.isDone) {
      if (counts[t.quadrant] !== undefined) counts[t.quadrant]++;
      if (t.quadrant === 'q1' && q1Highlight === '暂无核心必做事项') {
        q1Highlight = t.title;
      }
      if (t.quadrant === 'q3' && q3Highlight === '暂无授权事项') {
        q3Highlight = t.title;
      }
    }
  });

  const now = new Date();
  const dateStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;

  document.getElementById('card-date-display').textContent = dateStr;
  document.getElementById('card-count-q1').textContent = counts.q1;
  document.getElementById('card-count-q2').textContent = counts.q2;
  document.getElementById('card-count-q3').textContent = counts.q3;
  document.getElementById('card-count-q4').textContent = counts.q4;

  document.getElementById('card-hl-q1').textContent = q1Highlight;
  document.getElementById('card-hl-q3').textContent = q3Highlight;
  document.getElementById('card-hero-mantra').textContent = `“${AppState.mantra}”`;
}

function downloadCardImage() {
  const canvas = document.getElementById('screenshot-canvas');
  const ctx = canvas.getContext('2d');

  const width = 800;
  const height = 580;
  const scale = 2;
  canvas.width = width * scale;
  canvas.height = height * scale;
  ctx.scale(scale, scale);

  const bgGradient = ctx.createLinearGradient(0, 0, width, height);
  bgGradient.addColorStop(0, '#0f172a');
  bgGradient.addColorStop(1, '#1e293b');
  ctx.fillStyle = bgGradient;
  ctx.fillRect(0, 0, width, height);

  ctx.strokeStyle = '#334155';
  ctx.lineWidth = 2;
  ctx.strokeRect(10, 10, width - 20, height - 20);

  ctx.fillStyle = '#60a5fa';
  ctx.font = 'bold 16px sans-serif';
  ctx.fillText('CCagent · 管理者精力分诊战报', 40, 55);

  const now = new Date();
  const dateStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`;
  ctx.fillStyle = '#94a3b8';
  ctx.font = '14px sans-serif';
  ctx.fillText(dateStr, width - 130, 55);

  ctx.strokeStyle = '#334155';
  ctx.beginPath();
  ctx.moveTo(40, 75);
  ctx.lineTo(width - 40, 75);
  ctx.stroke();

  ctx.fillStyle = '#38bdf8';
  ctx.fillRect(40, 100, 4, 46);

  ctx.fillStyle = '#f8fafc';
  ctx.font = 'bold 18px sans-serif';
  const mantra = AppState.mantra;
  ctx.fillText(`“${mantra.substring(0, 36)}”`, 56, 122);
  if (mantra.length > 36) {
    ctx.fillText(`${mantra.substring(36, 72)}`, 56, 144);
  }

  const counts = {
    q1: document.getElementById('card-count-q1').textContent,
    q2: document.getElementById('card-count-q2').textContent,
    q3: document.getElementById('card-count-q3').textContent,
    q4: document.getElementById('card-count-q4').textContent
  };

  const metricBoxWidth = 165;
  const metricBoxHeight = 85;
  const startY = 175;

  const metricData = [
    { label: '今天必做 (Q1)', num: counts.q1, color: '#f87171' },
    { label: '深度排期 (Q2)', num: counts.q2, color: '#60a5fa' },
    { label: '果断授权 (Q3)', num: counts.q3, color: '#fbbf24' },
    { label: '延后砍掉 (Q4)', num: counts.q4, color: '#94a3b8' }
  ];

  metricData.forEach((m, idx) => {
    const x = 40 + idx * (metricBoxWidth + 20);
    ctx.fillStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.fillRect(x, startY, metricBoxWidth, metricBoxHeight);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.1)';
    ctx.strokeRect(x, startY, metricBoxWidth, metricBoxHeight);

    ctx.fillStyle = m.color;
    ctx.font = 'bold 28px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(m.num, x + metricBoxWidth / 2, startY + 45);

    ctx.fillStyle = '#94a3b8';
    ctx.font = '12px sans-serif';
    ctx.fillText(m.label, x + metricBoxWidth / 2, startY + 70);
  });

  ctx.textAlign = 'left';

  const hlY = 290;
  ctx.fillStyle = 'rgba(0, 0, 0, 0.25)';
  ctx.fillRect(40, hlY, width - 80, 110);
  ctx.strokeStyle = '#334155';
  ctx.strokeRect(40, hlY, width - 80, 110);

  ctx.fillStyle = '#ef4444';
  ctx.font = 'bold 13px sans-serif';
  ctx.fillText('🔴 核心主战场 (必做)：', 60, hlY + 38);
  ctx.fillStyle = '#f1f5f9';
  ctx.font = '14px sans-serif';
  ctx.fillText(document.getElementById('card-hl-q1').textContent.substring(0, 38), 210, hlY + 38);

  ctx.fillStyle = '#f59e0b';
  ctx.font = 'bold 13px sans-serif';
  ctx.fillText('🟡 最强精力释放 (授权)：', 60, hlY + 78);
  ctx.fillStyle = '#f1f5f9';
  ctx.font = '14px sans-serif';
  ctx.fillText(document.getElementById('card-hl-q3').textContent.substring(0, 38), 210, hlY + 78);

  const footerY = 435;
  ctx.strokeStyle = '#334155';
  ctx.beginPath();
  ctx.moveTo(40, footerY);
  ctx.lineTo(width - 40, footerY);
  ctx.stroke();

  ctx.fillStyle = '#f1f5f9';
  ctx.font = 'bold 15px sans-serif';
  ctx.fillText('管理者任务分诊台 · CCagent', 40, footerY + 36);

  ctx.fillStyle = '#94a3b8';
  ctx.font = '12px sans-serif';
  ctx.fillText('拒绝低效 ToDoList · 帮管理者授权、延后与聚焦核心交付', 40, footerY + 58);

  ctx.fillStyle = 'rgba(56, 189, 248, 0.15)';
  ctx.fillRect(width - 170, footerY + 20, 130, 44);
  ctx.strokeStyle = '#38bdf8';
  ctx.strokeRect(width - 170, footerY + 20, 130, 44);

  ctx.fillStyle = '#38bdf8';
  ctx.font = 'bold 14px sans-serif';
  ctx.textAlign = 'center';
  ctx.fillText('⚡ 微信/Coze分诊', width - 105, footerY + 47);

  const link = document.createElement('a');
  link.download = `CCagent_高管任务分诊战报_${dateStr}.png`;
  link.href = canvas.toDataURL('image/png');
  link.click();
}

function renderEventsModal() {
  const container = document.getElementById('events-accordion-list');
  if (!container || !AppState.eventLibrary || AppState.eventLibrary.length === 0) return;

  container.innerHTML = '';
  AppState.eventLibrary.forEach(item => {
    const card = document.createElement('div');
    card.className = 'event-accordion-card';
    card.innerHTML = `
      <div class="event-header" onclick="this.nextElementSibling.classList.toggle('collapsed')">
        <span><strong>${item.id} · ${escapeHtml(item.name)}</strong> [建议：${escapeHtml(item.default_action)}]</span>
        <span>▼</span>
      </div>
      <div class="event-body collapsed">
        <p><strong>识别特征：</strong>${escapeHtml(item.feature)}</p>
        <p><strong>高管处置路径：</strong>${escapeHtml(item.process_path)}</p>
        <div class="script-box">
          <strong>💬 推荐直接开口话术：</strong><br>
          ${escapeHtml(eventScript(item))}
        </div>
        <p style="color:#b91c1c;"><strong>常见踩坑：</strong>${escapeHtml(item.common_mistakes)}</p>
      </div>
    `;
    container.appendChild(card);
  });
}

function openModal(id) {
  document.getElementById(id).classList.add('active');
}

function closeModal(id) {
  document.getElementById(id).classList.remove('active');
}

function copyText(textareaId) {
  const textarea = document.getElementById(textareaId);
  textarea.select();
  document.execCommand('copy');
  alert('提示词已成功复制到剪贴板！可直接粘贴至扣子 (Coze) 或元器后台。');
}

function handleFeedback(type) {
  const thanksEl = document.getElementById('feedback-thanks');
  thanksEl.style.display = 'inline';
  const logs = JSON.parse(localStorage.getItem('ccagent_feedbacks') || '[]');
  logs.push({ type, time: new Date().toISOString() });
  localStorage.setItem('ccagent_feedbacks', JSON.stringify(logs));
  setTimeout(() => {
    thanksEl.style.display = 'none';
  }, 3500);
}

function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}
