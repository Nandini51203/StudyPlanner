// Study Planner page logic: plan generation + task management.

function generatePlan(btn) {
  const err = document.getElementById('planError');
  err.style.display = 'none';
  const title = document.getElementById('planTitle').value.trim();
  if (!title) {
    err.textContent = 'Please enter a plan title.';
    err.style.display = 'block';
    return;
  }
  const body = {
    title: title,
    exam_date: document.getElementById('planExamDate').value,
    daily_minutes: +document.getElementById('planDailyMinutes').value,
    days_per_week: +document.getElementById('planDaysPerWeek').value,
    study_time: document.getElementById('planStudyTime').value,
    material_id: document.getElementById('planMaterial').value,
    topics: document.getElementById('planTopics').value
  };
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Generating your plan...';
  fetch('/planner/generate', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(body)
  })
    .then(r => r.json().then(d => ({ok: r.ok, d})))
    .then(({ok, d}) => {
      if (!ok) throw new Error(d.error || 'Request failed');
      location = '/planner/' + d.plan_id;
    })
    .catch(e => {
      err.textContent = e.message;
      err.style.display = 'block';
      btn.disabled = false;
      btn.innerHTML = '<i class="bi bi-magic"></i> Generate Plan';
    });
}

function toggleTask(checkbox, pid, tid) {
  checkbox.disabled = true;
  const wasChecked = checkbox.checked;
  fetch(`/planner/${pid}/task/${tid}/toggle`, {method: 'POST'})
    .then(r => r.json().then(d => ({ok: r.ok, d})))
    .then(({ok, d}) => {
      if (!ok) throw new Error(d.error || 'Request failed');
      const bar = document.getElementById('planProgress');
      if (bar) bar.style.width = d.pct + '%';
      const lbl = document.getElementById('progressLabel');
      if (lbl) lbl.textContent = `${d.done}/${d.total} tasks completed (${d.pct}%)`;
      const rem = document.getElementById('remainingLabel');
      if (rem) rem.textContent = `${d.total - d.done} tasks remaining`;
      const topic = checkbox.closest('div.d-flex').querySelector('.task-topic');
      if (topic) {
        topic.style.textDecoration = d.completed ? 'line-through' : '';
        topic.style.color = d.completed ? '#999' : '';
      }
    })
    .catch(e => {
      alert(e.message);
      checkbox.checked = !wasChecked;
    })
    .finally(() => { checkbox.disabled = false; });
}

// ── Task Management ─────────────────────────────────────────────────────

function addTask(pid) {
  const topic = document.getElementById('newTaskTopic').value.trim();
  const desc = document.getElementById('newTaskDesc').value.trim();
  const dur = +document.getElementById('newTaskDur').value;
  const act = document.getElementById('newTaskAct').value;
  const pri = document.getElementById('newTaskPri').value;
  if (!topic) { alert('Topic is required'); return; }
  fetch(`/planner/${pid}/task/add`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({topic, description: desc, duration_minutes: dur, activity: act, priority: pri})
  })
    .then(r => r.json().then(d => ({ok: r.ok, d})))
    .then(({ok, d}) => {
      if (!ok) throw new Error(d.error || 'Request failed');
      location.reload();
    })
    .catch(e => alert(e.message));
}

function editTask(pid, tid, topic, desc, dur, act, pri) {
  document.getElementById('editTaskId').value = tid;
  document.getElementById('editTaskTopic').value = topic;
  document.getElementById('editTaskDesc').value = desc;
  document.getElementById('editTaskDur').value = dur;
  document.getElementById('editTaskAct').value = act;
  document.getElementById('editTaskPri').value = pri;
  new bootstrap.Modal(document.getElementById('editTaskModal')).show();
}

function saveTaskEdit(pid) {
  const tid = document.getElementById('editTaskId').value;
  const topic = document.getElementById('editTaskTopic').value.trim();
  const desc = document.getElementById('editTaskDesc').value.trim();
  const dur = +document.getElementById('editTaskDur').value;
  const act = document.getElementById('editTaskAct').value;
  const pri = document.getElementById('editTaskPri').value;
  if (!topic) { alert('Topic is required'); return; }
  fetch(`/planner/${pid}/task/${tid}/edit`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({topic, description: desc, duration_minutes: dur, activity: act, priority: pri})
  })
    .then(r => r.json().then(d => ({ok: r.ok, d})))
    .then(({ok, d}) => {
      if (!ok) throw new Error(d.error || 'Request failed');
      location.reload();
    })
    .catch(e => alert(e.message));
}

function deleteTask(pid, tid) {
  if (!confirm('Delete this task?')) return;
  fetch(`/planner/${pid}/task/${tid}/delete`, {method: 'POST'})
    .then(r => r.json().then(d => ({ok: r.ok, d})))
    .then(({ok, d}) => {
      if (!ok) throw new Error(d.error || 'Request failed');
      location.reload();
    })
    .catch(e => alert(e.message));
}

function regenerateRemaining(pid) {
  if (!confirm('Regenerate remaining tasks? Completed tasks will be preserved.')) return;
  fetch(`/planner/${pid}/regenerate`, {method: 'POST'})
    .then(r => r.json().then(d => ({ok: r.ok, d})))
    .then(({ok, d}) => {
      if (!ok) throw new Error(d.error || 'Request failed');
      location.reload();
    })
    .catch(e => alert(e.message));
}
