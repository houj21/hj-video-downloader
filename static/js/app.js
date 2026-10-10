/* HJ Video Downloader — frontend logic
   Contract (unchanged from upstream ReClip):
     POST /api/info     -> {title, thumbnail, duration, uploader, formats:[{id,label,height}]}
     POST /api/playlist -> {urls:[...]}
     POST /api/download -> {job_id}
     GET  /api/status/<job_id> -> {status, error?, filename?, percent?}
     GET  /api/file/<job_id>   -> attachment
*/

const state = {
  format: 'video',       // video | audio
  cards: [],             // parsed video cards
  queue: [],             // download tasks
  busy: false,
};

const $ = (sel) => document.querySelector(sel);
const HISTORY_KEY = 'hj_dl_history';

/* ---------- helpers ---------- */
function esc(s) {
  const d = document.createElement('div');
  d.textContent = s == null ? '' : String(s);
  return d.innerHTML;
}

function parseUrls(text) {
  const raw = String(text || '').split(/[\s,，、]+/).map((u) => u.trim()).filter(Boolean);
  return [...new Set(raw.filter((u) => u.startsWith('http')))];
}

function fmtDur(s) {
  if (!s) return '';
  const sec = Math.floor(Number(s) || 0);
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const r = sec % 60;
  const mm = String(m).padStart(h ? 2 : 1, '0');
  const ss = String(r).padStart(2, '0');
  return h ? `${h}:${mm}:${ss}` : `${mm}:${ss}`;
}

function friendlyError(err) {
  const e = String(err || '');
  if (e.includes('Unsupported URL')) return '暂不支持该链接，请确认网址是否正确';
  if (e.includes('Video unavailable')) return '视频不可用或已被删除';
  if (e.includes('Private video')) return '该视频为私密内容，无法访问';
  if (e.includes('HTTP Error 403')) return '平台拒绝访问（403），可尝试配置 Cookie';
  if (e.includes('HTTP Error 404')) return '视频不存在（404）';
  if (e.includes('HTTP Error 429')) return '请求过于频繁，请稍后再试';
  if (e.includes('copyright')) return '该视频因版权原因被限制';
  if (e.includes('Sign in') || e.includes('login')) return '该内容需要登录，请在设置中配置 Cookie';
  if (e.includes('geo')) return '该视频在当前地区不可用';
  if (/timed out|Timed out/.test(e)) return '请求超时，请重试';
  if (/network|Network|Connection/.test(e)) return '网络异常，请检查连接';
  return e.length > 90 ? e.slice(0, 90) + '…' : e;
}

const ICON = {
  link: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>',
  download: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>',
  audio: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
  video: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="3" width="20" height="16" rx="3"/><circle cx="8.5" cy="8.5" r="1.6"/><path d="m21 15-5.5-5L5 21"/></svg>',
  check: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
  alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="12.5"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
  clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><polyline points="12 7 12 12 15.5 14"/></svg>',
  crown: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M3 8.5 7 12l5-7 5 7 4-3.5-1.6 9.5H4.6L3 8.5Z"/></svg>',
  spark: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2.5l2.3 6.2H21l-5.2 3.9 1.9 6.4-5.7-4-5.7 4 1.9-6.4L3 8.7h6.7L12 2.5Z"/></svg>',
  bolt: '<svg viewBox="0 0 24 24" fill="currentColor"><path d="M13 2 5 13h5l-1 9 8-11h-5l1-9Z"/></svg>',
};

/* ---------- toast ---------- */
let toastTimer = null;
function toast(msg, type) {
  const el = $('#toast');
  el.className = 'toast is-visible' + (type ? ' is-' + type : '');
  el.innerHTML = (type === 'error' ? ICON.alert : ICON.check) + '<span>' + esc(msg) + '</span>';
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.className = 'toast'; }, 3200);
}

/* ---------- mobile menu ---------- */
function toggleMenu() {
  $('#mobileMenu').classList.toggle('is-open');
}

/* ---------- format switch ---------- */
function setFormat(btn) {
  document.querySelectorAll('.switch__btn').forEach((b) => b.classList.remove('is-active'));
  btn.classList.add('is-active');
  state.format = btn.dataset.format;
  renderCards();
}

function pickFormat(idx, formatId) {
  state.cards[idx].selectedFormatId = formatId;
  renderCards();
}

/* ---------- history ---------- */
function pushHistory(item) {
  try {
    const list = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]');
    const next = [item, ...list.filter((x) => x.url !== item.url)].slice(0, 3);
    localStorage.setItem(HISTORY_KEY, JSON.stringify(next));
  } catch (_) { /* ignore */ }
  renderHistory();
}

