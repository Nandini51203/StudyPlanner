const $ = id => document.getElementById(id);
async function go(btn, mid, stage, extra = {}) {
  const old = btn.innerHTML; btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> AI working...';
  try {
    const r = await fetch(`/api/run/${mid}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({stage, ...extra})});
    const d = await r.json(); if (!r.ok) throw new Error(d.error || "Request failed");
    location = (stage === "quiz" && d.quiz_id) ? `/quiz/${d.quiz_id}` : `/summary/${mid}`;
  } catch (e) { alert(e.message); btn.disabled = false; btn.innerHTML = old; }
}
