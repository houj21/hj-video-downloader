/* ============================================================
 * membership.js —— 登录注册 / 下单跳转 / 支付结果轮询
 * 约定：页面需在 <head> 提供 <meta name="csrf-token" content="{{ csrf_token }}">
 *      挂在 window.HJ 上供 summary.js 复用；所有 DOM 操作都做判空
 * ============================================================ */
(function () {
  'use strict';

  var $ = function (sel) { return document.querySelector(sel); };

  var ICON = {
    error: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><line x1="12" y1="8" x2="12" y2="13"/><line x1="12" y1="16.5" x2="12.01" y2="16.5"/></svg>',
    success: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="9"/><polyline points="8 12.5 11 15.5 16 9"/></svg>'
  };

  function esc(s) {
    var d = document.createElement('div');
    d.textContent = (s === null || s === undefined) ? '' : String(s);
    return d.innerHTML;
  }

  var toastTimer = null;
  function toast(msg, type) {
    var el = $('#toast');
    if (!el) return;
    el.className = 'toast is-visible' + (type ? ' is-' + type : '');
    el.innerHTML = (type === 'error' ? ICON.error : ICON.success) + '<span>' + esc(msg) + '</span>';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { el.className = 'toast'; }, 3200);
  }

  function token() {
    var m = document.querySelector('meta[name="csrf-token"]');
    if (m) return m.getAttribute('content') || '';
    // 兜底：导航栏组件上携带的 data-csrf（页面未放 meta 时也能取到）
    var holder = document.querySelector('[data-csrf]');
    return holder ? (holder.getAttribute('data-csrf') || '') : '';
  }

  function request(url, options) {
    var opts = options || {};
    var headers = { 'Content-Type': 'application/json' };
    var t = token();
    if (t) headers['X-CSRF-Token'] = t;
    Object.keys((opts.headers) || {}).forEach(function (k) { headers[k] = opts.headers[k]; });
    var merged = { method: opts.method || 'GET', headers: headers, credentials: 'same-origin' };
    if (opts.body !== undefined) merged.body = opts.body;
    return fetch(url, merged);
  }

  function readJson(res) { return res.json().catch(function () { return {}; }); }
  function get(url) { return request(url, { method: 'GET' }); }
  function post(url, body) { return request(url, { method: 'POST', body: JSON.stringify(body || {}) }); }

  function call(url, body) {
    return post(url, body).then(function (res) {
      return readJson(res).then(function (data) {
        if (!res.ok) {
          var err = new Error(data.error || '操作失败');
          err.code = data.code || '';
          err.status = res.status;
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  window.HJ = window.HJ || {};
  window.HJ.get = get;
  window.HJ.post = post;
  window.HJ.call = call;
  window.HJ.toast = toast;
  window.HJ.request = request;

  function bindLogout() {
    document.querySelectorAll('[data-logout]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        call('/api/auth/logout', {}).then(function () { window.location.href = '/'; })
          .catch(function () { window.location.href = '/'; });
      });
    });
  }

  /* ---------------- 登录 / 注册 ---------------- */

  var IDLE_TEXT = { login: '登录', register: '注册并继续' };

  function switchAuthTab(tab) {
    document.querySelectorAll('[data-auth-tab]').forEach(function (b) {
      var on = b.dataset.authTab === tab;
      b.classList.toggle('is-active', on);
      b.setAttribute('aria-selected', on ? 'true' : 'false');
    });
    ['login', 'register'].forEach(function (name) {
      var panel = $('#panel-' + name);
      if (panel) panel.hidden = name !== tab;
    });
    var err = $('#authError');
    if (err) { err.hidden = true; err.textContent = ''; }
  }

  /** 取当前激活表单内的元素，避免两个表单重复 ID 互相串扰。 */
  function active(tab) {
    var panel = $('#panel-' + tab);
    if (!panel) return null;
    return panel;
  }

  function btnOf(panel) { return panel ? panel.querySelector('.auth-submit') : null; }
  function textOf(panel) { return panel ? panel.querySelector('.auth-submit__text') : null; }

  function passwordScore(pw) {
    var s = 0;
    if (pw.length >= 8) s += 1;
    if (pw.length >= 12) s += 1;
    if (/[A-Za-z]/.test(pw) && /\d/.test(pw)) s += 1;
    if (/[^A-Za-z0-9]/.test(pw)) s += 1;
    return Math.min(s, 4);
  }

  function bindPasswordToggle() {
    document.querySelectorAll('[data-toggle-pw]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var field = document.getElementById(btn.dataset.togglePw);
        if (!field) return;
        var toText = field.type === 'password';
        field.type = toText ? 'text' : 'password';
        btn.setAttribute('aria-label', toText ? '隐藏密码' : '显示密码');
      });
    });
  }

  function bindStrength() {
    var input = $('#regPassword');
    if (!input) return;
    var bar = $('#pwBar');
    var label = $('#pwLabel');
    input.addEventListener('input', function () {
      if (!bar) return;
      var score = passwordScore(input.value);
      bar.dataset.score = String(score);
      bar.className = 'pw-bar' + (input.value ? ' is-filled' : '');
      if (label) label.textContent = ['太短了', '较弱', '一般', '较强', '很强'][score];
    });
  }

  function showError(msg) {
    var box = $('#authError');
    if (!box) { toast(msg, 'error'); return; }
    box.textContent = msg;
    box.hidden = false;
  }

  function loading(btn, textEl, on, idleText) {
    if (!btn) return;
    btn.disabled = !!on;
    if (textEl) textEl.innerHTML = on ? '<span class="spin"></span>处理中…' : idleText;
  }

  /** 按 tab 取表单作用域 */
  function scope(tab) {
    var panel = active(tab);
    return {
      panel: panel,
      btn: btnOf(panel),
      text: textOf(panel),
      idle: IDLE_TEXT[tab] || '提交'
    };
  }

  function goAfterLogin(nextUrl) {
    if (nextUrl && nextUrl.indexOf('/') === 0 && nextUrl.indexOf('//') !== 0) {
      window.location.href = nextUrl;
      return;
    }
    window.location.href = '/pricing';
  }

  function value(id) {
    var el = document.getElementById(id);
    return el ? (el.value || '') : '';
  }

  function bindAuthForms(nextUrl) {
    var tab = 'login';

    document.querySelectorAll('[data-auth-tab]').forEach(function (b) {
      b.addEventListener('click', function () {
        tab = b.dataset.authTab === 'register' ? 'register' : 'login';
        switchAuthTab(tab);
      });
    });

    ['loginSwitchLink', 'regSwitchLink'].forEach(function (id) {
      var link = document.getElementById(id);
      if (!link) return;
      link.addEventListener('click', function (e) {
        e.preventDefault();
        tab = link.dataset.target === 'register' ? 'register' : 'login';
        switchAuthTab(tab);
      });
    });

    var loginForm = $('#panel-login');
    if (loginForm) {
      loginForm.addEventListener('submit', function (e) {
        e.preventDefault();
        var s = scope('login');
        loading(s.btn, s.text, true, s.idle);
        call('/api/auth/login', { email: value('loginEmail'), password: value('loginPassword') })
          .then(function (data) {
            toast('登录成功' + (data.is_member ? '，终身会员已生效' : ''), 'success');
            setTimeout(function () { goAfterLogin(nextUrl); }, 600);
          })
          .catch(function (err) {
            loading(s.btn, s.text, false, s.idle);
            showError(err.message);
          });
      });
    }

    var regForm = $('#panel-register');
    if (regForm) {
      regForm.addEventListener('submit', function (e) {
        e.preventDefault();
        var pw = value('regPassword');
        var pw2 = value('regPassword2');
        if (pw.length < 8) { showError('密码至少需要 8 位'); return; }
        if (pw !== pw2) { showError('两次输入的密码不一致'); return; }
        var s = scope('register');
        loading(s.btn, s.text, true, s.idle);
        call('/api/auth/register', { email: value('regEmail'), password: pw })
          .then(function () {
            toast('注册成功，已自动登录', 'success');
            setTimeout(function () { goAfterLogin(nextUrl); }, 600);
          })
          .catch(function (err) {
            loading(s.btn, s.text, false, s.idle);
            showError(err.message);
          });
      });
    }

    bindPasswordToggle();
    bindStrength();
    switchAuthTab('login');
  }

  /* ---------------- 定价页下单 ---------------- */

  function bindCheckout() {
    document.querySelectorAll('[data-plan]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.disabled) return;
        var original = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<span class="spin"></span>正在跳转收银台…';
        call('/api/checkout', { plan: btn.dataset.plan }).then(function (data) {
          if (data.checkout_url) window.location.href = data.checkout_url;
        }).catch(function (err) {
          btn.disabled = false;
          btn.innerHTML = original;
          if (err.status === 401) {
            toast('请先登录后再开通', 'error');
            setTimeout(function () { window.location.href = '/account?next=/pricing'; }, 900);
            return;
          }
          if (err.code === 'already_member') {
            toast('你已是终身会员，无需重复购买', 'success');
            btn.textContent = '你已是终身会员';
            btn.disabled = true;
            return;
          }
          toast(err.message, 'error');
        });
      });
    });
  }

  /* ---------------- 支付结果页 ---------------- */

  function bindPayPolling(orderId, canceled) {
    var box = $('#payState');
    var PAY_TEXT = {
      pending: ['正在确认你的支付…', 'Stripe 正在把支付结果同步回来，通常几秒内完成'],
      paid: ['终身会员已开通', 'AI 视频总结、思维导图与字幕下载已全部解锁'],
      failed: ['支付未完成', '订单尚未完成付款，可返回定价页重新尝试'],
      canceled: ['你已取消支付', '没有产生任何扣款，随时可以再来'],
      missing: ['未提供订单信息', '请重新登录后查看订单']
    };

    function setPayState(state, tail) {
      if (!box) return;
      box.dataset.state = state;
      var pair = PAY_TEXT[state] || PAY_TEXT.pending;
      var title = $('#payTitle');
      var desc = $('#payDesc');
      if (title) title.textContent = pair[0];
      if (desc) desc.textContent = tail || pair[1];
    }

    if (canceled) { setPayState('canceled'); return; }
    if (!orderId) { setPayState('missing'); return; }

    var tries = 0;
    setPayState('pending');

    function pollOnce() {
      tries += 1;
      // 第 3 次起带 sync=1：Webhook 未到达时主动向 Stripe 问一次，避免用户干等
      var url = '/api/order/' + encodeURIComponent(orderId) + (tries >= 3 ? '?sync=1' : '');
      get(url).then(function (res) {
        return readJson(res).then(function (data) { return { res: res, data: data }; });
      }).then(function (pair) {
        if (!pair.res.ok) {
          setPayState(pair.res.status === 401 ? 'missing' : 'missing',
            pair.res.status === 401 ? '请重新登录后查看订单' : '');
          return null;
        }
        return pair.data;
      }).then(function (data) {
        if (!data) return;
        if (data.paid || data.is_member) {
          setPayState('paid');
          var detail = $('#payDetail');
          if (detail) {
            detail.hidden = false;
            detail.textContent = '订单号 ' + String(data.order_id || '').slice(-8) +
              ' · ¥' + (Number(data.amount || 0) / 100).toFixed(2);
          }
          // 刷新一次只为更新导航栏的会员徽章；刷新后轮询会再次拿到 paid，
          // 此时用 sessionStorage 标记拦住，避免「查到已支付→reload→再查到→再 reload」的闪烁循环
          var flag = 'hj-pay-reloaded-' + orderId;
          try {
            if (!sessionStorage.getItem(flag)) {
              sessionStorage.setItem(flag, '1');
              setTimeout(function () { window.location.reload(); }, 1200);
            }
          } catch (e) { /* sessionStorage 不可用（如隐私模式）就干脆不刷新，徽章下次跳页时更新 */ }
        } else if (data.status === 'expired' || data.status === 'failed') {
          setPayState('failed');
        } else if (tries < 25) {
          setTimeout(pollOnce, 2000);
        } else {
          setPayState('failed', '等待超时，请返回定价页确认是否已支付');
        }
      }).catch(function () {
        if (tries < 25) setTimeout(pollOnce, 2500);
        else setPayState('failed', '网络异常，请返回定价页确认是否已支付');
      });
    }

    pollOnce();
  }

  /* ---------------- init ---------------- */

  document.addEventListener('DOMContentLoaded', function () {
    bindLogout();
    document.querySelectorAll('[data-plan]').forEach(function () { bindCheckout(); });
    var authShell = $('#authShell');
    if (authShell) bindAuthForms(authShell.dataset.next || '');
    var payRoot = $('#payRoot');
    if (payRoot) bindPayPolling(payRoot.dataset.order || '', payRoot.dataset.canceled === '1');
  });
})();
