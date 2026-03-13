/* dashboard.js — BotRunner client-side logic */

// ── Run History Chart ─────────────────────────────────────────────────────

(function buildChart() {
  const canvas = document.getElementById('runChart');
  if (!canvas || !window.ALL_RUNS || ALL_RUNS.length === 0) return;

  // Group runs by bot, build a timeline dataset
  const botNames = [...new Set(ALL_RUNS.map(r => r.bot_name))];
  const GREEN = 'rgba(61, 220, 132, 0.85)';
  const RED   = 'rgba(255, 79, 79, 0.85)';
  const DIM   = 'rgba(80, 80, 80, 0.5)';

  // Build labels from unique dates (last 30 days worth of runs)
  const sorted = [...ALL_RUNS]
    .filter(r => r.status !== 'running')
    .sort((a, b) => a.start_time.localeCompare(b.start_time))
    .slice(-200);

  const labels = sorted.map(r => r.start_time.slice(0, 16).replace('T', ' '));

  const datasets = botNames.map((name, i) => {
    const hue   = (i * 137) % 360;
    const color = `hsl(${hue}, 70%, 60%)`;
    const runs  = sorted.filter(r => r.bot_name === name);

    return {
      label: name,
      data: sorted.map(r => {
        if (r.bot_name !== name) return null;
        return r.status === 'success' ? 1 : -1;
      }),
      backgroundColor: sorted.map(r => {
        if (r.bot_name !== name) return 'transparent';
        return r.status === 'success' ? GREEN : RED;
      }),
      borderColor: color,
      borderWidth: 0,
      borderRadius: 2,
      barThickness: 10,
    };
  });

  new Chart(canvas, {
    type: 'bar',
    data: { labels, datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 400 },
      interaction: { mode: 'index', intersect: false },
      scales: {
        x: {
          stacked: false,
          ticks: {
            color: '#444',
            font: { family: "'IBM Plex Mono'", size: 9 },
            maxTicksLimit: 12,
            maxRotation: 0,
          },
          grid: { color: '#1a1a1a' },
        },
        y: {
          min: -1.5,
          max: 1.5,
          ticks: {
            color: '#444',
            font: { family: "'IBM Plex Mono'", size: 9 },
            callback: v => v === 1 ? 'OK' : v === -1 ? 'FAIL' : '',
          },
          grid: { color: '#1a1a1a' },
        },
      },
      plugins: {
        legend: {
          labels: {
            color: '#666',
            font: { family: "'IBM Plex Mono'", size: 10 },
            boxWidth: 10,
            padding: 16,
          },
        },
        tooltip: {
          backgroundColor: '#181818',
          borderColor: '#2a2a2a',
          borderWidth: 1,
          titleColor: '#e8e8e8',
          bodyColor: '#888',
          titleFont: { family: "'IBM Plex Mono'", size: 11 },
          bodyFont:  { family: "'IBM Plex Mono'", size: 10 },
          callbacks: {
            label: ctx => {
              const run = sorted.filter(r => r.bot_name === ctx.dataset.label)[0];
              const val = ctx.raw;
              if (val === null) return null;
              return ` ${ctx.dataset.label}: ${val === 1 ? '✓ success' : '✗ failure'}`;
            },
          },
        },
      },
    },
  });
})();


// ── Toggle bot ────────────────────────────────────────────────────────────

async function toggleBot(botName, btn) {
  btn.disabled = true;
  btn.textContent = '...';

  try {
    const res = await fetch(`/api/bots/${botName}/toggle`, { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
    const data = await res.json();

    btn.textContent = data.enabled ? 'ENABLED' : 'DISABLED';
    btn.className = `btn btn--toggle ${data.enabled ? 'btn--on' : 'btn--off'}`;

    // Update card accent class
    const card = document.getElementById(`card-${botName}`);
    if (card) {
      card.classList.remove('card--disabled');
      if (!data.enabled) card.classList.add('card--disabled');
    }
  } catch (err) {
    btn.textContent = 'ERROR';
    console.error('Toggle failed:', err);
  } finally {
    btn.disabled = false;
  }
}


// ── Run bot ───────────────────────────────────────────────────────────────

async function runBot(botName, btn) {
  btn.disabled = true;
  btn.textContent = '● RUNNING';
  btn.classList.add('running');

  try {
    const res = await fetch(`/api/bots/${botName}/run`, { method: 'POST' });
    if (!res.ok) throw new Error(await res.text());
    location.reload();
  } catch (err) {
    btn.textContent = '▶ RUN';
    btn.classList.remove('running');
    btn.disabled = false;
    console.error('Run failed:', err);
  }
}


// ── Log viewer ────────────────────────────────────────────────────────────

async function openLog(botName) {
  const section = document.getElementById('log-section');
  const title   = document.getElementById('log-title');
  const content = document.getElementById('log-content');

  title.textContent   = `LOG — ${botName.toUpperCase()}`;
  content.textContent = 'Loading...';
  section.style.display = 'block';
  section.scrollIntoView({ behavior: 'smooth', block: 'start' });

  try {
    const res  = await fetch(`/api/logs/${botName}?lines=300`);
    const text = await res.text();
    content.textContent = text || '(log is empty)';
    // scroll log to bottom
    content.scrollTop = content.scrollHeight;
  } catch (err) {
    content.textContent = `Failed to load log: ${err.message}`;
  }
}

function closeLog() {
  document.getElementById('log-section').style.display = 'none';
}
