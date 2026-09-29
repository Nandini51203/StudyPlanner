function drawLine(id, scores) {
  if (!$(id)) return;
  new Chart($(id), {type: "line", data: {labels: scores.map(s => s.label), datasets: [{label: "Score %", data: scores.map(s => s.pct), borderColor: "#4f46e5", tension: .3}]}, options: {scales: {y: {min: 0, max: 100}}}});
}
function drawBar(id, topics) {
  if (!$(id)) return;
  new Chart($(id), {type: "bar", data: {labels: topics.map(t => t.topic), datasets: [{label: "Accuracy %", data: topics.map(t => t.accuracy), backgroundColor: "#818cf8"}]}, options: {scales: {y: {min: 0, max: 100}}}});
}
