/*
 * MePage storefront runtime: cart (enquiry list), item dialog, WhatsApp
 * hand-off, sticky category highlighting, search, and anonymous counters.
 * Message formats mirror app/services/whatsapp.py — keep them in sync.
 * No customer data leaves the browser except through WhatsApp, which the
 * customer sends themselves.
 */
(function () {
  "use strict";
  var data = JSON.parse(document.getElementById("store-data").textContent);
  var MAX_URL = 2000;
  var SYMBOLS = { INR: "₹", USD: "$", EUR: "€", GBP: "£", AED: "AED ", SGD: "S$" };
  var itemsById = {};
  data.items.forEach(function (it) { itemsById[it.id] = it; });
  var storageKey = "mepage-cart:" + (data.slug || "preview");

  // ---- sitting area / table (from the table QR: ?table=<label>) ------------
  var tableKey = "mepage-table:" + (data.slug || "preview");
  var tableNo = (function () {
    var t = "";
    try { t = (new URLSearchParams(location.search).get("table") || "").replace(/\s+/g, " ").trim().slice(0, 30); } catch (e) { /* old browser */ }
    try {
      if (t) sessionStorage.setItem(tableKey, t);
      else t = sessionStorage.getItem(tableKey) || "";
    } catch (e) { /* private mode */ }
    return t;
  })();
  function tableLine() { return tableNo ? "Table: " + tableNo + "\n\n" : ""; }

  // ---- formatting -------------------------------------------------------
  function toPaise(price) {
    var parts = String(price).split(".");
    var frac = ((parts[1] || "") + "00").slice(0, 2);
    return parseInt(parts[0], 10) * 100 + parseInt(frac, 10);
  }
  function groupIndian(intStr) {
    if (intStr.length <= 3) return intStr;
    var head = intStr.slice(0, -3), tail = intStr.slice(-3), groups = [];
    while (head.length > 2) { groups.unshift(head.slice(-2)); head = head.slice(0, -2); }
    if (head) groups.unshift(head);
    return groups.join(",") + "," + tail;
  }
  function formatPaise(paise) {
    var intStr = String(Math.floor(paise / 100)), frac = String(paise % 100).padStart(2, "0");
    var grouped = data.currency === "INR" ? groupIndian(intStr) : Number(intStr).toLocaleString("en-US");
    var sym = SYMBOLS[data.currency] || data.currency + " ";
    return sym + (frac === "00" ? grouped : grouped + "." + frac);
  }
  function priceLabel(it) {
    if (it.price != null) return formatPaise(toPaise(it.price));
    return it.price_text || null;
  }

  // ---- WhatsApp messages --------------------------------------------------
  function waUrl(text) {
    return "https://wa.me/" + data.whatsapp + "?text=" + encodeURIComponent(text);
  }
  function itemMessage(it) {
    var label = priceLabel(it);
    var line = label ? "- " + it.name + " — " + label : "- " + it.name + " (price not listed)";
    return "Hello " + data.name + ",\n\n" + tableLine() + "I would like to enquire about:\n" + line +
      "\n\nStore: " + data.url + "\n\nPlease share more details.";
  }
  function cartMessage(lines, keep) {
    var shown = keep == null ? lines : lines.slice(0, keep);
    var body = shown.map(function (l, i) {
      var label = priceLabel(l.item);
      var pricePart = l.item.price != null ? label + " each" : (label || "Price unavailable");
      return (i + 1) + ". " + l.item.name + " — Qty: " + l.qty + " — " + pricePart;
    });
    var hidden = lines.length - shown.length;
    if (hidden > 0) body.push("…and " + hidden + " more item(s) — I'll share the full list in chat.");
    var msg = "Hello " + data.name + ",\n\n" + tableLine() + "I would like to enquire about the following items:\n\n" + body.join("\n");
    var allPriced = lines.length && lines.every(function (l) { return l.item.price != null; });
    if (hidden === 0 && allPriced) {
      var total = lines.reduce(function (s, l) { return s + toPaise(l.item.price) * l.qty; }, 0);
      msg += "\n\nEstimated subtotal: " + formatPaise(total) + " (to be confirmed by the store)";
    }
    return msg + "\n\nStore: " + data.url + "\n\nPlease confirm availability and the final total.";
  }
  function cartLink(lines) {
    var url = waUrl(cartMessage(lines));
    if (url.length <= MAX_URL) return { url: url, truncated: false, included: lines.length };
    for (var keep = lines.length - 1; keep > 0; keep--) {
      url = waUrl(cartMessage(lines, keep));
      if (url.length <= MAX_URL) return { url: url, truncated: true, included: keep };
    }
    return { url: waUrl(cartMessage(lines, 0)), truncated: true, included: 0 };
  }

  // ---- anonymous counters (no personal data) ------------------------------
  function track(kind) {
    if (data.preview || !data.slug) return;
    try {
      var body = JSON.stringify({ slug: data.slug, kind: kind });
      if (navigator.sendBeacon) navigator.sendBeacon(data.eventsUrl, new Blob([body], { type: "application/json" }));
    } catch (e) { /* best effort */ }
  }

  // ---- cart state ----------------------------------------------------------
  var cart = {};
  function loadCart() {
    try {
      var raw = JSON.parse(sessionStorage.getItem(storageKey) || "{}");
      Object.keys(raw).forEach(function (id) {
        var it = itemsById[id];
        var qty = parseInt(raw[id], 10);
        if (it && it.available && qty > 0) cart[id] = Math.min(qty, 99);
      });
    } catch (e) { cart = {}; }
  }
  function saveCart() {
    try { sessionStorage.setItem(storageKey, JSON.stringify(cart)); } catch (e) { /* private mode */ }
  }
  function cartLines() {
    return Object.keys(cart).map(function (id) { return { item: itemsById[id], qty: cart[id] }; })
      .filter(function (l) { return l.item; });
  }
  function count() { return cartLines().reduce(function (s, l) { return s + l.qty; }, 0); }

  var toastEl = document.getElementById("toast"), toastTimer;
  function toast(msg) {
    toastEl.textContent = msg;
    toastEl.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { toastEl.classList.remove("show"); }, 2200);
  }

  function addToCart(id) {
    var it = itemsById[id];
    if (!it || !it.available) { toast("Sorry, this item is unavailable."); return; }
    cart[id] = Math.min((cart[id] || 0) + 1, 99);
    saveCart(); render();
    toast(it.name + " added to your list");
  }
  function setQty(id, qty) {
    if (qty <= 0) delete cart[id]; else cart[id] = Math.min(qty, 99);
    saveCart(); render();
  }

  // ---- rendering -------------------------------------------------------------
  var fab = document.getElementById("cart-open");
  var countEl = document.getElementById("cart-count");
  var cartDialog = document.getElementById("cart");
  var body = document.getElementById("cart-body");
  var subtotalEl = document.getElementById("cart-subtotal");
  var warningEl = document.getElementById("cart-warning");
  var sendEl = document.getElementById("cart-send");

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text != null) e.textContent = text;
    return e;
  }

  function render() {
    var lines = cartLines(), n = count();
    countEl.textContent = n;
    fab.hidden = n === 0;
    document.querySelectorAll("[data-add]").forEach(function (b) {
      var q = cart[b.getAttribute("data-add")];
      if (!b.disabled) b.textContent = q ? "Added · " + q : "Add to list";
    });
    body.textContent = "";
    if (!lines.length) {
      body.appendChild(el("p", "empty-cart", "Your list is empty. Tap “Add to list” on anything you'd like to ask about."));
      sendEl.setAttribute("aria-disabled", "true");
      sendEl.removeAttribute("href");
      subtotalEl.textContent = ""; warningEl.hidden = true;
      return;
    }
    var ul = el("ul", "cart-lines");
    lines.forEach(function (l) {
      var li = el("li", "cart-line");
      var info = el("div", "cart-info");
      info.appendChild(el("span", "cart-name", l.item.name));
      info.appendChild(el("span", "cart-price", priceLabel(l.item) || "Price on request"));
      var stepper = el("div", "stepper");
      var minus = el("button", "step", "−"); minus.type = "button";
      minus.setAttribute("aria-label", "Decrease " + l.item.name);
      minus.onclick = function () { setQty(l.item.id, l.qty - 1); };
      var qty = el("span", "qty", String(l.qty)); qty.setAttribute("aria-live", "polite");
      var plus = el("button", "step", "+"); plus.type = "button";
      plus.setAttribute("aria-label", "Increase " + l.item.name);
      plus.onclick = function () { setQty(l.item.id, l.qty + 1); };
      var remove = el("button", "btn-text remove", "Remove"); remove.type = "button";
      remove.setAttribute("aria-label", "Remove " + l.item.name);
      remove.onclick = function () { setQty(l.item.id, 0); };
      stepper.append(minus, qty, plus);
      li.append(info, stepper, remove);
      ul.appendChild(li);
    });
    body.appendChild(ul);

    var allPriced = lines.every(function (l) { return l.item.price != null; });
    if (allPriced) {
      var total = lines.reduce(function (s, l) { return s + toPaise(l.item.price) * l.qty; }, 0);
      subtotalEl.textContent = "Estimated subtotal: " + formatPaise(total) + " — the store will confirm the final total.";
    } else {
      subtotalEl.textContent = "Some items don't have a listed price — the store will confirm prices and the total.";
    }
    var link = cartLink(lines);
    sendEl.href = link.url;
    sendEl.removeAttribute("aria-disabled");
    if (link.truncated) {
      warningEl.hidden = false;
      warningEl.textContent = "Your list is too long for one WhatsApp message. We'll send the first " +
        link.included + " of " + lines.length + " items and a note that more follow — you can paste the rest in the chat.";
    } else {
      warningEl.hidden = true;
    }
  }

  // ---- dialogs ---------------------------------------------------------------
  function openDialog(d) {
    if (typeof d.showModal === "function") d.showModal(); else d.setAttribute("open", "");
  }
  function closeDialog(d) {
    if (typeof d.close === "function") d.close(); else d.removeAttribute("open");
  }
  document.querySelectorAll("dialog").forEach(function (d) {
    d.addEventListener("click", function (e) {
      if (e.target === d || e.target.closest("[data-close]")) closeDialog(d);
    });
  });
  fab.addEventListener("click", function () { render(); openDialog(cartDialog); });
  document.getElementById("cart-clear").addEventListener("click", function () {
    cart = {}; saveCart(); render();
  });
  sendEl.addEventListener("click", function (e) {
    if (sendEl.getAttribute("aria-disabled") === "true") { e.preventDefault(); return; }
    track("cart_enquiry");
    toast("Opening WhatsApp — press Send there to share your list.");
  });

  var itemDialog = document.getElementById("item-dialog");
  function openItem(id) {
    var tpl = document.getElementById("detail-" + id), it = itemsById[id];
    if (!tpl || !it) return;
    document.getElementById("item-dialog-title").textContent = it.name;
    var target = document.getElementById("item-dialog-body");
    target.textContent = "";
    target.appendChild(tpl.content.cloneNode(true));
    wireEnquiries(target);
    render();
    openDialog(itemDialog);
  }

  // ---- delegated actions ---------------------------------------------------
  function wireEnquiries(root) {
    root.querySelectorAll("[data-enquire]").forEach(function (a) {
      var it = itemsById[a.getAttribute("data-enquire")];
      if (it && data.whatsapp) a.href = waUrl(itemMessage(it));
    });
  }
  wireEnquiries(document);
  document.addEventListener("click", function (e) {
    var add = e.target.closest("[data-add]");
    if (add) { e.preventDefault(); addToCart(add.getAttribute("data-add")); return; }
    var enquire = e.target.closest("[data-enquire]");
    if (enquire) { track("item_enquiry"); toast("Opening WhatsApp — press Send there to ask the store."); return; }
    var open = e.target.closest("[data-open]");
    if (open) openItem(open.getAttribute("data-open"));
  });

  // ---- category nav highlight ---------------------------------------------
  var links = document.querySelectorAll(".cat-link");
  if (links.length && "IntersectionObserver" in window) {
    var byId = {};
    links.forEach(function (l) { byId[l.getAttribute("data-cat")] = l; });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        links.forEach(function (l) { l.removeAttribute("aria-current"); });
        var l = byId[en.target.id];
        if (l) {
          l.setAttribute("aria-current", "true");
          // Scroll only the nav strip: scrollIntoView also scrolls the page and cancels the user's own scroll.
          var strip = l.parentNode;
          if (strip && strip.scrollWidth > strip.clientWidth) {
            var sr = strip.getBoundingClientRect(), lr = l.getBoundingClientRect();
            strip.scrollTo({ left: strip.scrollLeft + (lr.left - sr.left) - (sr.width - lr.width) / 2, behavior: "smooth" });
          }
        }
      });
    }, { rootMargin: "-40% 0px -55% 0px" });
    document.querySelectorAll("main section[id^='cat-']").forEach(function (s) { io.observe(s); });
  }

  // ---- search (all templates) ------------------------------------------------
  // Matches name, description and variant names (it.search, built server-side) against every word typed.
  var search = document.querySelector("[data-search]");
  if (search) {
    var none = document.querySelector("[data-noresults]");
    var cards = [];
    document.querySelectorAll("main .item").forEach(function (card) {
      var add = card.querySelector("[data-add]");
      var it = add && itemsById[add.getAttribute("data-add")];
      if (!it) return;
      cards.push({ el: card, text: (it.search || it.name).toLowerCase() });
    });
    var sections = document.querySelectorAll("main section[id^='cat-']");
    var navLinks = {};
    document.querySelectorAll(".cat-link").forEach(function (l) { navLinks[l.getAttribute("data-cat")] = l; });
    search.addEventListener("input", function () {
      var words = search.value.trim().toLowerCase().split(/\s+/).filter(Boolean);
      cards.forEach(function (c) {
        c.el.hidden = !words.every(function (w) { return c.text.indexOf(w) !== -1; });
      });
      var any = false;
      sections.forEach(function (sec) {
        var visible = sec.querySelectorAll(".item:not([hidden])").length;
        sec.hidden = visible === 0;
        if (navLinks[sec.id]) navLinks[sec.id].hidden = visible === 0;
        if (visible) any = true;
      });
      if (none) none.hidden = any;
    });
  }

  loadCart();
  render();
  track("view");
})();