function renderHistory() {
  const wrap = $('#history');
  if (!wrap) return;
  let list = [];
  try { list = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]'); } catch (_) { list = []; }
  if (!list.length) { wrap.innerHTML = ''; return; }
  wrap.innerHTML =
    '<span class="history__label">最近解析</span>' +
    list.map((h) => `<button class="history__item" data-url="${esc(h.url)}">${esc(h.title || h.url)}</button>`).join('');
  wrap.querySelectorAll('.history__item').forEach((b) => {
    b.addEventListener('click', () => { $('#urlInput').value = b.dataset.url; });
  });
}

/* ---------- fetch & parse ---------- */
async function go() {
  if (state.busy) return;
  const input = $('#urlInput');
  let urls = parseUrls(input.value);
  if (!urls.length) {
    toast('请先粘贴视频链接', 'error');
    input.focus();
    return;
  }

  state.busy = true;
  const btn = $('#parseBtn');
  btn.disabled = true;
  btn.innerHTML = '<span class="spin"></span> 解析中';

  state.cards = [];
  renderCards();

  // expand playlists / channel links into single video urls
  for (let i = 0; i < urls.length; i++) {
    if (urls[i].includes('list=')) {
      try {
        const res = await fetch('/api/playlist', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url: urls[i] }),
        });
        const data = await res.json();
        if (data.urls && data.urls.length) urls.splice(i, 1, ...data.urls);
      } catch (_) { /* keep original url */ }
    }
  }

  await Promise.all(urls.map(async (url, i) => {
    const idx = state.cards.length;
    state.cards.push({ url, status: 'loading' });
    renderCards();
    try {
      const res = await fetch('/api/info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ url }),
      });
      const data = await res.json();
      if (data.error) {
        state.cards[idx] = { ...state.cards[idx], status: 'info-error', error: data.error };
      } else {
        state.cards[idx] = {
          ...state.cards[idx],
          status: 'ready',
          title: data.title || '',
          thumbnail: data.thumbnail || '',
          duration: data.duration,
          uploader: data.uploader || '',
          formats: data.formats || [],
          selectedFormatId: (data.formats && data.formats[0] && data.formats[0].id) || null,
        };
        pushHistory({ url, title: data.title || '' });
      }
    } catch (err) {
      state.cards[idx] = { ...state.cards[idx], status: 'info-error', error: err.message };
    }
    renderCards();
    void i;
  }));

  const ready = state.cards.filter((c) => c.status === 'ready').length;
  if (ready > 0) toast(`已解析 ${ready} 个视频`, 'success');
  if (ready > 1) $('#downloadAllBar').classList.remove('is-hidden');

  btn.disabled = false;
  btn.innerHTML = ICON.search + '<span>解析</span>';
  state.busy = false;
}

function renderCards() {
  const wrap = $('#cards');
  if (!state.cards.length) {
    wrap.innerHTML = `
      <div class="empty" style="grid-column:1/-1">
        ${ICON.video}
        <div class="empty__title">还没有解析任何视频</div>
        <div class="empty__desc">在上方粘贴链接并点击「解析」，结果会显示在这里</div>
      </div>`;
    return;
  }
  wrap.innerHTML = state.cards.map(cardHtml).join('');
  wrap.querySelectorAll('[data-act="pick"]').forEach((b) => {
    b.addEventListener('click', () => pickFormat(Number(b.dataset.idx), b.dataset.fmt));
  });
  wrap.querySelectorAll('[data-act="dl"]').forEach((b) => {
    b.addEventListener('click', () => downloadCard(Number(b.dataset.idx)));
  });
}

