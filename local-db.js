/* 한눈 장부 — 내 PC용 저장소 어댑터.
 *
 * 아티팩트에서는 Claude 저장소(window.claude)가 장부를 맡는다.
 * 내 PC에서는 이 파일이 같은 모양의 저장소를 흉내 내고, 실제 내용은
 * 구글 드라이브 폴더의 장부.json 한 파일에 들어간다.
 */
(function () {
  "use strict";

  var COLLECTIONS = ["groups", "cards", "cats", "meta", "entries"];
  var API = "/api/data" + (location.search || "");
  var POLL_MS = 4000;
  var FLUSH_MS = 250;

  var state = { version: 0, groups: {}, cards: {}, cats: {}, meta: {}, entries: {} };
  var listeners = [];   // {col, fn}
  var loaded = false;
  var flushTimer = null;
  var waiting = [];     // 저장이 끝나기를 기다리는 약속들
  var inFlight = false;
  var dirty = false;

  function blank() { return { version: 0, groups: {}, cards: {}, cats: {}, meta: {}, entries: {} }; }

  function adopt(doc) {
    var next = blank();
    next.version = (doc && doc.version) || 0;
    COLLECTIONS.forEach(function (c) {
      next[c] = (doc && doc[c] && typeof doc[c] === "object") ? doc[c] : {};
    });
    var changed = [];
    COLLECTIONS.forEach(function (c) {
      if (JSON.stringify(state[c]) !== JSON.stringify(next[c])) changed.push(c);
    });
    state = next;
    changed.forEach(notify);
    return changed;
  }

  function snapshot(col) {
    var d = state[col] || {};
    var ids = Object.keys(d);
    return {
      docs: ids.map(function (id) {
        return { id: id, exists: true, data: function () { return d[id]; }, metadata: { fromCache: false, hasPendingWrites: dirty } };
      }),
      size: ids.length, empty: !ids.length,
      docChanges: function () { return []; },
      metadata: { fromCache: false, hasPendingWrites: dirty }
    };
  }

  function notify(col) {
    listeners.forEach(function (l) { if (l.col === col) { try { l.fn(); } catch (e) { console.error(e); } } });
  }

  // ---------------------------------------------------------------- 서버와 주고받기
  function pull() {
    return fetch(API, { headers: { Accept: "application/json" } })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (doc) { loaded = true; adopt(doc); })
      .catch(function (err) { console.warn("장부를 읽지 못했습니다", err); loaded = true; });
  }

  function flush() {
    if (inFlight) { schedule(); return; }
    var pending = waiting; waiting = [];
    if (!pending.length) return;
    inFlight = true;
    var body = { baseVersion: state.version };
    COLLECTIONS.forEach(function (c) { body[c] = state[c]; });

    fetch(API, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    }).then(function (r) {
      if (r.status === 409) {
        return r.json().then(function (out) {
          adopt(out.current);
          throw { code: "unavailable", message: "다른 기기가 먼저 저장했어요. 방금 내용을 다시 넣어 주세요." };
        });
      }
      if (!r.ok) throw { code: "unavailable", message: "저장하지 못했어요 (HTTP " + r.status + ")" };
      return r.json();
    }).then(function (out) {
      state.version = out.version;
      dirty = false;
      pending.forEach(function (p) { p.ok(); });
    }).catch(function (err) {
      var e = (err && err.code) ? err : { code: "unavailable", message: "저장하지 못했어요." };
      pending.forEach(function (p) { p.fail(e); });
    }).then(function () {
      inFlight = false;
      if (waiting.length) schedule();
    });
  }

  function schedule() {
    clearTimeout(flushTimer);
    flushTimer = setTimeout(flush, FLUSH_MS);
  }

  function mutate(fn) {
    fn();
    dirty = true;
    return new Promise(function (ok, fail) { waiting.push({ ok: ok, fail: fail }); schedule(); });
  }

  // ---------------------------------------------------------------- 저장소 흉내
  function docRef(col, id) {
    if (COLLECTIONS.indexOf(col) < 0) throw new TypeError("알 수 없는 묶음: " + col);
    return {
      id: id,
      path: col + "/" + id,
      get: function () {
        return Promise.resolve({
          id: id, exists: !!state[col][id],
          data: function () { return state[col][id]; }, metadata: {}
        });
      },
      set: function (body) {
        return mutate(function () { state[col][id] = JSON.parse(JSON.stringify(body)); notify(col); });
      },
      update: function (body) {
        return mutate(function () { state[col][id] = Object.assign({}, state[col][id], body); notify(col); });
      },
      "delete": function () {
        return mutate(function () { delete state[col][id]; notify(col); });
      },
      acquire: function () { return Promise.resolve({ acquired: true }); },
      onSnapshot: function (next) {
        var fn = function () {
          next({ id: id, exists: !!state[col][id], data: function () { return state[col][id]; }, metadata: {} });
        };
        listeners.push({ col: col, fn: fn });
        if (loaded) setTimeout(fn, 0); else pull().then(fn);
        return function () { listeners = listeners.filter(function (l) { return l.fn !== fn; }); };
      },
      collection: function () { throw new TypeError("한눈 장부는 하위 묶음을 쓰지 않습니다."); }
    };
  }

  function collectionRef(col) {
    if (COLLECTIONS.indexOf(col) < 0) throw new TypeError("알 수 없는 묶음: " + col);
    return {
      path: col,
      doc: function (id) { return docRef(col, id || String(Math.random()).slice(2)); },
      add: function (body) { var r = docRef(col, String(Date.now()) + String(Math.random()).slice(2, 8)); return r.set(body).then(function () { return r; }); },
      onSnapshot: function (next) {
        var fn = function () { next(snapshot(col)); };
        listeners.push({ col: col, fn: fn });
        if (loaded) setTimeout(fn, 0); else pull().then(fn);
        return function () { listeners = listeners.filter(function (l) { return l.fn !== fn; }); };
      }
    };
  }

  var db = {
    collection: collectionRef,
    doc: function (path) {
      var p = String(path).split("/");
      if (p.length !== 2) throw new TypeError("경로는 '묶음/이름' 두 마디여야 합니다: " + path);
      return docRef(p[0], p[1]);
    }
  };

  // 내려받기 — 아티팩트 밖이라 평범한 링크로 저장하면 된다
  var downloads = {
    save: function (o) {
      try {
        var blob = new Blob([o.data], { type: /\.json$/i.test(o.filename) ? "application/json" : "text/csv;charset=utf-8" });
        var url = URL.createObjectURL(blob);
        var a = document.createElement("a");
        a.href = url; a.download = o.filename;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(function () { URL.revokeObjectURL(url); }, 4000);
        return Promise.resolve();
      } catch (err) {
        return Promise.reject({ code: "upstream_error", message: String(err) });
      }
    }
  };

  // 명세서 자동 읽기는 Claude 가 있어야 한다 — 내 PC판에서는 직접 채우기로 넘어간다
  window.__LOCAL__ = { db: db, downloads: downloads, sample: null };

  pull();
  setInterval(function () { if (!dirty && !inFlight) pull(); }, POLL_MS);
  window.addEventListener("beforeunload", function () {
    if (!dirty) return;
    var body = { baseVersion: state.version };
    COLLECTIONS.forEach(function (c) { body[c] = state[c]; });
    try { navigator.sendBeacon(API, new Blob([JSON.stringify(body)], { type: "application/json" })); } catch (e) {}
  });
})();
