/*
 * MePage storefront — Split Bill (customer flow).
 * Steps: 1 details -> 2 review -> 3 result. Shares are previewed here with
 * the same remainder rule the server uses (the server is the source of
 * truth and its numbers are what the result screen shows). All text is set
 * with textContent — never innerHTML.
 */
(function () {
  "use strict";
  var dataEl = document.getElementById("store-data");
  var openBtns = document.querySelectorAll("[data-split-open]");
  var dialog = document.getElementById("split");
  if (!dataEl || !openBtns.length || !dialog) return;
  var store = JSON.parse(dataEl.textContent);
  var cfg = store.splitBill || {};
  var MIN = 2, MAX = 20, MAX_TOTAL = 1000000;
  var SYMBOLS = { INR: "₹" };
  var body = document.getElementById("split-body");
  var stateKey = "mepage-split:" + (store.slug || "preview");

  var st = null;     // wizard state
  var pollTimer = null;

  function newState() {
    return { step: 1, total: "", people: [blank(), blank()], table: "", requestId: null, busy: false,
      error: "", errors: {}, result: null, token: null };
  }
  function blank() { return { name: "", phone: "" }; }

  // ---- helpers -------------------------------------------------------------
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }
  function btn(label, cls, onclick) {
    var b = el("button", "btn " + (cls || ""), label);
    b.type = "button";
    if (onclick) b.onclick = onclick;
    return b;
  }
  function toast(msg) {
    var t = document.getElementById("toast");
    if (!t) return;
    t.textContent = msg; t.classList.add("show");
    clearTimeout(toast._t); toast._t = setTimeout(function () { t.classList.remove("show"); }, 2400);
  }
  function group(n) {
    var s = String(n);
    if (s.length <= 3) return s;
    var head = s.slice(0, -3), tail = s.slice(-3), g = [];
    while (head.length > 2) { g.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) g.unshift(head);
    return g.join(",") + "," + tail;
  }
  function money(paise) {
    var rupees = Math.floor(paise / 100), frac = paise % 100;
    return (SYMBOLS[store.currency] || "₹") + group(rupees) + (frac ? "." + String(frac).padStart(2, "0") : "");
  }
  // "1250.5" -> 125050; null when not a valid amount (max 2 decimals, > 0, <= limit).
  function parsePaise(raw) {
    var s = String(raw).trim().replace(/,/g, "");
    if (!/^\d{1,7}(\.\d{1,2})?$/.test(s)) return null;
    var parts = s.split("."), p = parseInt(parts[0], 10) * 100 + parseInt((parts[1] || "0").padEnd(2, "0"), 10);
    return p > 0 && p <= MAX_TOTAL * 100 ? p : null;
  }
  function shares(total, n) {
    var base = Math.floor(total / n), rem = total % n, out = [];
    for (var i = 0; i < n; i++) out.push(base + (i < rem ? 1 : 0));
    return out;
  }
  // Mirrors the server's phone rules closely enough for instant feedback.
  function validPhone(raw) {
    var s = String(raw).trim(), plus = s.charAt(0) === "+", d = s.replace(/\D/g, "");
    if (!plus && d.indexOf("00") === 0) { d = d.slice(2); plus = true; }
    if (!plus) {
      if (d.length === 11 && d.charAt(0) === "0") d = d.slice(1);
      if (d.length === 12 && d.indexOf("91") === 0) return /^91[6-9]\d{9}$/.test(d);
      return /^[6-9]\d{9}$/.test(d);
    }
    if (d.length < 8 || d.length > 15 || d.charAt(0) === "0") return false;
    return d.indexOf("91") !== 0 || /^91[6-9]\d{9}$/.test(d);
  }
  function digitsOf(raw) {
    var s = String(raw).trim(), d = s.replace(/\D/g, "");
    if (s.charAt(0) !== "+" && d.indexOf("00") === 0) return d.slice(2);
    if (s.charAt(0) !== "+") { if (d.length === 11 && d.charAt(0) === "0") d = d.slice(1); if (d.length === 10) d = "91" + d; }
    return d;
  }
  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    var a = new Uint8Array(16); (window.crypto || {}).getRandomValues ? crypto.getRandomValues(a) : a.forEach(function (_, i) { a[i] = Math.random() * 256; });
    return Array.prototype.map.call(a, function (b) { return b.toString(16).padStart(2, "0"); }).join("");
  }
  function tableNo() {
    try { return sessionStorage.getItem("mepage-table:" + store.slug) || ""; } catch (e) { return ""; }
  }

  // ---- validation ------------------------------------------------------------
  function validate() {
    var errors = {}, total = parsePaise(st.total);
    if (!st.total.trim()) errors.total = "Enter the total bill amount.";
    else if (total == null) errors.total = "Enter an amount like 4000 or 1250.50 (up to ₹" + group(MAX_TOTAL) + ").";
    else if (total < st.people.length * 100) errors.total = "Each person's share must be at least ₹1.";
    var seen = {};
    st.people.forEach(function (p, i) {
      if (!p.phone.trim()) errors["phone" + i] = "WhatsApp number is required.";
      else if (!validPhone(p.phone)) errors["phone" + i] = "Enter a valid mobile number (10 digits, or with country code).";
      else {
        var d = digitsOf(p.phone);
        if (seen[d] != null) errors["phone" + i] = "This number is already added.";
        seen[d] = i;
      }
    });
    st.errors = errors;
    return Object.keys(errors).length === 0;
  }

  // ---- rendering -------------------------------------------------------------
  function stepper() {
    var ol = el("ol", "sp-steps");
    ol.setAttribute("aria-label", "Progress");
    ["Details", "Review", "Send"].forEach(function (label, i) {
      var li = el("li", null, (i + 1) + ". " + label);
      if (st.step === i + 1) li.setAttribute("aria-current", "step");
      ol.appendChild(li);
    });
    return ol;
  }
  function draw() {
    var focusId = document.activeElement && document.activeElement.id;
    var selStart = document.activeElement && document.activeElement.selectionStart;
    body.textContent = "";
    body.appendChild(stepper());
    if (st.step === 1) drawDetails(); else if (st.step === 2) drawReview(); else drawResult();
    if (focusId) {
      var f = document.getElementById(focusId);
      if (f) { f.focus(); try { if (selStart != null) f.setSelectionRange(selStart, selStart); } catch (e) { /* not text */ } }
    }
  }

  function field(id, label, value, opts) {
    opts = opts || {};
    var wrap = el("div", "sp-field");
    var lab = el("label", null, label); lab.htmlFor = id;
    var input = el("input"); input.id = id; input.type = opts.type || "text"; input.value = value;
    if (opts.inputmode) input.inputMode = opts.inputmode;
    if (opts.autocomplete) input.autocomplete = opts.autocomplete;
    if (opts.placeholder) input.placeholder = opts.placeholder;
    if (opts.maxlength) input.maxLength = opts.maxlength;
    var err = opts.error;
    if (err) { input.setAttribute("aria-invalid", "true"); input.setAttribute("aria-describedby", id + "-e"); }
    input.oninput = function () { opts.onInput(input.value); };
    wrap.appendChild(lab);
    if (opts.prefix) {
      var box = el("div", "sp-amount"); box.appendChild(el("span", null, opts.prefix)); box.appendChild(input); wrap.appendChild(box);
    } else wrap.appendChild(input);
    if (err) { var e = el("p", "sp-err", err); e.id = id + "-e"; e.setAttribute("role", "alert"); wrap.appendChild(e); }
    return wrap;
  }

  function setCount(n) {
    n = Math.max(MIN, Math.min(MAX, n));
    while (st.people.length < n) st.people.push(blank());
    st.people.length = n;
    draw();
  }

  function drawDetails() {
    var total = parsePaise(st.total);
    body.appendChild(field("sp-total", "Total bill amount (₹)", st.total, {
      type: "text", inputmode: "decimal", prefix: "₹", placeholder: "4000", maxlength: 12, error: st.errors.total,
      onInput: function (v) { st.total = v; updateLive(); },
    }));

    var cl = el("div", "sp-field");
    cl.appendChild(el("span", "sp-label", "Number of people"));
    var row = el("div", "sp-count");
    var minus = btn("−", "step", function () { setCount(st.people.length - 1); });
    minus.className = "step"; minus.setAttribute("aria-label", "Fewer people"); minus.disabled = st.people.length <= MIN;
    var out = el("output", null, String(st.people.length)); out.setAttribute("aria-live", "polite");
    var plus = btn("+", "step", function () { setCount(st.people.length + 1); });
    plus.className = "step"; plus.setAttribute("aria-label", "More people"); plus.disabled = st.people.length >= MAX;
    row.append(minus, out, plus); cl.appendChild(row); body.appendChild(cl);

    var live = el("p", "sp-live"); live.id = "sp-live"; live.setAttribute("aria-live", "polite");
    body.appendChild(live);
    updateLive();

    st.people.forEach(function (p, i) {
      var box = el("fieldset", "sp-person");
      box.style.cssText = "min-width:0";
      var head = el("div", "sp-person-head");
      head.appendChild(el("span", null, "Person " + (i + 1)));
      if (st.people.length > MIN) {
        var rm = el("button", "sp-remove", "Remove"); rm.type = "button";
        rm.setAttribute("aria-label", "Remove person " + (i + 1));
        rm.onclick = function () { st.people.splice(i, 1); draw(); };
        head.appendChild(rm);
      }
      box.appendChild(head);
      var r2 = el("div", "sp-row2");
      r2.appendChild(field("sp-name-" + i, "Name (optional)", p.name, { autocomplete: "off", maxlength: 60, placeholder: "e.g. Rahul", onInput: function (v) { p.name = v; } }));
      r2.appendChild(field("sp-phone-" + i, "WhatsApp number", p.phone, {
        type: "tel", inputmode: "tel", autocomplete: "off", placeholder: "98765 43210", maxlength: 20, error: st.errors["phone" + i],
        onInput: function (v) { p.phone = v; },
      }));
      box.appendChild(r2);
      body.appendChild(box);
    });

    var add = btn("+ Add another person", "btn-ghost", function () { setCount(st.people.length + 1); });
    add.disabled = st.people.length >= MAX;
    body.appendChild(add);
    body.appendChild(el("p", "sp-note", "Indian numbers need 10 digits. For other countries add the country code, like +44 7700 900123."));

    var foot = el("div", "sp-foot");
    foot.appendChild(btn("Review split", "", function () {
      if (validate()) { st.requestId = uuid(); st.step = 2; st.error = ""; draw(); body.scrollTop = 0; } else { draw(); focusFirstError(); }
    }));
    body.appendChild(foot);
    if (total) updateLive();
  }
  function updateLive() {
    var live = document.getElementById("sp-live"); if (!live) return;
    var total = parsePaise(st.total), n = st.people.length;
    if (total && total >= n * 100) {
      var s = shares(total, n), uneven = s[0] !== s[n - 1];
      live.textContent = uneven ? "About " + money(Math.floor(total / n)) + " each (a few pay 1 paisa more so it adds up exactly)"
        : money(s[0]) + " each";
    } else live.textContent = "Enter the bill amount to see each person's share.";
  }
  function focusFirstError() {
    var bad = body.querySelector("[aria-invalid=true]"); if (bad) bad.focus();
  }

  function drawReview() {
    var total = parsePaise(st.total), n = st.people.length, sh = shares(total, n);
    body.appendChild(el("h3", null, "Review and confirm"));
    var dl = el("dl", "sp-summary");
    [["Restaurant", store.name, true], ["Total bill", money(total)], ["People", String(n)],
      ["Each pays", sh[0] === sh[n - 1] ? money(sh[0]) : "≈ " + money(Math.floor(total / n))]].forEach(function (r) {
      var d = el("div", r[2] ? "wide" : null); d.appendChild(el("dt", null, r[0])); d.appendChild(el("dd", null, r[1])); dl.appendChild(d);
    });
    body.appendChild(dl);

    var table = el("table", "sp-table");
    var cap = el("caption", "sr-only", "Bill breakdown"); table.appendChild(cap);
    var thead = el("thead"), hr = el("tr");
    ["Participant", "Amount"].forEach(function (h, i) { var th = el("th", i ? "num" : null, h); th.scope = "col"; hr.appendChild(th); });
    thead.appendChild(hr); table.appendChild(thead);
    var tb = el("tbody");
    st.people.forEach(function (p, i) {
      var tr = el("tr"), td = el("td");
      td.appendChild(document.createTextNode(p.name.trim() || "Person " + (i + 1)));
      td.appendChild(el("span", "sp-sub", p.phone.trim()));
      tr.appendChild(td); tr.appendChild(el("td", "num", money(sh[i]))); tb.appendChild(tr);
    });
    table.appendChild(tb);
    var tf = el("tfoot"), ft = el("tr"); ft.appendChild(el("td", null, "Total")); ft.appendChild(el("td", "num", money(total)));
    tf.appendChild(ft); table.appendChild(tf); body.appendChild(table);

    body.appendChild(el("p", "sp-note", "Each person gets their own WhatsApp message with their amount and how to pay " + store.name +
      ". Nothing is marked paid until the restaurant confirms it."));
    if (st.error) { var e = el("p", "sp-banner sp-banner-err", st.error); e.setAttribute("role", "alert"); body.appendChild(e); }

    var foot = el("div", "sp-foot");
    var back = btn("Edit details", "btn-ghost", function () { st.step = 1; st.error = ""; draw(); });
    back.disabled = st.busy;
    var go = btn(st.busy ? "Sending…" : (st.error ? "Try again" : "Confirm & Send Payment Details"), "", submit);
    go.disabled = st.busy;
    if (st.busy) go.prepend(el("span", "sp-spin"));
    foot.append(back, go);
    body.appendChild(foot);
  }

  // ---- network ---------------------------------------------------------------
  function api(method, url, payload, token) {
    var headers = {};
    if (payload) headers["Content-Type"] = "application/json";
    if (token) headers["X-Split-Token"] = token;
    return fetch(url, { method: method, headers: headers, body: payload ? JSON.stringify(payload) : undefined, cache: "no-store" })
      .then(function (r) {
        return r.text().then(function (t) {
          var j = null; try { j = t ? JSON.parse(t) : null; } catch (e) { /* non-JSON */ }
          if (!r.ok) {
            var d = j && j.detail, msg = (d && (d.message || (typeof d === "string" && d))) || "Something went wrong. Please try again.";
            if (d && d.errors && d.errors[0]) msg = d.errors[0].message;
            var err = new Error(msg); err.status = r.status; err.field = d && d.field; throw err;
          }
          return j;
        });
      }, function () { var e = new Error("You appear to be offline. Check your connection and try again."); e.status = 0; throw e; });
  }

  function submit() {
    if (st.busy) return;
    if (store.preview) { toast("Preview only — nothing is sent from a preview."); return; }
    st.busy = true; st.error = ""; draw();
    api("POST", cfg.url, {
      request_id: st.requestId, total: st.total.trim().replace(/,/g, ""), table_no: tableNo() || null,
      participants: st.people.map(function (p) { return { name: p.name.trim() || null, phone: p.phone.trim() }; }),
    }).then(function (res) {
      st.busy = false; st.result = res; st.token = res.access_token; st.step = 3;
      try { sessionStorage.setItem(stateKey, JSON.stringify({ id: res.id, token: res.access_token })); } catch (e) { /* private mode */ }
      draw(); body.scrollTop = 0; schedulePoll();
    }).catch(function (err) {
      st.busy = false;
      var m = /^participants\.(\d+)\.phone$/.exec(err.field || "");
      if (m && err.status === 422) {          // server disagrees with a number: send them back to fix it
        st.errors["phone" + m[1]] = err.message; st.step = 1; st.error = ""; draw(); focusFirstError(); return;
      }
      st.error = err.message; draw();
    });
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    if (!st || !st.result || !st.result.notifications_in_progress) return;
    var started = schedulePoll.started = schedulePoll.started || Date.now();
    if (Date.now() - started > 120000) return;
    pollTimer = setTimeout(function () {
      api("GET", cfg.url.replace(/\/stores\/[^/]+\/split-bills$/, "") + "/split-bills/" + st.result.id, null, st.token)
        .then(function (res) { res.access_token = st.token; st.result = res; if (st.step === 3) draw(); schedulePoll(); })
        .catch(function () { schedulePoll(); });
    }, 2500);
  }

  function retry() {
    var base = cfg.url.replace(/\/stores\/[^/]+\/split-bills$/, "") + "/split-bills/" + st.result.id;
    st.retrying = true; draw();
    api("POST", base + "/notify", null, st.token).then(function () {
      schedulePoll.started = null;
      return api("GET", base, null, st.token);
    }).then(function (res) {
      res.access_token = st.token; res.notifications_in_progress = true; st.result = res; st.retrying = false; draw(); schedulePoll();
    }).catch(function (err) { st.retrying = false; toast(err.message); draw(); });
  }

  // ---- result ----------------------------------------------------------------
  function copy(text) {
    var done = function () { toast("UPI ID copied"); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, fallback);
    else fallback();
    function fallback() {
      var t = el("textarea"); t.value = text; t.style.position = "fixed"; t.style.opacity = "0"; document.body.appendChild(t);
      t.select(); try { document.execCommand("copy"); done(); } catch (e) { toast("Copy it manually: " + text); } t.remove();
    }
  }
  function link(label, href, cls) {
    var a = el("a", "btn " + (cls || ""), label); a.href = href; a.target = "_blank"; a.rel = "noopener"; return a;
  }

  function drawResult() {
    var r = st.result, cloud = r.delivery_mode === "cloud_api";
    var failed = r.participants.filter(function (p) { return p.notification_status === "failed"; }).length;
    var waiting = r.notifications_in_progress;

    var banner;
    if (!cloud) {
      banner = el("p", "sp-banner sp-banner-warn", "Your split is ready. Tap “Send on WhatsApp” for each person — WhatsApp opens with their message ready; press Send there.");
    } else if (waiting) {
      banner = el("p", "sp-banner sp-banner-warn"); banner.appendChild(el("span", "sp-spin")); banner.appendChild(document.createTextNode("Sending payment details on WhatsApp…"));
    } else if (failed) {
      banner = el("p", "sp-banner sp-banner-err", failed + " message" + (failed > 1 ? "s" : "") + " couldn't be sent. Retry, or send the details from your own WhatsApp.");
    } else {
      banner = el("p", "sp-banner sp-banner-ok", "Payment details sent to everyone on WhatsApp.");
    }
    banner.setAttribute("role", "status");
    body.appendChild(banner);
    body.appendChild(el("p", "sp-note", "Split " + r.code + " · " + money(r.total_paise) + " between " + r.participant_count + " people."));

    // How to pay (shared by everyone)
    var pay = el("section", "sp-pay"); pay.setAttribute("aria-labelledby", "sp-pay-h");
    var h = el("h3", null, "How to pay " + r.restaurant); h.id = "sp-pay-h"; pay.appendChild(h);
    if (r.payment.upi_id) {
      var u = el("div", "sp-upi"); u.appendChild(el("code", null, r.payment.upi_id));
      u.appendChild(btn("Copy UPI ID", "btn-ghost", function () { copy(r.payment.upi_id); }));
      pay.appendChild(u);
    }
    if (r.payment.qr_url) {
      var img = el("img", "sp-qr"); img.src = r.payment.qr_url; img.alt = r.restaurant + " payment QR code"; img.width = 240; img.height = 240;
      pay.appendChild(img);
    }
    if (r.payment.note) pay.appendChild(el("p", "sp-note", r.payment.note));
    pay.appendChild(el("p", "sp-note", r.payment_note));
    body.appendChild(pay);

    r.participants.forEach(function (p, i) {
      var card = el("div", "sp-card"), top = el("div", "sp-card-top"), who = el("div");
      who.appendChild(el("strong", null, p.name || "Person " + (i + 1)));
      who.appendChild(el("span", "sp-sub", p.phone_masked));
      top.appendChild(who); top.appendChild(el("span", "sp-share", money(p.share_paise))); card.appendChild(top);

      var chip = chipFor(p); card.appendChild(chip);
      var acts = el("div", "sp-actions");
      if (p.wa_link) acts.appendChild(link(p.notification_status === "failed" ? "Send on WhatsApp instead" : "Send on WhatsApp", p.wa_link, "btn-wa"));
      if (p.upi_link) acts.appendChild(link("Pay " + money(p.share_paise) + " in UPI app", p.upi_link, "btn-ghost"));
      if (acts.children.length) card.appendChild(acts);
      body.appendChild(card);
    });

    var foot = el("div", "sp-foot");
    if (r.retryable && !waiting) {
      var rb = btn(st.retrying ? "Retrying…" : "Retry failed messages", "", retry); rb.disabled = !!st.retrying; foot.appendChild(rb);
    }
    foot.appendChild(btn("Start a new split", "btn-ghost", function () { clearTimeout(pollTimer); schedulePoll.started = null; st = newState(); clearSaved(); draw(); }));
    foot.appendChild(btn("Done", "btn-ghost", function () { closeDlg(); }));
    body.appendChild(foot);
  }
  function chipFor(p) {
    var s = p.notification_status;
    if (p.status === "payment_confirmed") return el("span", "sp-chip sp-chip-sent", "Payment confirmed by restaurant");
    if (s === "sent") return el("span", "sp-chip sp-chip-sent", "Message sent · payment pending");
    if (s === "failed") return el("span", "sp-chip sp-chip-failed", "Message not sent");
    if (s === "pending" || s === "sending") return el("span", "sp-chip sp-chip-wait", "Sending…");
    return el("span", "sp-chip", "Not sent yet · payment pending");
  }
  function clearSaved() { try { sessionStorage.removeItem(stateKey); } catch (e) { /* ignore */ } }

  // ---- open / close ------------------------------------------------------------
  function closeDlg() { if (dialog.close) dialog.close(); else dialog.removeAttribute("open"); }
  function resume() {
    var saved = null;
    try { saved = JSON.parse(sessionStorage.getItem(stateKey) || "null"); } catch (e) { /* ignore */ }
    if (!saved || store.preview) return Promise.resolve(false);
    var base = cfg.url.replace(/\/stores\/[^/]+\/split-bills$/, "") + "/split-bills/" + saved.id;
    return api("GET", base, null, saved.token).then(function (res) {
      res.access_token = saved.token; st.result = res; st.token = saved.token; st.step = 3; return true;
    }, function () { clearSaved(); return false; });
  }
  function openSplit() {
    if (!st) st = newState();
    st.table = tableNo();
    var show = function () { draw(); if (dialog.showModal) dialog.showModal(); else dialog.setAttribute("open", ""); schedulePoll(); };
    if (st.step === 1 && !st.total) resume().then(show); else show();
  }
  openBtns.forEach(function (b) { b.addEventListener("click", openSplit); });
  dialog.addEventListener("click", function (e) {
    if (e.target === dialog || e.target.closest("[data-close]")) closeDlg();
  });
  dialog.addEventListener("close", function () { clearTimeout(pollTimer); });
})();
