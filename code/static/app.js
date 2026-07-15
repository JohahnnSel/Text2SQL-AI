// ============================================================
// app.js — Libro de Gastos, frontend vanilla JS (sin frameworks)
//
// Consume el endpoint FastAPI (main.py) del proyecto Text-to-SQL:
//   GET  /health
//   POST /api/query   { pregunta: string }
//
// Nota de seguridad: todo el contenido que viene del backend (SQL
// generado, filas de la base, mensajes de error) se inserta con
// textContent, nunca con innerHTML, para no abrir una puerta de XSS
// a partir de datos que en última instancia salen de un LLM o de la
// base de datos.
// ============================================================

// Como main.py ahora sirve este mismo frontend (ver app.mount("/static", ...)
// en main.py), dejamos API_BASE vacío para usar rutas relativas al mismo
// origen. Si en algún momento separás el frontend a otro host/puerto,
// volvé a poner acá la URL completa del backend, ej:
// "http://localhost:8000"
const API_BASE = "";

let entryCounter = 0;

const form = document.getElementById("queryForm");
const textarea = document.getElementById("pregunta");
const submitBtn = document.getElementById("submitBtn");
const ledger = document.getElementById("ledger");
const ledgerEmpty = document.getElementById("ledgerEmpty");
const entryTemplate = document.getElementById("entryTemplate");
const statusDot = document.getElementById("statusDot");
const statusLabel = document.getElementById("statusLabel");
const suggestions = document.getElementById("suggestions");

// ---------- Autoresize del textarea ----------
textarea.addEventListener("input", () => {
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, 140) + "px";
});

textarea.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    form.requestSubmit();
  }
});

// ---------- Chips de sugerencia ----------
suggestions.addEventListener("click", (e) => {
  const chip = e.target.closest(".chip");
  if (!chip) return;
  textarea.value = chip.dataset.q;
  textarea.dispatchEvent(new Event("input"));
  textarea.focus();
});

// ---------- Chequeo de salud del backend ----------
async function checkHealth() {
  statusDot.className = "status-dot checking";
  statusLabel.textContent = "verificando conexión…";
  try {
    const res = await fetch(`${API_BASE}/health`, { signal: AbortSignal.timeout(4000) });
    if (res.ok) {
      statusDot.className = "status-dot ok";
      statusLabel.textContent = "conectado";
    } else {
      throw new Error("respuesta no OK");
    }
  } catch {
    statusDot.className = "status-dot error";
    statusLabel.textContent = "sin conexión con la API";
  }
}
checkHealth();

// ---------- Envío del formulario ----------
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const pregunta = textarea.value.trim();
  if (!pregunta) return;

  entryCounter += 1;
  ledgerEmpty.classList.add("hidden");

  const entry = createLoadingEntry(entryCounter, pregunta);
  ledger.prepend(entry);

  textarea.value = "";
  textarea.style.height = "auto";
  setFormDisabled(true);

  try {
    const res = await fetch(`${API_BASE}/api/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pregunta }),
    });

    const data = await res.json().catch(() => null);

    if (res.ok && data) {
      renderSuccess(entry, data);
    } else {
      const detalle = (data && data.detail) ? data.detail : `Error inesperado (HTTP ${res.status}).`;
      renderError(entry, detalle);
    }
  } catch (err) {
    renderError(entry, "No se pudo contactar a la API. ¿Está corriendo uvicorn en " + API_BASE + "?");
  } finally {
    setFormDisabled(false);
    textarea.focus();
  }
});

function setFormDisabled(disabled) {
  textarea.disabled = disabled;
  submitBtn.disabled = disabled;
}

// ---------- Construcción de entradas del DOM ----------

function createLoadingEntry(numero, pregunta) {
  const node = entryTemplate.content.cloneNode(true);
  const article = node.querySelector(".entry");

  article.querySelector(".entry-number").textContent = `N.º ${String(numero).padStart(3, "0")}`;
  article.querySelector(".entry-time").textContent = new Date().toLocaleTimeString("es-ES", {
    hour: "2-digit", minute: "2-digit",
  });
  article.querySelector(".entry-question").textContent = pregunta;

  return article;
}

function renderSuccess(article, data) {
  const body = article.querySelector(".entry-body");
  body.innerHTML = ""; // seguro: limpiamos nuestro propio placeholder, no contenido externo

  // --- Receipt con el SQL generado ---
  const receipt = document.createElement("div");
  receipt.className = "receipt";
  const label = document.createElement("p");
  label.className = "receipt-label";
  label.textContent = "SQL generado y validado";
  const pre = document.createElement("pre");
  pre.textContent = data.sql_generado || "";
  receipt.appendChild(label);
  receipt.appendChild(pre);
  body.appendChild(receipt);

  // --- Resumen en lenguaje natural ---
  const summary = document.createElement("p");
  summary.className = "entry-summary";
  summary.textContent = data.resumen || "";
  body.appendChild(summary);

  // --- Tabla de resultados ---
  if (Array.isArray(data.filas) && data.filas.length > 0) {
    body.appendChild(buildResultsTable(data.filas));
  }

  // --- Metadata ---
  const meta = document.createElement("p");
  meta.className = "entry-meta";
  meta.textContent = `${data.total_filas} fila(s) · ${data.duracion_ms} ms`;
  body.appendChild(meta);
}

function buildResultsTable(filas) {
  const wrap = document.createElement("div");
  wrap.className = "results-wrap";

  const table = document.createElement("table");
  table.className = "results";

  const columnas = Object.keys(filas[0]);

  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  columnas.forEach((col) => {
    const th = document.createElement("th");
    th.textContent = col;
    headRow.appendChild(th);
  });
  thead.appendChild(headRow);
  table.appendChild(thead);

  const tbody = document.createElement("tbody");
  // Limitamos el render a 50 filas para no trabar el DOM en preguntas
  // muy abiertas; el total real ya se muestra aparte en entry-meta.
  filas.slice(0, 50).forEach((fila) => {
    const tr = document.createElement("tr");
    columnas.forEach((col) => {
      const td = document.createElement("td");
      const valor = fila[col];
      td.textContent = valor === null || valor === undefined ? "—" : String(valor);
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  });
  table.appendChild(tbody);

  wrap.appendChild(table);
  return wrap;
}

function renderError(article, detalle) {
  const body = article.querySelector(".entry-body");
  body.innerHTML = "";

  const box = document.createElement("div");
  box.className = "entry-error";

  const title = document.createElement("p");
  title.className = "entry-error-title";
  title.textContent = "Consulta rechazada";

  const detail = document.createElement("p");
  detail.className = "entry-error-detail";
  detail.textContent = detalle;

  box.appendChild(title);
  box.appendChild(detail);
  body.appendChild(box);
}
