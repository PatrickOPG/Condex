// Checklist 100% — frontend sem framework.
// Regra de ouro: dados vindos da API entram na tela só via textContent
// (o helper el() faz isso), nunca via innerHTML.

const $ = (sel) => document.querySelector(sel);

const estado = {
  steamid: localStorage.getItem("steamid") || null,
  jogos: [],
  jogo: null,          // { appid, nome, conquistas }
  manuais: new Set(),  // ids marcados à mão (conquistas que a Steam ainda não mostra)
  filtro: "todas",
};

// ------------------------------------------------------------ utilidades
function el(tag, props = {}, ...filhos) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (v == null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const f of filhos.flat()) if (f != null) e.append(f);
  return e;
}

async function api(url) {
  const r = await fetch(url);
  const corpo = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(corpo.detail || "Algo deu errado. Tente de novo.");
  return corpo;
}

function avisar(msg) {
  const a = $("#aviso");
  a.textContent = msg || "";
  a.hidden = !msg;
}

function mostrar(tela) {
  for (const id of ["tela-perfil", "tela-biblioteca", "tela-jogo"]) {
    $("#" + id).hidden = id !== tela;
  }
  avisar("");
  window.scrollTo(0, 0);
}

function chaveManual() {
  return `manual:${estado.steamid || "anonimo"}:${estado.jogo.appid}`;
}

function carregarManuais() {
  try {
    estado.manuais = new Set(JSON.parse(localStorage.getItem(chaveManual()) || "[]"));
  } catch {
    estado.manuais = new Set();
  }
}

function salvarManuais() {
  localStorage.setItem(chaveManual(), JSON.stringify([...estado.manuais]));
}

function faixaRaridade(p) {
  if (p == null) return { texto: "—", classe: "" };
  const txt = p < 10 ? p.toFixed(1) : p.toFixed(0);
  if (p < 5) return { texto: `${txt}% · muito rara`, classe: "r-ultra" };
  if (p < 20) return { texto: `${txt}% · rara`, classe: "r-rara" };
  if (p < 50) return { texto: `${txt}% · incomum`, classe: "" };
  return { texto: `${txt}% · comum`, classe: "" };
}

// ------------------------------------------------------------ perfil
async function abrirPerfil(entrada) {
  avisar("");
  const { steamid } = await api(`/api/resolver?entrada=${encodeURIComponent(entrada)}`);
  estado.steamid = steamid;
  localStorage.setItem("steamid", steamid);
  estado.jogos = await api(`/api/biblioteca/${steamid}`);
  renderizarBiblioteca();
  mostrar("tela-biblioteca");
}

$("#form-perfil").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await abrirPerfil($("#entrada-perfil").value);
  } catch (err) {
    avisar(err.message);
  }
});

$("#form-appid").addEventListener("submit", async (e) => {
  e.preventDefault();
  const appid = $("#entrada-appid").value;
  if (appid) abrirJogo(Number(appid));
});

$("#btn-trocar-perfil").addEventListener("click", () => {
  estado.steamid = null;
  localStorage.removeItem("steamid");
  mostrar("tela-perfil");
});

// ------------------------------------------------------------ biblioteca
function renderizarBiblioteca() {
  const termo = $("#busca-jogo").value.trim().toLowerCase();
  const lista = $("#lista-jogos");
  lista.replaceChildren();
  const visiveis = estado.jogos.filter((j) => j.nome.toLowerCase().includes(termo));
  if (!visiveis.length) {
    lista.append(el("li", { class: "vazio" }, "Nenhum jogo encontrado."));
    return;
  }
  for (const j of visiveis) {
    lista.append(
      el("li", {},
        el("button", { class: "jogo", onclick: () => abrirJogo(j.appid) },
          el("span", { class: "jogo-nome" }, j.nome),
          el("span", { class: "jogo-horas" }, j.horas ? `${j.horas} h` : ""))
      )
    );
  }
}

$("#busca-jogo").addEventListener("input", renderizarBiblioteca);

