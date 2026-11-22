/**
 * CCagent - 任务字段规范化 / 时间阶梯排程 / 事件库建议
 * 依赖 app.js 里的 AppState 与 escapeHtml（均在运行时才访问）。
 */

const QUADRANTS = ['q1', 'q2', 'q3', 'q4', 'candidate'];
const ACTIONS = ['self', 'delegate', 'defer', 'drop', 'clarify'];
const ACTION_LABELS = { self: '亲自做', delegate: '授权', defer: '延后', drop: '放弃', clarify: '待厘清' };

const SCHEDULE_KEY = 'ccagent_schedule_cfg_v1';
const SCHEDULE_DEFAULTS = {
  start: '09:00',
  end: '18:00',
  lunchStart: '12:00',
  lunchEnd: '13:30',
  batchStart: '16:30',
  batchEnd: '17:30'
};

// ============================================================================
// 字段规范化：把模型或规则引擎的输出收敛成统一结构
// ============================================================================
function defaultActionFor(quadrant) {
  return { q1: 'self', q2: 'self', q3: 'delegate', q4: 'defer', candidate: 'clarify' }[quadrant] || 'self';
}

function defaultMinutes(quadrant) {
  return { q1: 60, q2: 90, q3: 20 }[quadrant] || 30;
}

function validTime(str) {
  if (typeof str !== 'string') return '';
  const m = str.trim().match(/^(\d{1,2})[:：](\d{2})$/);
  if (!m) return '';
  const h = Number(m[1]);
  const mm = Number(m[2]);
  if (h > 23 || mm > 59) return '';
  return `${String(h).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
}

function getEvent(id) {
  if (!id || typeof AppState === 'undefined') return null;
  return (AppState.eventLibrary || []).find(e => e.id === id) || null;
}

function normalizeTask(item, idx, engine) {
  const quadrant = QUADRANTS.includes(item.quadrant) ? item.quadrant : 'q2';
  const source = ['done', 'rollover', 'tomorrow', 'future'].includes(item.source) ? item.source : 'tomorrow';

  let action = ACTIONS.includes(item.action) ? item.action : defaultActionFor(quadrant);
  if (quadrant === 'candidate') action = 'clarify';
  else if (action === 'clarify') action = defaultActionFor(quadrant);

  let est = Math.round(Number(item.estMinutes));
  if (!Number.isFinite(est) || est <= 0) est = defaultMinutes(quadrant);
  est = Math.min(240, Math.max(5, est));
  if (source === 'done') est = 0;

  // 模型编造的 eventId 一律丢弃，只认事件库里真实存在的
  const eventId = getEvent(item.eventId) ? item.eventId : null;

  return {
    id: `${engine}-${Date.now()}-${idx}`,
    title: String(item.title || '').trim() || '（未命名事项）',
    source,
    quadrant,
    aiQuadrant: quadrant,
    action,
    requester: String(item.requester || '').trim(),
    estMinutes: est,
    fixedTime: validTime(item.fixedTime),
    eventId,
    reason: String(item.reason || ''),
    pendingProbe: quadrant === 'candidate' ? String(item.pendingProbe || '') : '',
    isDone: source === 'done',
    engine
  };
}

// 规则兜底引擎：补齐与 AI 结果相同的字段
function parseFixedTime(title) {
  const re = /(上午|早上|中午|下午|晚上)?\s*(\d{1,2})(?:[:：](\d{2})|点(半|\d{1,2})?)(?!\s*(?:前|之前|以前))/;
  const m = String(title).match(re);
  if (!m) return '';
  let h = Number(m[2]);
  let min = 0;
  if (m[3]) min = Number(m[3]);
  else if (m[4] === '半') min = 30;
  else if (m[4]) min = Number(m[4]);
  const period = m[1];
  if ((period === '下午' || period === '晚上') && h < 12) h += 12;
  else if (period === '中午' && h < 11) h += 12;
  else if (!period && h >= 1 && h <= 7) h += 12; // 无前缀的 1~7 点，按工作日习惯视为下午
  if (h > 23 || min > 59) return '';
  return `${String(h).padStart(2, '0')}:${String(min).padStart(2, '0')}`;
}

function finalizeFallbackTask(t) {
  t.aiQuadrant = t.quadrant;
  t.action = t.quadrant === 'candidate' ? 'clarify' : defaultActionFor(t.quadrant);
  t.requester = t.requester || '';
  t.estMinutes = t.source === 'done' ? 0 : (t.estMinutes || defaultMinutes(t.quadrant));
  t.fixedTime = t.fixedTime || (t.source === 'done' ? '' : parseFixedTime(t.title));
  t.eventId = getEvent(t.eventId) ? t.eventId : null;
  return t;
}

// 旧版本缓存里的任务没有新字段，载入时补齐，避免刷新后排程和卡片展示出错
function migrateTask(t) {
  if (!t.action) t.action = defaultActionFor(t.quadrant);
  if (!t.estMinutes && t.source !== 'done') t.estMinutes = defaultMinutes(t.quadrant);
  if (t.fixedTime === undefined) t.fixedTime = t.source === 'done' ? '' : parseFixedTime(t.title || '');
  if (t.requester === undefined) t.requester = '';
  if (t.eventId === undefined) t.eventId = null;
  if (!t.aiQuadrant) t.aiQuadrant = t.quadrant;
  return t;
}

// 用户手动拖拽后，处理动作跟着象限走，并记录这是人工调整（后续做测试埋点要用）
function applyUserMove(task, quadrant) {
  if (task.quadrant !== quadrant) {
    task.quadrant = quadrant;
    task.action = defaultActionFor(quadrant);
    task.userMoved = true;
  }
}

// ============================================================================
// 事件库建议
// ============================================================================
function eventScript(ev) {
  const s = ev.script_template || {};
  return s.to_subordinate || s.to_peer || s.to_boss || s.to_self || s.to_host || s.to_team || s.to_client || Object.values(s)[0] || '';
}

function toggleEventBody(headEl) {
  const body = headEl.nextElementSibling;
  if (body) body.classList.toggle('collapsed');
}

function eventAdviceHtml(task) {
  if (task.engine === 'manual' || task.isDone) return '';
  const ev = task.eventId ? getEvent(task.eventId) : null;
  if (!ev) {
    if (task.quadrant === 'candidate') return '';
    return `<div class="event-nomatch">📚 库中暂无该类型的专项建议</div>`;
  }
  const qs = (ev.evaluation_questions || []).map(q => `<li>${escapeHtml(q)}</li>`).join('');
  const script = eventScript(ev);
  return `
    <div class="task-event">
      <div class="task-event-head" onclick="toggleEventBody(this)">
        <span>📚 ${escapeHtml(ev.id)} · ${escapeHtml(ev.name)} · 建议：${escapeHtml(ev.default_action || '')}</span>
        <span class="evt-arrow">▾</span>
      </div>
      <div class="task-event-body collapsed">
        <p><strong>怎么做：</strong>${escapeHtml(ev.process_path || '')}</p>
        ${script ? `<div class="script-box"><strong>💬 开口话术：</strong><br>${escapeHtml(script)}</div>` : ''}
        ${qs ? `<div><strong>先问自己：</strong><ul class="evt-qs">${qs}</ul></div>` : ''}
        ${ev.common_mistakes ? `<p class="evt-warn"><strong>常见踩坑：</strong>${escapeHtml(ev.common_mistakes)}</p>` : ''}
        ${ev.conditions ? `<p class="evt-cond"><strong>适用：</strong>${escapeHtml(ev.conditions)}</p>` : ''}
        ${ev.invalidation_conditions ? `<p class="evt-cond"><strong>不适用：</strong>${escapeHtml(ev.invalidation_conditions)}</p>` : ''}
        ${ev.compliance_note ? `<p class="evt-warn"><strong>合规提示：</strong>${escapeHtml(ev.compliance_note)}</p>` : ''}
      </div>
    </div>`;
}

function taskMetaHtml(task) {
  if (task.isDone) return '';
  const chips = [];
  if (task.action) chips.push(`<span class="meta-chip action-${task.action}">${ACTION_LABELS[task.action] || task.action}</span>`);
  if (task.requester) chips.push(`<span class="meta-chip">谁在要：${escapeHtml(task.requester)}</span>`);
  if (task.estMinutes) chips.push(`<span class="meta-chip">⏱ ${task.estMinutes} 分钟</span>`);
  if (task.fixedTime) chips.push(`<span class="meta-chip fixed">🕑 ${escapeHtml(task.fixedTime)}</span>`);
  return chips.length ? `<div class="task-meta">${chips.join('')}</div>` : '';
}

// ============================================================================
// 时间阶梯排程
// ============================================================================
function toMin(hhmm) {
  const [h, m] = String(hhmm).split(':').map(Number);
  return h * 60 + m;
}

function fmt(min) {
  const h = Math.floor(min / 60);
  const m = min % 60;
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
}

function fmtDuration(min) {
  if (min < 60) return `${min} 分钟`;
  const h = Math.floor(min / 60);
  const m = min % 60;
  return m ? `${h} 小时 ${m} 分` : `${h} 小时`;
}

function validateScheduleConfig(c) {
  const keys = ['start', 'end', 'lunchStart', 'lunchEnd', 'batchStart', 'batchEnd'];
  if (!keys.every(k => validTime(c[k]))) return false;
  return toMin(c.start) < toMin(c.end)
    && toMin(c.lunchStart) <= toMin(c.lunchEnd)
    && toMin(c.batchStart) < toMin(c.batchEnd);
}

function getScheduleConfig() {
  try {
    const raw = JSON.parse(localStorage.getItem(SCHEDULE_KEY) || '{}');
    const cfg = { ...SCHEDULE_DEFAULTS, ...raw };
    if (validateScheduleConfig(cfg)) return cfg;
  } catch (e) { /* 使用默认值 */ }
  return { ...SCHEDULE_DEFAULTS };
}

function subtractInterval(free, s, e) {
  const out = [];
  for (const [a, b] of free) {
    if (e <= a || s >= b) { out.push([a, b]); continue; }
    if (s > a) out.push([a, s]);
    if (e < b) out.push([e, b]);
  }
  return out;
}

function sumIntervals(free) {
  return free.reduce((acc, [a, b]) => acc + (b - a), 0);
}

// 在允许范围 [lo, hi] 内，从前往后取空档；允许拆成多段，但每段至少 25 分钟（任务本身更短则整体放入）
function allocate(free, est, lo, hi) {
  const segs = [];
  let rem = est;
  for (const [a, b] of free) {
    if (rem <= 0) break;
    const s = Math.max(a, lo);
    const e = Math.min(b, hi);
    const len = e - s;
    if (len <= 0) continue;
    if (len < Math.min(25, rem)) continue;
    const take = Math.min(len, rem);
    segs.push([s, s + take]);
    rem -= take;
  }
  return rem > 0 ? null : segs;
}

function buildSchedule(tasks, cfg) {
  const S = toMin(cfg.start);
  const E = toMin(cfg.end);
  const L1 = toMin(cfg.lunchStart);
  const L2 = toMin(cfg.lunchEnd);
  const B1 = toMin(cfg.batchStart);
  const B2 = toMin(cfg.batchEnd);

  let free = [[S, E]];
  const hasLunch = L2 > L1 && L2 > S && L1 < E;
  if (hasLunch) free = subtractInterval(free, L1, L2);

  const res = {
    blocks: [],
    overflow: [],
    candidates: [],
    deferDrop: [],
    conflicts: [],
    capacity: sumIntervals(free),
    planned: 0,
    overflowMinutes: 0,
    lunch: hasLunch ? { start: Math.max(L1, S), end: Math.min(L2, E) } : null,
    range: { S, E, B1, B2 }
  };

  const minutesOf = t => {
    const m = Number(t.estMinutes) || defaultMinutes(t.quadrant);
    return t.action === 'delegate' ? Math.min(m, 30) : m;
  };
  const isBatch = t => t.action === 'delegate' || t.quadrant === 'q3';

  const eligible = [];
  tasks.forEach(t => {
    if (t.isDone || t.source === 'done') return;
    if (t.quadrant === 'candidate' || t.action === 'clarify') { res.candidates.push(t); return; }
    if (t.quadrant === 'q4' || t.action === 'defer' || t.action === 'drop') { res.deferDrop.push(t); return; }
    eligible.push(t);
  });

  // 1. 固定时间的事项先落位（只有本人要参加的才算固定块；授权出去的会议不占我的时间）
  const placed = new Set();
  eligible.forEach(t => {
    if (!t.fixedTime || t.action === 'delegate') return;
    const s = toMin(t.fixedTime);
    const e = s + minutesOf(t);
    const block = { task: t, start: s, end: e, kind: 'fixed', part: 1, parts: 1, outOfHours: s < S || e > E };
    res.blocks.forEach(b => {
      if (b.kind === 'fixed' && s < b.end && e > b.start) res.conflicts.push([b.task, t]);
    });
    res.blocks.push(block);
    free = subtractInterval(free, s, e);
    res.planned += e - s;
    placed.add(t.id);
  });

  const commit = (t, segs, kind, spill) => {
    segs.forEach(([s, e], i) => {
      res.blocks.push({ task: t, start: s, end: e, kind, part: i + 1, parts: segs.length, spill: Boolean(spill) });
      free = subtractInterval(free, s, e);
      res.planned += e - s;
    });
  };

  const rank = { q1: 1, q2: 2, q3: 3 };
  const rest = eligible.filter(t => !placed.has(t.id)).sort((a, b) => rank[a.quadrant] - rank[b.quadrant]);

  // 2. 专注类（q1 先于 q2）：优先避开批处理窗口，放不下再占用
  rest.filter(t => !isBatch(t)).forEach(t => {
    const est = minutesOf(t);
    const segs = allocate(subtractInterval(free, B1, B2), est, S, E) || allocate(free, est, S, E);
    if (!segs) { res.overflow.push(t); res.overflowMinutes += est; return; }
    commit(t, segs, 'focus');
  });

  // 3. 批处理/授权类：先进批处理窗口，窗口满了顺延到其他空档，仍放不下才算排不下
  rest.filter(isBatch).forEach(t => {
    const est = minutesOf(t);
    let segs = allocate(free, est, B1, B2);
    let spill = false;
    if (!segs) { segs = allocate(free, est, S, E); spill = Boolean(segs); }
    if (!segs) { res.overflow.push(t); res.overflowMinutes += est; return; }
    commit(t, segs, 'batch', spill);
  });

  res.blocks.sort((a, b) => a.start - b.start);
  return res;
}

// ============================================================================
// 渲染：时间阶梯
// ============================================================================
function scheduleRowHtml(b) {
  const t = b.task;
  const part = b.parts > 1 ? `<span class="sch-part">（${b.part}/${b.parts}）</span>` : '';
  const kindLabel = b.kind === 'fixed' ? '固定时间' : (b.kind === 'batch' ? (b.spill ? '批处理（窗口已满，顺延）' : '批处理') : '专注块');
  const warn = b.outOfHours ? `<span class="sch-flag">超出工作时段</span>` : '';
  return `
    <div class="sch-row">
      <div class="sch-time">${fmt(b.start)}<small>${fmt(b.end)}</small></div>
      <div class="sch-block sch-${t.quadrant} sch-kind-${b.kind}">
        <div class="sch-block-head">
          <div class="sch-title">${escapeHtml(t.title)}${part}</div>
          <button class="btn-card-icon" title="标记完成" onclick="markTaskDone('${t.id}')">✓</button>
        </div>
        <div class="sch-sub"><span class="sch-kind">${kindLabel}</span>${warn}</div>
        ${taskMetaHtml(t)}
        ${t.reason ? `<div class="task-reason">💡 ${escapeHtml(t.reason)}</div>` : ''}
        ${b.part === 1 ? eventAdviceHtml(t) : ''}
      </div>
    </div>`;
}

function renderLinearView() {
  const container = document.getElementById('linear-timeline-container');
  if (!container) return;

  const cfg = getScheduleConfig();
  const sch = buildSchedule(AppState.tasks, cfg);
  const total = sch.blocks.length + sch.overflow.length + sch.candidates.length + sch.deferDrop.length;

  if (total === 0) {
    container.innerHTML = '<div style="text-align:center; padding:40px; color:#94a3b8;">当前暂无待办事项，请先在上方输入任务并点击一键智能分诊！</div>';
    return;
  }

  let html = '';

  // 概览
  const q1Overflow = sch.overflow.some(t => t.quadrant === 'q1');
  html += `<div class="sch-summary ${sch.overflow.length ? 'sch-warn' : 'sch-ok'}">
    <div>可用 <strong>${fmtDuration(sch.capacity)}</strong> · 已排 <strong>${fmtDuration(sch.planned)}</strong> · 排不下 <strong>${sch.overflow.length}</strong> 项${sch.overflow.length ? `（约 ${fmtDuration(sch.overflowMinutes)}）` : ''}</div>
    ${q1Overflow ? '<div class="sch-alert">⚠️ 有「必做」事项排不下。先做减法：授权、缩小范围或降级，而不是加班。</div>' : ''}
    ${sch.conflicts.length ? `<div class="sch-alert">⚠️ 固定时间冲突：${sch.conflicts.map(([a, b]) => `「${escapeHtml(a.title)}」与「${escapeHtml(b.title)}」`).join('、')}</div>` : ''}
  </div>`;

  // 时间轴
  const rows = sch.blocks.map(b => ({ start: b.start, end: b.end, html: scheduleRowHtml(b) }));
  if (sch.lunch) {
    rows.push({
      start: sch.lunch.start,
      end: sch.lunch.end,
      html: `<div class="sch-row"><div class="sch-time">${fmt(sch.lunch.start)}<small>${fmt(sch.lunch.end)}</small></div><div class="sch-lunch">🍱 午休</div></div>`
    });
  }
  rows.sort((a, b) => a.start - b.start);

  let cursor = sch.range.S;
  let timeline = '';
  rows.forEach(r => {
    if (r.start - cursor >= 10) {
      timeline += `<div class="sch-row"><div class="sch-time muted">${fmt(cursor)}</div><div class="sch-gap">空档 ${fmtDuration(r.start - cursor)}（留给突发事项和缓冲）</div></div>`;
    }
    timeline += r.html;
    cursor = Math.max(cursor, r.end);
  });
  if (sch.range.E - cursor >= 10) {
    timeline += `<div class="sch-row"><div class="sch-time muted">${fmt(cursor)}</div><div class="sch-gap">空档 ${fmtDuration(sch.range.E - cursor)}（留给突发事项和缓冲）</div></div>`;
  }
  html += `<div class="sch-timeline">${timeline || '<div class="sch-gap">今天没有可排入的事项</div>'}</div>`;

  // 排不下
  if (sch.overflow.length) {
    const tip = t => t.quadrant === 'q3' ? '建议集中授权，或明天批处理' : (t.quadrant === 'q2' ? '建议延后到明天第一个专注块' : '最危险：必须砍掉别的，或找人分担');
    html += `<div class="sch-section sch-section-warn"><h4>🚫 今天排不下（${sch.overflow.length} 项）</h4>`;
    sch.overflow.forEach(t => {
      html += `<div class="sch-side-item"><div><strong>${escapeHtml(t.title)}</strong> <span class="meta-chip">⏱ ${t.estMinutes} 分钟</span></div><div class="sch-side-reason">${tip(t)}</div>${eventAdviceHtml(t)}</div>`;
    });
    html += `</div>`;
  }

  // 砍掉清单
  if (sch.deferDrop.length) {
    html += `<div class="sch-section"><h4>✂️ 不进入今天：延后 / 放弃（${sch.deferDrop.length} 项）</h4>`;
    sch.deferDrop.forEach(t => {
      html += `<div class="sch-side-item"><div><span class="meta-chip action-${t.action}">${ACTION_LABELS[t.action] || '延后'}</span> <strong>${escapeHtml(t.title)}</strong></div>${t.reason ? `<div class="sch-side-reason">💡 ${escapeHtml(t.reason)}</div>` : ''}${eventAdviceHtml(t)}</div>`;
    });
    html += `</div>`;
  }

  // 待厘清
  if (sch.candidates.length) {
    html += `<div class="sch-section"><h4>📦 待厘清：先想清楚再排（${sch.candidates.length} 项）</h4>`;
    sch.candidates.forEach(t => {
      html += `<div class="sch-side-item"><div><strong>${escapeHtml(t.title)}</strong></div>${t.pendingProbe ? `<div class="task-pending-probe">${escapeHtml(t.pendingProbe)}</div>` : ''}</div>`;
    });
    html += `</div>`;
  }

  container.innerHTML = html;
}

// ============================================================================
// 排程设置（上下班、午休、批处理时段）
// ============================================================================
function initScheduleConfigUI() {
  const map = {
    start: 'cfg-sch-start',
    end: 'cfg-sch-end',
    lunchStart: 'cfg-sch-lunch-start',
    lunchEnd: 'cfg-sch-lunch-end',
    batchStart: 'cfg-sch-batch-start',
    batchEnd: 'cfg-sch-batch-end'
  };
  const cfg = getScheduleConfig();
  Object.entries(map).forEach(([key, id]) => {
    const input = document.getElementById(id);
    if (!input) return;
    input.value = cfg[key];
    input.addEventListener('change', () => {
      const next = { ...getScheduleConfig(), [key]: input.value };
      if (validateScheduleConfig(next)) {
        localStorage.setItem(SCHEDULE_KEY, JSON.stringify(next));
      } else {
        alert('时间设置不合理：下班需晚于上班，批处理结束需晚于开始。已恢复为上一次的设置。');
        input.value = getScheduleConfig()[key];
      }
      renderLinearView();
    });
  });
}

if (typeof document !== 'undefined') {
  document.addEventListener('DOMContentLoaded', initScheduleConfigUI);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { migrateTask, finalizeFallbackTask, buildSchedule, normalizeTask, parseFixedTime, validTime, defaultActionFor, validateScheduleConfig, SCHEDULE_DEFAULTS, subtractInterval, allocate };
}