function cardHtml(c, idx) {
  if (c.status === 'loading') {
    return `<div class="skeleton-card">
      <div class="skeleton-thumb"></div>
      <div class="skeleton-line"></div>
      <div class="skeleton-line skeleton-line--short"></div>
    </div>`;
  }

  if (c.status === 'info-error') {
    return `<div class="video-card" style="border-color:rgba(239,68,68,.4)">
      <div class="video-card__thumb" style="display:grid;place-items:center;background:rgba(239,68,68,.05);color:#EF4444">
        ${ICON.alert}
      </div>
      <div class="video-card__body">
        <div class="video-card__title" style="color:#EF4444">解析失败</div>
        <div class="video-card__meta" style="white-space:normal">${esc(friendlyError(c.error))}</div>
        <div class="video-card__meta" style="white-space:normal;word-break:break-all">${esc(c.url)}</div>
      </div>
    </div>`;
  }

  const isAudio = state.format === 'audio';
  let thumb;
  if (isAudio) {
    thumb = `<div class="video-card__thumb-fallback" style="color:var(--brand)">${ICON.audio}</div>`;
  } else if (c.thumbnail) {
    thumb = `<img src="${esc(c.thumbnail)}" alt="" onerror="this.style.display='none'">`;
  } else {
    thumb = `<div class="video-card__thumb-fallback">${ICON.video}</div>`;
  }

  const formats = (!isAudio && c.formats && c.formats.length > 1)
    ? `<div class="video-card__formats">${c.formats.map((f) =>
        `<button class="q-chip${f.id === c.selectedFormatId ? ' is-active' : ''}" data-act="pick" data-idx="${idx}" data-fmt="${esc(f.id)}">${esc(f.label)}</button>`
      ).join('')}</div>`
    : '';

  const queued = state.queue.some((q) => q.url === c.url && q.status === 'downloading');
  const action = queued
    ? `<button class="btn btn--ghost" disabled><span class="spin"></span> 下载中</button>`
    : `<button class="btn btn--primary" data-act="dl" data-idx="${idx}">${ICON.download} ${isAudio ? '下载 MP3' : '下载 MP4'}</button>`;

  // 一键跳到 AI 总结页并自动开始（下载与总结形成闭环）
  const aiAction = `<a class="btn btn--ghost btn--sm" href="/summarize?url=${encodeURIComponent(c.url)}" title="用 AI 总结这个视频">${ICON.spark} 总结</a>`;

  return `<div class="video-card" style="animation-delay:${Math.min(idx * 60, 420)}ms">
    <div class="video-card__thumb">
      ${thumb}
      ${c.duration ? `<span class="video-card__duration">${fmtDur(c.duration)}</span>` : ''}
    </div>
    <div class="video-card__body">
      <div class="video-card__title">${esc(c.title || '未命名视频')}</div>
      <div class="video-card__meta">${esc(c.uploader || '未知来源')}${c.duration ? ' · ' + fmtDur(c.duration) : ''}</div>
      ${formats}
      <div class="video-card__actions">${action}${aiAction}</div>
    </div>
  </div>`;
}

/* ---------- download & queue ---------- */
async function downloadCard(idx) {
  const c = state.cards[idx];
  if (!c || c.status !== 'ready') return;

  const task = {
    jobId: null,
    url: c.url,
    title: c.title || c.url,
    thumbnail: c.thumbnail || '',
    format: state.format,
    status: 'starting',
    percent: 0,
    filename: '',
    error: '',
  };
  state.queue.unshift(task);
  renderCards();
  renderQueue();

  try {
    const res = await fetch('/api/download', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        url: c.url,
        format: state.format,
        format_id: c.selectedFormatId || null,
        title: c.title || '',
      }),
    });
    const data = await res.json();
    if (data.error) {
      task.status = 'error';
      task.error = data.error;
      renderQueue();
      return;
    }
    task.jobId = data.job_id;
    task.status = 'downloading';
    renderQueue();
    poll(task);
  } catch (err) {
    task.status = 'error';
    task.error = err.message;
    renderQueue();
  }
}

async function downloadAll() {
  const btn = $('#downloadAllBtn');
  btn.disabled = true;
  const targets = state.cards.map((c, i) => ({ c, i })).filter((x) => x.c.status === 'ready');
  for (const t of targets) {
    await downloadCard(t.i);
    await new Promise((r) => setTimeout(r, 300));
  }
  btn.disabled = false;
}

function poll(task) {
  const iv = setInterval(async () => {
    try {
      const res = await fetch(`/api/status/${task.jobId}`);
      const data = await res.json();
      if (data.percent != null) task.percent = Number(data.percent) || 0;
      if (data.status === 'done') {
        clearInterval(iv);
        task.status = 'done';
        task.percent = 100;
        task.filename = data.filename || '';
        renderCards();
        renderQueue();
        toast('下载完成，正在保存到本地', 'success');
        saveTask(task);
      } else if (data.status === 'error') {
        clearInterval(iv);
        task.status = 'error';
        task.error = data.error || '下载失败';
        renderCards();
        renderQueue();
        toast(friendlyError(task.error), 'error');
      } else {
        renderQueue();
      }
    } catch (_) {
      clearInterval(iv);
      task.status = 'error';
      task.error = '与服务器断开连接';
      renderCards();
      renderQueue();
    }
  }, 900);
}