// ------------------------------------------------------------ checklist
async function abrirJogo(appid) {
  try {
    const q = estado.steamid ? `?steamid=${estado.steamid}` : "";
    estado.jogo = await api(`/api/jogo/${appid}${q}`);
  } catch (err) {
    avisar(err.message);
    return;
  }
  carregarManuais();
  estado.filtro = "todas";
  document.querySelectorAll("[data-filtro]").forEach((b) =>
    b.setAttribute("aria-pressed", String(b.dataset.filtro === "todas"))
  );
  $("#titulo-jogo").textContent = estado.jogo.nome;
  mostrar("tela-jogo");
  renderizarChecklist();
}

$("#btn-voltar").addEventListener("click", () => {
  mostrar(estado.steamid ? "tela-biblioteca" : "tela-perfil");
});

function estaFeita(c) {
  return c.desbloqueada || estado.manuais.has(c.id);
}

function atualizarProgresso() {
  const total = estado.jogo.conquistas.length;
  const feitas = estado.jogo.conquistas.filter(estaFeita).length;
  const pct = total ? Math.round((feitas / total) * 100) : 0;
  $("#prog-num").textContent = `${feitas} de ${total} conquistas`;
  $("#prog-pct").textContent = `${pct}%`;
  $("#prog-barra").style.width = `${pct}%`;
}

function ordenar(lista) {
  const ordem = $("#ordem").value;
  const copia = [...lista];
  if (ordem === "nome") return copia.sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
  const r = (c) => (c.raridade == null ? -1 : c.raridade);
  return copia.sort((a, b) => (ordem === "raridade-desc" ? r(b) - r(a) : r(a) - r(b)));
}

function itemConquista(c) {
  const feita = estaFeita(c);
  const idCaixa = `chk-${c.id}`;

  const caixa = el("input", { type: "checkbox", id: idCaixa, disabled: c.desbloqueada });
  caixa.checked = feita;
  caixa.addEventListener("change", () => {
    if (caixa.checked) estado.manuais.add(c.id);
    else estado.manuais.delete(c.id);
    salvarManuais();
    renderizarChecklist();
  });

  const r = faixaRaridade(c.raridade);
  const descricao = c.descricao
    ? c.descricao
    : c.oculta ? "Conquista oculta: a Steam não revela a descrição." : "";

  return el("li", { class: "conquista" + (feita ? " feita" : "") },
    caixa,
    c.icone ? el("img", { src: c.icone, alt: "", width: 48, height: 48, loading: "lazy" }) : null,
    el("div", { class: "corpo" },
      el("label", { for: idCaixa, class: "nome" }, c.nome),
      descricao ? el("p", { class: "desc" }, descricao) : null,
      c.tags.length ? el("p", { class: "tags" }, c.tags.map((t) => el("span", { class: "tag" }, t))) : null,
      c.guia
        ? el("details", { class: "guia" },
            el("summary", {}, "Como conseguir"),
            el("p", {}, c.guia))
        : null,
      c.desbloqueada ? el("p", { class: "nota" }, "Desbloqueada na Steam") : null
    ),
    el("span", { class: `raridade ${r.classe}` }, r.texto)
  );
}

function renderizarChecklist() {
  atualizarProgresso();
  let lista = estado.jogo.conquistas;
  if (estado.filtro === "pendentes") lista = lista.filter((c) => !estaFeita(c));
  if (estado.filtro === "concluidas") lista = lista.filter(estaFeita);
  lista = ordenar(lista);

  const ul = $("#lista-conquistas");
  ul.replaceChildren();
  if (!lista.length) {
    ul.append(el("li", { class: "vazio" }, "Nada por aqui com esse filtro."));
    return;
  }
  for (const c of lista) ul.append(itemConquista(c));
}

document.querySelectorAll("[data-filtro]").forEach((b) =>
  b.addEventListener("click", () => {
    estado.filtro = b.dataset.filtro;
    document.querySelectorAll("[data-filtro]").forEach((x) =>
      x.setAttribute("aria-pressed", String(x === b))
    );
    renderizarChecklist();
  })
);
$("#ordem").addEventListener("change", renderizarChecklist);

// ------------------------------------------------------------ início
if (estado.steamid) {
  abrirPerfil(estado.steamid).catch(() => mostrar("tela-perfil"));
}
