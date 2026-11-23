// Dashboard logic: poll /admin/stats, send demo traffic, log in, purge.
// Plain browser JavaScript, no framework, no build step.

const TEST_PATHS = ["/", "/products", "/api/products", "/api/products/1",
                    "/api/products?category=books", "/api/time", "/internal/reports"];
const COLORS = { HIT: "var(--hit)", REVALIDATED: "var(--reval)", MISS: "var(--miss)" };
let token = null; // JWT kept in memory only: gone when the tab closes.

const $ = (id) => document.getElementById(id);

async function refreshStats() {
  try {
    const res = await fetch("/admin/stats");
    const s = await res.json();
    $("hit-ratio").textContent = `${(s.hit_ratio * 100).toFixed(1)}%`;
    $("hits").textContent = s.hits;
    $("misses").textContent = s.misses;
    $("revalidations").textContent = s.revalidations;
    $("rate-limited").textContent = s.rate_limited;
    $("cache-entries").textContent = `${s.cache_entries} / ${s.cache_capacity}`;
    $("allowed").textContent = s.access_decisions.ALLOWED;
    $("denied").textContent = s.access_decisions.DENIED_401 + s.access_decisions.DENIED_403;
    renderLatency(s.avg_latency_ms);
    setLive(true);
  } catch {
    setLive(false);
  }
}

function setLive(ok) {
  $("live").textContent = ok ? "live" : "edge unreachable";
  $("live").className = `pill ${ok ? "ok" : "down"}`;
}

function renderLatency(avg) {
  const max = Math.max(1, ...Object.values(avg));
  $("latency").innerHTML = Object.entries(COLORS).map(([status, color]) => `
    <div class="bar-row">
      <span>${status}</span>
      <div class="bar-track"><div class="bar-fill" style="width:${(avg[status] / max) * 100}%;background:${color}"></div></div>
      <span class="bar-value">${avg[status].toFixed(2)} ms</span>
    </div>`).join("");
}

async function timedGet(path) {
  const started = performance.now();
  const headers = token ? { Authorization: `Bearer ${token}` } : {}; // zero trust: send who we are
  const res = await fetch(path, { cache: "no-store", headers }); // bypass the browser cache, test the edge
  return {
    path,
    status: res.status,
    cache: res.headers.get("X-Cache") || "NONE",
    age: res.headers.get("Age") ?? "–",
    ms: performance.now() - started,
  };
}

function showResults(rows) {
  $("results").innerHTML = rows.map((r) => `
    <tr><td><code>${r.path}</code></td><td>${r.status}</td>
    <td><span class="tag ${r.cache}">${r.cache}</span></td>
    <td>${r.age}</td><td>${r.ms.toFixed(0)} ms</td></tr>`).join("");
}

async function sendTestRequests() {
  const rows = [];
  for (const path of TEST_PATHS) rows.push(await timedGet(path)); // one by one, easier to read
  showResults(rows);
  refreshStats();
}

async function sendBurst() {
  const rows = await Promise.all(Array.from({ length: 40 }, () => timedGet("/api/products")));
  const limited = rows.filter((r) => r.status === 429).length;
  showResults([...rows.filter((r) => r.status !== 429).slice(0, 3), ...rows.filter((r) => r.status === 429).slice(0, 3)]);
  $("results").insertAdjacentHTML("beforeend",
    `<tr><td colspan="5" class="muted">${rows.length} sent, ${limited} rejected with 429 (rate limit).</td></tr>`);
  refreshStats();
}

async function login(event) {
  event.preventDefault();
  const form = new FormData(event.target);
  const res = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username: form.get("username"), password: form.get("password") }),
  });
  if (!res.ok) {
    token = null;
    $("auth-status").textContent = `Login failed (${res.status}).`;
    return;
  }
  const body = await res.json();
  token = body.access_token;
  $("auth-status").textContent = `Logged in as ${form.get("username")} (${body.role}). Token expires in ${body.expires_in / 60} min.`;
}

async function purge(path) {
  const res = await fetch("/admin/purge", {
    method: "POST",
    headers: { "Content-Type": "application/json", ...(token && { Authorization: `Bearer ${token}` }) },
    body: JSON.stringify(path ? { path } : {}),
  });
  $("purge-status").textContent = res.ok
    ? `Purged ${(await res.json()).purged} entries ${path ? "for " + path : "(everything)"}.`
    : `Purge refused: ${res.status} ${res.status === 401 ? "(log in first)" : res.status === 403 ? "(admin role needed)" : ""}`;
  refreshStats();
}

$("send-test").addEventListener("click", sendTestRequests);
$("send-burst").addEventListener("click", sendBurst);
$("login-form").addEventListener("submit", login);
$("purge-form").addEventListener("submit", (e) => {
  e.preventDefault();
  purge(new FormData(e.target).get("path").trim() || null);
});
$("purge-all").addEventListener("click", () => purge(null));

refreshStats();
setInterval(refreshStats, 2000);