function saveTask(task) {
  if (!task.jobId) return;
  const a = document.createElement('a');
  a.href = `/api/file/${task.jobId}`;
  a.download = task.filename || '';
  document.body.appendChild(a);
  a.click();
  a.remove();
}

function renderQueue() {
  const wrap = $('#queue');
  const section = $('#queueSection');
  if (!state.queue.length) {
    section.classList.add('is-hidden');
    wrap.innerHTML = '';
    return;
  }
  section.classList.remove('is-hidden');
  wrap.innerHTML = state.queue.map((t) => {
    const isDone = t.status === 'done';
    const isErr = t.status === 'error';
    const statusText = isDone
      ? '已完成 · 可保存到本地'
      : isErr
        ? friendlyError(t.error || '下载失败')
        : '下载中 ' + (t.percent ? Math.round(t.percent) + '%' : '请稍候');

    const icon = isDone ? ICON.check : isErr ? ICON.alert : ICON.download;
    const progress = (!isDone && !isErr)
      ? `<div class="progress${t.percent ? '' : ' progress--indeterminate'}">
           <div class="progress__bar" style="width:${Math.max(4, t.percent || 0)}%"></div>
         </div>`
      : '';

    const action = isDone
      ? `<button class="btn btn--success" data-save="${t.jobId}" data-filename="${esc(t.filename)}">${ICON.download} 保存到本地</button>`
      : isErr
        ? `<button class="btn btn--ghost" data-retry="${esc(t.url)}">重试</button>`
        : '';

    return `<div class="queue__item${isDone ? ' is-done' : ''}${isErr ? ' is-error' : ''}">
      <div class="queue__icon">${icon}</div>
      <div class="queue__main">
        <div class="queue__title">${esc(t.title)}</div>
        <div class="queue__status ${isDone ? 'is-done' : isErr ? 'is-error' : ''}">${esc(statusText)}</div>
        ${progress}
      </div>
      <div class="queue__action">${action}</div>
    </div>`;
  }).join('');

  wrap.querySelectorAll('[data-save]').forEach((b) => {
    b.addEventListener('click', () => saveTask({ jobId: b.dataset.save, filename: b.dataset.filename }));
  });
  wrap.querySelectorAll('[data-retry]').forEach((b) => {
    b.addEventListener('click', () => {
      const idx = state.cards.findIndex((c) => c.url === b.dataset.retry && c.status === 'ready');
      if (idx >= 0) {
        state.queue = state.queue.filter((q) => !(q.url === b.dataset.retry && q.status === 'error'));
        downloadCard(idx);
      }
    });
  });
}

/* ---------- init (safe for both index & pricing pages) ---------- */
document.addEventListener('DOMContentLoaded', () => {
  const parseBtn = $('#parseBtn');
  const urlInput = $('#urlInput');
  const downloadAllBtn = $('#downloadAllBtn');

  if (parseBtn) parseBtn.addEventListener('click', go);
  if (downloadAllBtn) downloadAllBtn.addEventListener('click', downloadAll);
  if (urlInput) {
    urlInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); go(); }
    });
  }

  document.querySelectorAll('.switch__btn').forEach((b) => {
    b.addEventListener('click', () => setFormat(b));
  });

  const burger = $('#burger');
  if (burger) burger.addEventListener('click', toggleMenu);

  // pricing page: payment not wired yet
  document.querySelectorAll('[data-coming-soon]').forEach((b) => {
    b.addEventListener('click', () => {
      toast(`${b.dataset.comingSoon}支付通道开发中，敬请期待`, 'error');
    });
  });

  if (urlInput) {
    renderHistory();
    renderCards();
    renderQueue();
  }

  // nav scrollspy: highlight 首页 / 支持平台 based on scroll position
  const platformsSection = document.getElementById('platforms');
  if (platformsSection) {
    const navLinks = document.querySelectorAll('.nav__links .nav__link, .mobile-menu a');
    const updateSpy = () => {
      const inPlatforms = window.scrollY + 96 >= platformsSection.offsetTop;
      navLinks.forEach((link) => {
        const href = link.getAttribute('href');
        if (href === '#platforms' || href === '/#platforms') {
          link.classList.toggle('is-active', inPlatforms);
        } else if (href === '/') {
          link.classList.toggle('is-active', !inPlatforms);
        }
      });
    };
    window.addEventListener('scroll', updateSpy, { passive: true });
    window.addEventListener('hashchange', updateSpy);
    updateSpy();
  }
});
