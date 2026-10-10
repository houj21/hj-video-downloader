/* AI 视频总结页交互：提交、进度轮询、四段结果渲染、思维导图、SSE 追问、导出 */
(function () {
  'use strict';

  const $ = (sel) => document.querySelector(sel);
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));

  const ICON = {
    check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
    alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12.5"/><line x1="12" y1="16.2" x2="12" y2="16.2"/></svg>',
  };

  /* ---------- toast ---------- */
  let toastTimer = null;
  function toast(msg, type) {
    const el = $('#toast');
    if (!el) return;
    el.className = 'toast is-visible' + (type ? ' is-' + type : '');
    el.innerHTML = (type === 'error' ? ICON.alert : ICON.check) + '<span>' + esc(msg) + '</span>';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { el.className = 'toast'; }, 3200);
  }

  const state = {
    jobId: null,
    pollTimer: null,
    url: '',
    result: null,
    meta: null,
    history: [],
    asking: false,
  };

  const STAGE_ORDER = ['fetching', 'parsing', 'summarizing', 'done'];

  function fmtTs(sec) {
    const n = Math.max(0, Math.round(Number(sec) || 0));
    const h = Math.floor(n / 3600);
    const m = Math.floor((n % 3600) / 60);
    const s = n % 60;
    const mm = String(m).padStart(2, '0');
    const ss = String(s).padStart(2, '0');
    return h ? h + ':' + mm + ':' + ss : mm + ':' + ss;
  }

  /* ---------- 模型配置 ---------- */
  async function loadLlmConfig() {
    const hint = $('#llmHint');
    try {
      const res = await fetch('/api/llm/config');
      const data = await res.json();
      if (data.configured) {
        hint.textContent = '当前模型：' + data.model + ' · ' + data.base_url;
        $('#configGuide').hidden = true;
      } else {
        hint.textContent = '未检测到大模型配置，AI 总结暂不可用';
        $('#configGuide').hidden = false;
      }
      return data.configured;
    } catch (e) {
      if (hint) hint.textContent = '模型配置读取失败';
      return false;
    }
  }

  /* ---------- 进度 ---------- */
  function renderPipeline(stage, percent, failed) {
    const list = $('#pipelineList');
    const current = STAGE_ORDER.indexOf(stage);
    list.querySelectorAll('.pipeline__step').forEach((li, idx) => {
      li.classList.remove('is-active', 'is-done', 'is-error');
      if (failed && idx === Math.max(current, 0)) li.classList.add('is-error');
      else if (stage === 'done' || idx < current) li.classList.add('is-done');
      else if (idx === current) li.classList.add('is-active');
    });
    const bar = $('#progressBar');
    bar.style.width = Math.max(0, Math.min(100, percent || 0)) + '%';
    bar.classList.toggle('is-error', !!failed);
  }

  /* ---------- 渲染结果 ---------- */
  function renderResult() {
    const result = state.result || {};
    const meta = state.meta || {};

    $('#metaTitle').textContent = meta.title || '视频总结';
    const bits = [];
    if (meta.uploader) bits.push('UP：' + meta.uploader);
    if (meta.duration) bits.push('时长：' + fmtTs(meta.duration));
    $('#metaSub').textContent = bits.join(' · ');

    const cover = $('#metaCover');
    if (meta.thumbnail) {
      cover.src = meta.thumbnail;
      cover.alt = meta.title || '视频封面';
      cover.hidden = false;
      cover.onerror = () => { cover.hidden = true; };
    } else {
      cover.hidden = true;
    }

    const link = $('#metaLink');
    if (meta.webpage_url || state.url) {
      link.href = meta.webpage_url || state.url;
    }

    $('#overview').textContent = result.overview || '（模型未返回总览）';
    if (result.degraded) {
      $('#overview').textContent = '模型未返回结构化结果，以下是原始输出：' + (result.overview || '');
    }

    renderTimeline(result.chapters || []);
    renderKeypoints(result.keypoints || []);
    renderMindmap(result.mindmap || '');

    $('#result').hidden = false;
    $('#result').classList.add('is-in');
  }

  function renderTimeline(chapters) {
    const box = $('#timeline');
    box.innerHTML = '';
    if (!chapters.length) {
      box.innerHTML = '<li class="timeline__empty">本次未生成章节（可能是模型输出降级），可查看「核心要点」或重新总结。</li>';
      return;
    }
    chapters.forEach((c) => {
      const li = document.createElement('li');
      li.className = 'timeline__item';
      const jump = jumpUrl(c.start);
      li.innerHTML =
        '<a class="tl-time" href="' + esc(jump) + '" target="_blank" rel="noopener" ' +
        'title="跳转到原视频 ' + fmtTs(c.start) + '">' + fmtTs(c.start) + '</a>' +
        '<div class="tl-body">' +
          '<h3 class="tl-title">' + esc(c.title) + '</h3>' +
          ((c.points && c.points.length)
            ? '<ul class="tl-points">' + c.points.map((p) => '<li>' + esc(p) + '</li>').join('') + '</ul>'
            : '') +
        '</div>';
      box.appendChild(li);
    });
  }

  function jumpUrl(sec) {
    const base = (state.meta && state.meta.webpage_url) || state.url || '#';
    if (base === '#') return '#';
    return base + (base.indexOf('?') === -1 ? '?' : '&') + 't=' + Math.max(0, Math.round(Number(sec) || 0));
  }

  function renderKeypoints(points) {
    const box = $('#keypoints');
    box.innerHTML = '';
    if (!points.length) {
      box.innerHTML = '<p class="timeline__empty">本次未生成核心要点。</p>';
      return;
    }
    points.forEach((p, i) => {
      const div = document.createElement('div');
      div.className = 'kp-card';
      div.innerHTML = '<span class="kp-num">' + (i + 1) + '</span><p class="kp-text">' + esc(p) + '</p>';
      box.appendChild(div);
    });
  }

  /* ---------- 思维导图：Markdown 缩进树 -> 横向曲线导图（ProcessOn 风格 SVG） ---------- */
  const SVGNS = 'http://www.w3.org/2000/svg';
  const MM_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif';
  const MM_COLORS = ['#1777FF', '#16A394', '#7C5CFF', '#E08A00', '#E0537A', '#0EA5E9'];

  const MM = {
    tree: null, host: null, svg: null, layer: null, bounds: null,
    scale: 1, tx: 0, ty: 0, touched: false, collapsed: new Set(), seq: 0, bound: false,
  };

  const mmCtx = document.createElement('canvas').getContext('2d');

  function svgEl(tag, attrs) {
    const el = document.createElementNS(SVGNS, tag);
    if (attrs) {
      Object.keys(attrs).forEach((key) => {
        if (attrs[key] !== null && attrs[key] !== undefined) el.setAttribute(key, attrs[key]);
      });
    }
    return el;
  }

  /* 各层级的字号/尺寸规格 */
  function mmSpec(depth) {
    if (depth === 0) return { shape: 'card', size: 16, weight: 700, h: 46, padX: 22, gapX: 66, gapY: 16 };
    if (depth === 1) return { shape: 'pill', size: 14.5, weight: 600, h: 38, padX: 17, gapX: 54, gapY: 12 };
    if (depth === 2) return { shape: 'text', size: 13.5, weight: 400, h: 32, padX: 12, gapX: 46, gapY: 9 };
    return { shape: 'text', size: 13, weight: 400, h: 30, padX: 12, gapX: 42, gapY: 7 };
  }

  function mmTextWidth(text, spec) {
    mmCtx.font = spec.weight + ' ' + spec.size + 'px ' + MM_FONT;
    return mmCtx.measureText(text).width;
  }

  function parseMindmap(text) {
    const root = [];
    const stack = [{ level: -1, children: root }];
    String(text).split('\n').forEach((line) => {
      if (!line.trim()) return;
      const indent = (line.match(/^[ \t]*/) || [''])[0].replace(/\t/g, '  ').length;
      const level = Math.floor(indent / 2);
      const label = line.trim().replace(/^[-*+]\s*/, '').trim();
      if (!label) return;
      while (stack.length > 1 && stack[stack.length - 1].level >= level) stack.pop();
      const node = { id: 'm' + (MM.seq++), label: label, children: [] };
      stack[stack.length - 1].children.push(node);
      stack.push({ level: level, children: node.children });
    });
    return root;
  }

  function mmCountDesc(node) {
    let count = 0;
    node.children.forEach((child) => { count += 1 + mmCountDesc(child); });
    return count;
  }

  /* 布局：叶子按顺序排 y，父节点取首末子节点中点；x 由父节点右边缘递推 */
  function mmLayout(root) {
    const nodes = [];
    let cursorY = 0;

    function walk(node, depth, parent, color) {
      node.depth = depth;
      node.parent = parent;
      node.color = color;
      node.spec = mmSpec(depth);
      node.w = Math.max(30, Math.round(mmTextWidth(node.label, node.spec)) + node.spec.padX * 2);
      node.h = node.spec.h;
      node.x = parent ? parent.x + parent.w + parent.spec.gapX : 0;

      const kids = MM.collapsed.has(node.id) ? [] : node.children;
      node.hiddenCount = kids.length ? 0 : mmCountDesc(node);
      if (kids.length) {
        kids.forEach((kid, index) => {
          walk(kid, depth + 1, node, depth === 0 ? MM_COLORS[index % MM_COLORS.length] : color);
        });
        node.y = (kids[0].y + kids[kids.length - 1].y) / 2;
      } else {
        node.y = cursorY + node.h / 2;
        cursorY += node.h + node.spec.gapY;
      }
      nodes.push(node);
    }

    walk(root, 0, null, MM_COLORS[0]);

    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    nodes.forEach((node) => {
      minX = Math.min(minX, node.x);
      maxX = Math.max(maxX, node.x + node.w);
      minY = Math.min(minY, node.y - node.h / 2);
      maxY = Math.max(maxY, node.y + node.h / 2);
    });
    const pad = 30;
    const offsetX = pad - minX;
    const offsetY = pad - minY;
    nodes.forEach((node) => { node.x += offsetX; node.y += offsetY; });

    return {
      nodes: nodes,
      bounds: { x: 0, y: 0, w: maxX - minX + pad * 2, h: maxY - minY + pad * 2 },
    };
  }

  function mmNodeGroup(node) {
    let cls = 'mmx-node mmx-' + node.spec.shape;
    if (node.children.length) cls += ' mmx-parent';
    const group = svgEl('g', { class: cls, 'data-id': node.id });

    group.appendChild(svgEl('rect', {
      class: 'mmx-bg',
      x: node.x,
      y: node.y - node.h / 2,
      width: node.w,
      height: node.h,
      rx: node.spec.shape === 'card' ? 12 : (node.spec.shape === 'pill' ? node.h / 2 : 8),
    }));

    const text = svgEl('text', {
      class: 'mmx-txt',
      x: node.x + node.w / 2,
      y: node.y + node.spec.size * 0.35,
      'text-anchor': 'middle',
      'font-family': MM_FONT,
      'font-size': node.spec.size,
      'font-weight': node.spec.weight,
    });
    text.textContent = node.label;
    group.appendChild(text);

    if (node.hiddenCount) {
      const badge = svgEl('g', { class: 'mmx-badge' });
      badge.appendChild(svgEl('circle', { cx: node.x + node.w + 11, cy: node.y, r: 9 }));
      const count = svgEl('text', {
        x: node.x + node.w + 11,
        y: node.y + 3.6,
        'text-anchor': 'middle',
        'font-family': MM_FONT,
        'font-size': 11,
        'font-weight': 600,
      });
      count.textContent = node.hiddenCount;
      badge.appendChild(count);
      group.appendChild(badge);
    }
    return group;
  }

  function mmDraw(nodes) {
    // 先画连线，再画节点，保证节点压在曲线之上
    nodes.forEach((node) => {
      if (!node.parent) return;
      const parent = node.parent;
      const sx = parent.x + parent.w;
      const sy = parent.y;
      const ex = node.x;
      const ey = node.y;
      const k = Math.max(18, (ex - sx) * 0.5);
      MM.layer.appendChild(svgEl('path', {
        d: 'M ' + sx + ' ' + sy + ' C ' + (sx + k) + ' ' + sy + ', ' + (ex - k) + ' ' + ey + ', ' + ex + ' ' + ey,
        fill: 'none',
        stroke: node.color,
        'stroke-width': node.depth === 1 ? 2.4 : 1.7,
        'stroke-linecap': 'round',
        opacity: node.depth === 1 ? 0.85 : 0.55,
      }));
    });
    nodes.forEach((node) => { MM.layer.appendChild(mmNodeGroup(node)); });
  }

  function mmViewport() {
    const rect = MM.host.getBoundingClientRect();
    return { w: Math.round(rect.width), h: Math.round(rect.height) };
  }

  function mmApply() {
    MM.layer.setAttribute('transform',
      'translate(' + MM.tx + ',' + MM.ty + ') scale(' + MM.scale + ')');
  }

  function mmZoomLabel() {
    const label = $('#mmZoom');
    if (label) label.textContent = Math.round(MM.scale * 100) + '%';
  }

  function mmResize() {
    const view = mmViewport();
    MM.svg.setAttribute('viewBox', '0 0 ' + view.w + ' ' + view.h);
    MM.svg.setAttribute('width', view.w);
    MM.svg.setAttribute('height', view.h);
  }

  function mmFit() {
    if (!MM.svg || !MM.bounds) return;
    const view = mmViewport();
    if (view.w < 60 || view.h < 60) return;          // 面板隐藏时尺寸为 0，等 ResizeObserver 再触发
    const bounds = MM.bounds;
    const raw = Math.min((view.w - 32) / bounds.w, (view.h - 32) / bounds.h);
    MM.scale = Math.max(0.2, Math.min(1.1, raw));
    MM.tx = (view.w - bounds.w * MM.scale) / 2 - bounds.x * MM.scale;
    MM.ty = (view.h - bounds.h * MM.scale) / 2 - bounds.y * MM.scale;
    mmApply();
    mmZoomLabel();
  }

  /* 初始视图：内容放得下就整体适应；放不下（窄屏）则用可读比例锚定左侧，靠拖拽查看 */
  function mmHome() {
    if (!MM.svg || !MM.bounds) return;
    const view = mmViewport();
    if (view.w < 60 || view.h < 60) return;
    const bounds = MM.bounds;
    const raw = Math.min((view.w - 32) / bounds.w, (view.h - 32) / bounds.h);
    if (raw >= 0.72) { mmFit(); return; }            // 放得下：整体适应（桌面常规路径）
    MM.scale = 0.9;                                  // 放不下：保证文字可读，其余靠拖拽
    MM.tx = 16 - bounds.x * MM.scale;
    MM.ty = (view.h - bounds.h * MM.scale) / 2 - bounds.y * MM.scale;
    mmApply();
    mmZoomLabel();
  }

  function mmZoomAt(px, py, factor) {
    const next = Math.min(3, Math.max(0.2, MM.scale * factor));
    const ratio = next / MM.scale;
    MM.tx = px - ratio * (px - MM.tx);
    MM.ty = py - ratio * (py - MM.ty);
    MM.scale = next;
    mmApply();
    mmZoomLabel();
  }

  function mmZoomBy(factor) {
    const view = mmViewport();
    mmZoomAt(view.w / 2, view.h / 2, factor);
  }

  /* 首次调用时绑定画布交互（滚轮缩放 / 拖拽平移 / 点击折叠 / 工具栏） */
  function mmSetup() {
    if (MM.bound) return;
    const host = $('#mindmap');
    if (!host) return;
    MM.host = host;
    MM.bound = true;

    host.addEventListener('wheel', (e) => {
      if (!MM.svg) return;
      e.preventDefault();
      const rect = host.getBoundingClientRect();
      MM.touched = true;
      mmZoomAt(e.clientX - rect.left, e.clientY - rect.top, e.deltaY < 0 ? 1.12 : 1 / 1.12);
    }, { passive: false });

    let dragging = false, captured = false, lastX = 0, lastY = 0, moved = 0;
    host.addEventListener('pointerdown', (e) => {
      if (!MM.svg || e.button !== 0) return;
      dragging = true;
      captured = false;
      moved = 0;
      lastX = e.clientX;
      lastY = e.clientY;
      // 这里不能立即 setPointerCapture：Chrome 会把随后的 click 事件重定向到捕获元素，
      // 节点就收不到点击了（折叠功能会失效）。改为真正开始拖拽后才捕获。
    });
    host.addEventListener('pointermove', (e) => {
      if (!dragging) return;
      const dx = e.clientX - lastX;
      const dy = e.clientY - lastY;
      lastX = e.clientX;
      lastY = e.clientY;
      moved += Math.abs(dx) + Math.abs(dy);
      if (moved <= 4) return;                        // 未超过阈值：仍视为点击
      if (!captured) {
        captured = true;
        try { host.setPointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
        host.classList.add('is-panning');
      }
      MM.touched = true;
      MM.tx += dx;
      MM.ty += dy;
      mmApply();
    });
    host.addEventListener('pointerup', (e) => {
      if (!dragging) return;
      dragging = false;
      host.classList.remove('is-panning');
      if (captured) {
        try { host.releasePointerCapture(e.pointerId); } catch (err) { /* 忽略 */ }
        MM.skipClick = true;                         // 拖拽结束不算点击
      }
    });
    host.addEventListener('pointercancel', () => {
      dragging = false;
      captured = false;
      host.classList.remove('is-panning');
    });

    host.addEventListener('click', (e) => {
      if (MM.skipClick) { MM.skipClick = false; return; }
      const group = e.target.closest ? e.target.closest('.mmx-node') : null;
      if (!group || !group.classList.contains('mmx-parent')) return;
      const id = group.getAttribute('data-id');
      if (MM.collapsed.has(id)) MM.collapsed.delete(id);
      else MM.collapsed.add(id);
      mmRender(false);
    });

    const toolbar = document.querySelector('.mm-toolbar');
    if (toolbar) {
      toolbar.addEventListener('click', (e) => {
        const btn = e.target.closest('.mm-tool');
        if (!btn || !MM.svg) return;
        const act = btn.getAttribute('data-mm');
        if (act === 'in') mmZoomBy(1.2);
        if (act === 'out') mmZoomBy(1 / 1.2);
        if (act === 'fit') { MM.touched = false; mmFit(); }
        if (act === 'reset') {
          MM.touched = true;
          MM.scale = 1;
          MM.tx = 20 - MM.bounds.x;
          MM.ty = 20 - MM.bounds.y;
          mmApply();
          mmZoomLabel();
        }
      });
    }

    window.addEventListener('resize', () => {
      if (!MM.svg) return;
      mmResize();
      if (!MM.touched) mmHome();
    });
    if (window.ResizeObserver) {                     // 切到导图 Tab 时尺寸由 0 变正常，需要重新适配
      const observer = new ResizeObserver(() => {
        if (!MM.svg) return;
        mmResize();
        if (!MM.touched) mmHome();
      });
      observer.observe(host);
    }

    window.addEventListener('beforeprint', () => {
      if (!MM.svg || !MM.bounds) return;
      MM.host.classList.add('is-printing');
      MM.layer.setAttribute('transform', '');
      MM.svg.setAttribute('viewBox',
        MM.bounds.x + ' ' + MM.bounds.y + ' ' + MM.bounds.w + ' ' + MM.bounds.h);
    });
    window.addEventListener('afterprint', () => {
      if (!MM.svg) return;
      MM.host.classList.remove('is-printing');
      mmResize();
      if (MM.touched) mmApply(); else mmHome();
    });
  }

  function mmRender(fit) {
    if (!MM.tree) return;
    const layout = mmLayout(MM.tree);
    MM.bounds = layout.bounds;

    const svg = svgEl('svg', { xmlns: SVGNS, preserveAspectRatio: 'xMidYMid meet' });
    const defs = svgEl('defs');
    const grad = svgEl('linearGradient', { id: 'mmRootGrad', x1: '0', y1: '0', x2: '1', y2: '1' });
    grad.appendChild(svgEl('stop', { offset: '0', 'stop-color': '#3D8DFF' }));
    grad.appendChild(svgEl('stop', { offset: '1', 'stop-color': '#0E58D6' }));
    defs.appendChild(grad);
    svg.appendChild(defs);

    MM.layer = svgEl('g');
    svg.appendChild(MM.layer);
    MM.svg = svg;

    MM.host.innerHTML = '';
    MM.host.appendChild(svg);

    mmDraw(layout.nodes);
    mmResize();
    if (fit) mmHome(); else { mmApply(); mmZoomLabel(); }
  }

  function renderMindmap(text) {
    mmSetup();
    MM.seq = 0;
    MM.collapsed = new Set();
    MM.touched = false;

    const raw = parseMindmap(text);
    if (!raw.length) {
      MM.tree = null;
      MM.svg = null;
      MM.host.innerHTML = '<p class="timeline__empty">本次未生成思维导图。</p>';
      return;
    }
    // 模型偶尔会输出多个顶层节点，统一挂到一个虚拟根上，保证是单根横向导图
    MM.tree = raw.length === 1 ? raw[0] : { id: 'mroot', label: '视频要点', children: raw };
    mmRender(true);
  }

  /* ---------- 提交与轮询 ---------- */
  async function startSummarize() {
    const input = $('#urlInput');
    const url = input.value.trim();
    if (!url) {
      toast('请先粘贴视频链接', 'error');
      input.focus();
      return;
    }

    const btn = $('#summarizeBtn');
    btn.disabled = true;
    btn.querySelector('span').textContent = '总结中';
    $('#result').hidden = true;
    $('#pipeline').hidden = false;
    renderPipeline('fetching', 5, false);
    $('#progressText').textContent = '正在提交任务…';

    try {
      const res = await fetch('/api/summarize', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url: url }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '提交失败');
      state.jobId = data.job_id;
      state.url = url;
      state.history = [];
      $('#askLog').innerHTML = '';
      poll();
    } catch (err) {
      btn.disabled = false;
      btn.querySelector('span').textContent = '开始总结';
      renderPipeline('fetching', 100, true);
      $('#progressText').textContent = err.message || '提交失败';
      toast(err.message || '提交失败', 'error');
    }
  }

  function poll() {
    clearInterval(state.pollTimer);
    state.pollTimer = setInterval(tick, 1200);
    tick();
  }

  async function tick() {
    if (!state.jobId) return;
    try {
      const res = await fetch('/api/summary/status/' + state.jobId);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || '任务不存在');

      const failed = data.status === 'error';
      renderPipeline(data.stage || 'fetching', data.percent, failed);
      $('#progressText').textContent = failed
        ? (data.error || '总结失败')
        : (data.stage_text || '处理中…') + '（' + Math.round(data.percent || 0) + '%）';

      if (data.status === 'done') {
        clearInterval(state.pollTimer);
        state.result = data.result;
        state.meta = data.meta || {};
        $('#pipeline').hidden = true;
        renderResult();
        resetButton();
        toast('总结完成', 'success');
      } else if (failed) {
        clearInterval(state.pollTimer);
        resetButton();
        toast(data.error || '总结失败', 'error');
      }
    } catch (err) {
      clearInterval(state.pollTimer);
      renderPipeline('fetching', 100, true);
      $('#progressText').textContent = err.message || '任务查询失败';
      resetButton();
    }
  }

  function resetButton() {
    const btn = $('#summarizeBtn');
    btn.disabled = false;
    btn.querySelector('span').textContent = '开始总结';
  }

  /* ---------- 追问（SSE，POST） ---------- */
  async function ask(question) {
    if (!question || state.asking || !state.jobId) return;
    state.asking = true;
    const btn = $('#askBtn');
    btn.disabled = true;

    appendBubble('user', question);
    const bubble = appendBubble('ai', '');
    $('#askField').value = '';

    const payload = {
      job_id: state.jobId,
      question: question,
      history: state.history.slice(-8),
    };

    let answer = '';
    try {
      const res = await fetch('/api/summary/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
      if (!res.ok || !res.body) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.error || '追问失败');
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder('utf-8');
      let buffer = '';
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';
        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith('data:')) continue;
          let evt;
          try { evt = JSON.parse(line.slice(5).trim()); } catch (e) { continue; }
          if (evt.error) throw new Error(evt.error);
          if (evt.delta) {
            answer += evt.delta;
            bubble.querySelector('.bubble__text').textContent = answer;
            scrollAsk();
          }
        }
      }
      if (!answer) bubble.querySelector('.bubble__text').textContent = '（没有返回内容）';
      else state.history.push({ role: 'user', content: question }, { role: 'assistant', content: answer });
    } catch (err) {
      bubble.querySelector('.bubble__text').textContent = '追问失败：' + (err.message || '请稍后重试');
      toast(err.message || '追问失败', 'error');
    } finally {
      state.asking = false;
      btn.disabled = false;
      scrollAsk();
    }
  }

  function appendBubble(role, text) {
    const log = $('#askLog');
    const div = document.createElement('div');
    div.className = 'bubble bubble--' + role;
    div.innerHTML = '<div class="bubble__text">' + esc(text) + '</div>';
    log.appendChild(div);
    scrollAsk();
    return div;
  }

  function scrollAsk() {
    const log = $('#askLog');
    log.scrollTop = log.scrollHeight;
  }

  /* ---------- 导出 ---------- */
  async function exportRequest(format) {
    const res = await fetch('/api/summary/export', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ job_id: state.jobId, format: format }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.error || '导出失败');
    }
    return res;
  }

  function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function baseName() {
    const title = (state.meta && state.meta.title) || '视频总结';
    return title.replace(/[\\/:*?"<>|]/g, '').trim().slice(0, 60) || '视频总结';
  }

  async function doCopy() {
    try {
      const res = await exportRequest('md');
      const text = await res.text();
      await navigator.clipboard.writeText(text);
      toast('已复制 Markdown', 'success');
    } catch (err) {
      toast(err.message || '复制失败', 'error');
    }
  }

  async function doDownload(format, ext, mime) {
    try {
      const res = await exportRequest(format);
      const blob = await res.blob();
      downloadBlob(blob.slice(0, blob.size, mime), baseName() + '.' + ext);
      toast('已开始下载 .' + ext, 'success');
    } catch (err) {
      toast(err.message || '导出失败', 'error');
    }
  }

  /* ---------- 绑定 ---------- */
  function bind() {
    const burger = $('#burger');
    if (burger) burger.addEventListener('click', () => $('#mobileMenu').classList.toggle('is-open'));

    $('#summarizeBtn').addEventListener('click', startSummarize);
    $('#urlInput').addEventListener('keydown', (e) => { if (e.key === 'Enter') startSummarize(); });

    document.querySelectorAll('.sum-tab').forEach((tab) => {
      tab.addEventListener('click', () => {
        document.querySelectorAll('.sum-tab').forEach((t) => {
          t.classList.toggle('is-active', t === tab);
          t.setAttribute('aria-selected', t === tab ? 'true' : 'false');
        });
        document.querySelectorAll('.sum-panel').forEach((p) => {
          p.classList.toggle('is-active', p.id === 'panel-' + tab.dataset.tab);
        });
      });
    });

    $('#askBtn').addEventListener('click', () => ask($('#askField').value.trim()));
    $('#askField').addEventListener('keydown', (e) => { if (e.key === 'Enter') ask($('#askField').value.trim()); });
    $('#askChips').addEventListener('click', (e) => {
      const chip = e.target.closest('.chip--btn');
      if (chip) ask(chip.dataset.q);
    });

    $('#copyBtn').addEventListener('click', doCopy);
    $('#mdBtn').addEventListener('click', () => doDownload('md', 'md', 'text/markdown'));
    $('#docxBtn').addEventListener('click', () => doDownload('docx', 'docx',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document'));
    $('#pdfBtn').addEventListener('click', () => {
      window.print();
      toast('在打印窗口选择「另存为 PDF」', 'success');
    });
  }

  /* ---------- 初始化（支持 ?url= 深链自动开始） ---------- */
  async function init() {
    bind();
    const configured = await loadLlmConfig();
    const param = new URLSearchParams(location.search).get('url');
    if (param) {
      $('#urlInput').value = param;
      if (configured) startSummarize();
    }
  }

  document.addEventListener('DOMContentLoaded', init);
})();
