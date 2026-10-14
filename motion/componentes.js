// Biblioteca única de componentes de cena (T18).
// Tudo é função do tempo T em segundos e nada usa relógio: render(T) é determinístico.
// Nada aqui conhece um caso (R14): textos, fontes, tempos e cores vêm de DADOS, escrito pelo gerador
// (scripts/cenas.py) a partir do plano, do catálogo de fontes e do estilo do canal.
(function () {
  const D = window.DADOS;
  const C = D.estilo.cores;
  const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));
  const p = (t, a, b) => b <= a ? (t >= a ? 1 : 0) : clamp((t - a) / (b - a));
  // texto do plano entra como texto, nunca como HTML
  const esc = x => String(x ?? '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const eo = x => 1 - Math.pow(1 - x, 3);
  const eio = x => x < .5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2;
  const tw = (s, t, a, cps = 28) => s.slice(0, Math.floor(clamp((t - a) * cps, 0, s.length)));
  const src = id => D.recursos[id];
  const COR = { papel: C.papel, ambar: C.ambar, vermelho: C.vermelho, apagado: C.apagado, tinta: C.tinta };
  // papel com transparência, para textos secundários (mesma cor, menos peso)
  const papelA = a => { const h = C.papel.replace('#', ''); const n = parseInt(h, 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };
  const fundoA = a => { const h = C.fundo.replace('#', ''); const n = parseInt(h, 16); return `rgba(${n >> 16 & 255},${n >> 8 & 255},${n & 255},${a})`; };

  // ---------- peças ----------
  function retratoCartao(id, t, a, b, legenda, altura = 700, largMax = null) {
    const k = eo(p(t, a, a + .5));
    return `<div class="abs" style="left:50%;top:50%;transform:translate(-50%,-50%) rotate(${-2 + k}deg) scale(${1.04 - .04 * eio(p(t, a, b))});opacity:${k}"><div style="background:${C.papel};padding:22px 22px 80px;box-shadow:0 40px 90px rgba(0,0,0,.8)"><img src="${src(id)}" style="${largMax ? `width:${largMax}px;height:auto;max-height:${altura}px;object-fit:contain` : `height:${altura}px`};display:block;filter:grayscale(1) contrast(1.1)"></div><div class="tw" style="position:absolute;left:22px;bottom:24px;font-size:24px;color:${C.tinta};text-shadow:none">${esc(legenda)}</div></div>`;
  }
  function circulo(cx, cy, rx, ry, t, a, sai = 1e9) {
    const k = eo(p(t, a, a + .5)), o = 1 - p(t, sai, sai + .3);
    return `<svg class="abs" style="left:0;top:0;overflow:visible" width="10" height="10"><path d="M${cx + rx},${cy} A${rx},${ry} 0 1,1 ${cx + rx * .97},${cy - ry * .25}" pathLength="1" fill="none" stroke="${C.vermelho}" stroke-width="7" stroke-linecap="round" stroke-dasharray="1" stroke-dashoffset="${1 - k}" opacity="${o}" transform="rotate(-4 ${cx} ${cy})"/></svg>`;
  }
  function fato(t, f, left = 1180, largura = 640) {
    return `<div class="abs" style="left:${left}px;top:${f.top ?? 380}px;width:${largura}px;opacity:${p(t, f.em, f.em + .35)}"><div class="tw" style="font-size:26px;letter-spacing:6px;color:${C.ambar}">${esc(f.rotulo)}</div><div style="font-size:${f.tamanho ?? 64}px;font-weight:700;line-height:1.05;margin-top:8px;color:${COR[f.cor] || C.papel}">${esc(f.valor)}</div>${f.sub ? `<div class="tw" style="font-size:30px;margin-top:10px;opacity:${p(t, f.sub_em ?? f.em, (f.sub_em ?? f.em) + .35)}">${esc(f.sub)}</div>` : ''}</div>`;
  }

  // ---------- componentes de cena: (t, cena) -> html ----------
  const COMP = {};

  // foto em tela cheia com movimento lento de câmera
  COMP.foto = (t, c) => {
    const o = c.params || {}, k = eio(p(t, c.ini, c.fim));
    const z = (o.z0 ?? 1.12) + ((o.z1 ?? 1.0) - (o.z0 ?? 1.12)) * k;
    const x = (o.x0 ?? 0) + ((o.x1 ?? 0) - (o.x0 ?? 0)) * k, y = (o.y0 ?? 0) + ((o.y1 ?? 0) - (o.y0 ?? 0)) * k;
    return `<div class="abs" style="inset:0;overflow:hidden;background:#000"><img src="${src(c.fonte)}" style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;object-position:${o.pos || '50% 50%'};transform:translate(${x}px,${y}px) scale(${z});filter:grayscale(${o.gs ?? .6}) sepia(.22) contrast(1.15) brightness(${o.br ?? .55})"></div>
  <div class="abs" style="inset:0;background:linear-gradient(180deg,${fundoA(.55)} 0%,${fundoA(.05)} 40%,${fundoA(.75)} 100%)"></div>
  ${o.credito ? `<div class="abs" style="right:28px;bottom:22px;font-size:18px;color:${papelA(.55)}">${esc(o.credito)}</div>` : ''}`;
  };

  // retrato em moldura de papel, centralizado; opcionalmente troca para outra foto (volta no tempo)
  COMP.retrato = (t, c) => {
    const o = c.params || {};
    if (!o.troca) return retratoCartao(c.fonte, t, c.ini, c.fim, o.legenda);
    const tr = o.troca, k = p(t, tr.em, tr.em + .3);
    return `<div style="position:absolute;inset:0;opacity:${1 - k}">${retratoCartao(c.fonte, t, c.ini, c.fim, o.legenda)}</div>
  <div style="position:absolute;inset:0;opacity:${k}">${retratoCartao(tr.fonte, t, tr.em, c.fim, tr.legenda)}</div>`;
  };

  // retrato à esquerda, fatos na margem direita (M04: texto fora da imagem)
  COMP.fotoFato = (t, c) => {
    const o = c.params || {};
    return `<div style="position:absolute;inset:0;transform:translateX(${o.desloca ?? -300}px)">${retratoCartao(c.fonte, t, c.ini, c.fim, o.legenda)}</div>`;
  };

  // janela de arquivo: o próprio quadro desfocado ao fundo, moldura, linhas de varredura e fonte acima
  COMP.arquivo = (t, c) => {
    const o = c.params || {}, cl = c.clip;
    const pos = (cl.de - cl.trecho0) + (t - c.ini) * cl.velocidade;
    const i = Math.min(cl.quadros, Math.max(1, Math.floor(pos * D.estilo.fps) + 1));
    const f = `${cl.dir}/f${String(i).padStart(4, '0')}.jpg`;
    const k = eo(p(t, c.ini, c.ini + .25)), z = 1 + (o.zoom ?? .04) * p(t, c.ini, c.ini + 3);
    const w = o.w ?? 1240, h = o.h ?? 800, x = o.x ?? 0, esq = 340 + x - (w - 1240) / 2;
    return `<div class="abs" style="inset:0;overflow:hidden;background:#000"><img src="${f}" style="position:absolute;inset:-40px;width:calc(100% + 80px);height:calc(100% + 80px);object-fit:cover;filter:blur(28px) brightness(.35) grayscale(.5)"></div>
  <div class="abs" style="left:calc(50% + ${x}px);top:50%;width:${w}px;height:${h}px;transform:translate(-50%,-50%) scale(${.96 + .04 * k});opacity:${k};box-shadow:0 40px 90px rgba(0,0,0,.8);outline:3px solid ${papelA(.85)};outline-offset:10px;overflow:hidden">
    <img src="${f}" style="width:100%;height:100%;object-fit:cover;object-position:${o.pos || '50% 40%'};transform:scale(${z});filter:contrast(1.12) saturate(.75) brightness(.95)">
    <div style="position:absolute;inset:0;background:repeating-linear-gradient(0deg,rgba(0,0,0,.18) 0 2px,rgba(0,0,0,0) 2px 4px)"></div></div>
  ${o.rotulo ? `<div class="abs tw" style="left:${esq}px;top:62px;font-size:28px;letter-spacing:8px;color:${C.papel};opacity:${p(t, c.ini + .1, c.ini + .4)}"><span style="color:${C.vermelho}">■</span> ${esc(o.rotulo)}</div>` : ''}
  <div class="abs tw" style="left:${esq}px;top:${o.rotulo ? 102 : 90}px;font-size:18px;letter-spacing:4px;color:${papelA(.55)}">ARQUIVO · ${esc(cl.fonte_texto)}</div>`;
  };

  // mural de documentos: a câmera passa de um cartão para o próximo; o próximo só aparece na sua vez
  COMP.mural = (t, c) => {
    const o = c.params || {}, itens = o.itens || [];
    let foco = 0, pos = 0;
    itens.forEach((it, i) => { if (t >= it.em) foco = i; if (i > 0) pos += eio(p(t, it.em - .45, it.em + .15)); });
    let h = `<div class="abs" style="inset:0;background:${C.fundo}"></div>`;
    itens.forEach((it, i) => {
      const d = Math.abs(i - pos), x = 760 + (i - pos) * 700, sc = 1 - .25 * Math.min(1, d);
      const op = (1 - .6 * Math.min(1, d)) * (i > pos ? 1 - clamp(i - pos) : 1);
      const fs = it.fontes || [];
      const corpo = fs.length > 1 || it.largura
        ? fs.map((id, j) => `<img src="${src(id)}" style="width:${it.largura ?? 760}px;display:block;${j ? 'margin-top:14px;' : ''}filter:sepia(.2) contrast(1.05)">`).join('')
        : `<img src="${src(fs[0])}" style="height:560px;display:block;filter:grayscale(1) contrast(1.1)"><div class="tw" style="color:${C.tinta};font-size:22px;margin-top:14px;text-shadow:none">${esc(it.legenda)}</div>`;
      h += `<div class="abs" style="left:${x}px;top:520px;transform:translate(-50%,-50%) scale(${sc}) rotate(${i % 2 ? 1.5 : -1.5}deg);opacity:${op * p(t, c.ini, c.ini + .35)}"><div style="background:${C.papel};padding:18px;box-shadow:0 40px 90px rgba(0,0,0,.8)">${corpo}</div>
      ${(it.circulos || []).map(q => circulo(q.x, q.y, q.rx, q.ry, t, q.em)).join('')}</div>`;
    });
    const it = itens[foco] || {};
    h += `<div class="abs" style="left:1260px;top:360px;width:600px;opacity:${p(t, (it.em ?? c.ini) + .1, (it.em ?? c.ini) + .45)}"><div class="tw" style="font-size:26px;letter-spacing:6px;color:${C.ambar}">${esc(it.rotulo)}</div><div style="font-size:64px;font-weight:700;line-height:1.05;margin-top:8px">${esc(it.valor)}</div></div>`;
    if (it.fonte_texto) h += `<div class="abs tw" style="left:120px;top:960px;font-size:18px;letter-spacing:4px;color:${papelA(.55)}">${esc(it.fonte_texto)}</div>`;
    return h;
  };

  // mapa: contorno de terra projetado pelo gerador, rota tracejada da origem aos pontos na ordem da narração
  COMP.mapa = (t, c) => {
    const o = c.params || {}, m = c.mapa;
    const vistos = m.pontos.filter(q => t >= q.em - .25);
    const rota = [m.origem, ...vistos].map(q => `${q.x},${q.y}`).join(' ');
    let h = `<svg width="1920" height="1080"><path d="${m.terra}" fill="#18181a" stroke="${papelA(.35)}" stroke-width="1.2" opacity="${p(t, c.ini, c.ini + .5)}"/>
   <polyline points="${rota}" fill="none" stroke="${C.vermelho}" stroke-width="3" stroke-dasharray="10 8" opacity=".9"/>
   <circle cx="${m.origem.x}" cy="${m.origem.y}" r="9" fill="${C.papel}"/>
   <text x="${m.origem.x - 16}" y="${m.origem.y - 18}" text-anchor="end" font-size="30" fill="${C.papel}" font-family='${D.estilo.fontes.display}'>${esc(m.origem.nome.toUpperCase())}</text>`;
    m.pontos.forEach(q => {
      const k = eo(p(t, q.em - .25, q.em + .15)); if (k <= 0) return;
      h += `<circle cx="${q.x}" cy="${q.y}" r="${12 * k}" fill="${C.vermelho}"/><text x="${q.x + (q.dx ?? 18)}" y="${q.y + (q.dy ?? -30)}" text-anchor="${q.alinhar || 'start'}" font-size="30" font-weight="700" fill="${C.papel}" opacity="${k}" font-family='${D.estilo.fontes.display}'>${esc(q.nome.toUpperCase())}</text>`;
    });
    return h + `</svg>${o.titulo ? `<div class="abs tw" style="left:120px;top:150px;font-size:30px;letter-spacing:8px;opacity:${p(t, c.ini + .2, c.ini + .6)}">${esc(o.titulo)}</div>` : ''}`;
  };

  // linha da vida (M17): fotos reais nos anos; a câmera anda pelos anos dados em quadros-chave
  function anoEm(t, anos) {
    if (t <= anos[0][0]) return anos[0][1];
    for (let i = 1; i < anos.length; i++) if (t <= anos[i][0]) {
      const [t0, a0] = anos[i - 1], [t1, a1] = anos[i];
      return a0 + (a1 - a0) * eio(p(t, t0, t1));
    }
    return anos[anos.length - 1][1];
  }
  COMP.linhaVida = (t, c) => {
    const o = c.params || {}, ano = anoEm(t, o.anos || [[c.ini, 1950]]), PX = o.px ?? 70;
    const escuro = (o.escurece || []).reduce((v, [a, b, alvo]) => t >= a ? v + (alvo - v) * p(t, a, b) : v, 0);
    const X = y => 960 + (y - ano) * PX; let h = '';
    for (let y = Math.floor(ano - 960 / PX) - 1; y <= ano + 960 / PX + 1; y++) {
      const x = X(y); if (x < -50 || x > 1970) continue; const big = y % 10 === 0;
      h += `<div class="abs" style="left:${x}px;top:${big ? 740 : 752}px;width:2px;height:${big ? 28 : 10}px;background:${papelA(big ? .6 : .25)}"></div>`;
      if (big) h += `<div class="abs tw" style="left:${x - 40}px;top:780px;width:80px;text-align:center;font-size:22px;color:${papelA(.55)};text-shadow:none">${y}</div>`;
    }
    h += `<div class="abs" style="left:0;right:0;top:752px;height:2px;background:${papelA(.35)}"></div>`;
    const cap = o.capitulo, ini = o.titulo_em ?? c.ini;
    if (o.faixa) h += `<div class="abs" style="left:${X(o.faixa[0])}px;top:749px;width:${(o.faixa[1] - o.faixa[0]) * PX}px;height:8px;background:${C.vermelho};opacity:${p(t, ini + 1.6, ini + 2.0)}"></div>`;
    (o.fotos || []).forEach(({ ano: y, fonte }) => {
      const x = X(y); if (x < -300 || x > 2220) return; const foco = Math.max(0, 1 - Math.abs(y - ano) / 7);
      const sc = .62 + .38 * foco, op = (.35 + .65 * foco) * (1 - escuro);
      h += `<div class="abs" style="left:${x}px;top:430px;transform:translate(-50%,-50%) scale(${sc}) rotate(${(((y % 3) + 3) % 3 - 1) * 1.5}deg);opacity:${op}"><div style="background:${C.papel};padding:12px 12px 46px;box-shadow:0 30px 70px rgba(0,0,0,.75)"><img src="${src(fonte)}" style="height:380px;width:300px;object-fit:cover;display:block;filter:grayscale(1) contrast(1.1) brightness(${.6 + .4 * foco})"></div><div class="tw" style="position:absolute;left:0;right:0;bottom:12px;text-align:center;font-size:24px;color:${C.tinta};text-shadow:none">${y}</div></div>`;
    });
    const contorno = `<div class="abs" style="left:0;right:0;top:120px;text-align:center;font-size:300px;font-weight:700;letter-spacing:10px;color:transparent;-webkit-text-stroke:2px ${papelA(.14 * (1 - escuro))};text-shadow:none">${Math.round(ano)}</div>`;
    if (cap) h += `<div class="abs tw" style="left:0;right:0;top:860px;text-align:center;font-size:24px;letter-spacing:10px;color:${C.apagado};opacity:${p(t, ini + 1.7, ini + 2.1)}">CAPÍTULO ${esc(cap.numero)} DE ${esc(cap.total)} · ${esc(String(cap.periodo).toUpperCase())}</div>
      <div class="abs" style="left:0;right:0;top:900px;text-align:center;font-size:96px;font-weight:700;opacity:${p(t, ini + 1.9, ini + 2.4)};transform:translateY(${(1 - eo(p(t, ini + 1.9, ini + 2.5))) * 20}px)">${esc(String(cap.titulo).toUpperCase())}</div>`;
    return `<div style="position:absolute;inset:0;opacity:${o.entra ? p(t, c.ini, c.ini + o.entra) : 1}">${contorno}${h}</div>`;
  };

  // lista ao lado de um retrato, com carimbo (ex.: os itens de um kit)
  COMP.lista = (t, c) => {
    const o = c.params || {};
    return `<div style="position:absolute;inset:0;transform:translateX(-330px)">${retratoCartao(c.fonte, t, c.ini, c.fim, o.legenda, 700, o.largura_max)}</div>
  <div class="abs tw" style="left:1120px;top:250px;font-size:26px;letter-spacing:6px;color:${C.ambar};opacity:${p(t, c.ini, c.ini + .3)}">${esc(o.titulo)}</div>`
      + (o.itens || []).map((it, i) => `<div class="abs tw" style="left:1120px;top:${310 + i * 62}px;font-size:40px;opacity:${p(t, it.em - .1, it.em + .2)}"><span style="color:${C.vermelho}">■</span> ${esc(it.texto)}</div>`).join('')
      + (o.carimbo ? `<div class="abs" style="left:1110px;top:${310 + (o.itens || []).length * 62 + 30}px;font-size:120px;font-weight:700;color:${C.vermelho};letter-spacing:6px;opacity:${p(t, o.carimbo.em, o.carimbo.em + .15)};transform:rotate(-4deg) scale(${1.25 - .25 * eo(p(t, o.carimbo.em, o.carimbo.em + .25))})">${esc(o.carimbo.texto)}</div>` : '')
      + (o.sub ? `<div class="abs tw" style="left:1120px;top:${310 + (o.itens || []).length * 62 + 190}px;font-size:36px;opacity:${p(t, o.sub.em, o.sub.em + .4)}">${esc(o.sub.texto)}</div>` : '');
  };

  // encerramento: botão de inscrição que é "clicado", like e o gancho do próximo episódio (textos vêm do plano)
  COMP.chamada = (t, c) => {
    const o = c.params || {}, ck = o.clique ?? c.ini + 1, lk = o.like ?? ck + .8, px = o.proximo;
    const sai = px ? 1 - p(t, px.em - .4, px.em) : 1;
    const ent = eo(p(t, c.ini, c.ini + .4)), apertado = t >= ck;
    const zoom = 1 + .08 * Math.sin(Math.PI * p(t, ck - .12, ck + .12));
    const mx = 960 + 230 * (1 - eio(p(t, ck - .9, ck - .1))), my = 600 + 160 * (1 - eio(p(t, ck - .9, ck - .1)));
    const mao = t < ck + .5 ? `<svg class="abs" style="left:${mx}px;top:${my}px;opacity:${p(t, ck - 1, ck - .8) * (1 - p(t, ck + .3, ck + .5))}" width="60" height="72" viewBox="0 0 24 29"><path d="M3 1 L3 21 L8 16 L12 26 L15 24.6 L11 15 L18 15 Z" fill="${C.papel}" stroke="${C.fundo}" stroke-width="1.6"/></svg>` : '';
    const lkk = eo(p(t, lk, lk + .35)), pop = 1 + .25 * Math.sin(Math.PI * p(t, lk, lk + .35));
    const like = `<svg class="abs" style="left:1290px;top:478px;opacity:${lkk * sai};transform:scale(${pop})" width="124" height="124" viewBox="0 0 24 24"><path d="M2 21h4V9H2v12zm20-11c0-1.1-.9-2-2-2h-6.3l1-4.6v-.3c0-.4-.2-.8-.4-1.1L13.2 1 6.6 7.6C6.2 7.9 6 8.4 6 9v10c0 1.1.9 2 2 2h9c.8 0 1.5-.5 1.8-1.2l3-7.1c.1-.2.2-.5.2-.7v-2z" fill="${lkk > .5 ? C.vermelho : C.papel}"/></svg>`;
    const botao = `<div class="abs" style="left:960px;top:540px;transform:translate(-50%,-50%) scale(${(.9 + .1 * ent) * zoom});opacity:${ent * sai}"><div style="padding:30px 64px;border-radius:14px;background:${apertado ? C.apagado : C.vermelho};font-size:56px;font-weight:700;letter-spacing:4px;color:${C.papel};white-space:nowrap">${esc(apertado ? (o.botao_depois ?? '✓ ' + (o.botao ?? '')) : o.botao)}</div></div>`;
    const prox = px ? `<div class="abs tw" style="left:0;right:0;top:420px;text-align:center;font-size:30px;letter-spacing:10px;color:${C.ambar};opacity:${p(t, px.em, px.em + .4)}">${esc(px.rotulo)}</div><div class="abs" style="left:160px;right:160px;top:480px;text-align:center;font-size:${px.tamanho ?? 96}px;font-weight:700;line-height:1.05;white-space:pre-line;opacity:${p(t, px.em + .2, px.em + .7)}">${esc(px.titulo)}</div>${px.sub ? `<div class="abs serif" style="left:0;right:0;top:${px.sub_top ?? 640}px;text-align:center;font-size:40px;font-style:italic;opacity:${p(t, px.sub_em ?? px.em + .8, (px.sub_em ?? px.em + .8) + .5)}">${esc(px.sub)}</div>` : ''}` : '';
    return (o.botao ? botao + like + mao : '') + prox;
  };

  // ---------- camadas comuns, por cima de qualquer cena ----------
  const textos = (t, c) => (c.params?.textos || []).map(x => {
    const fam = { display: '', tw: 'tw', serifa: 'serif' }[x.fonte || 'display'];
    const corpo = esc(x.digita ? tw(x.texto, t, x.em, x.cps ?? 24) : x.texto);
    const op = x.digita ? 1 : p(t, x.em, x.em + .35);
    return `<div class="abs ${fam}" style="left:${x.left ?? 0}px;${x.left == null ? 'right:0;text-align:center;' : ''}top:${x.top}px;font-size:${x.tamanho ?? 64}px;font-weight:${x.peso ?? 400};letter-spacing:${x.espaco ?? 0}px;color:${COR[x.cor] || C.papel};opacity:${op}">${corpo}</div>`;
  }).join('');
  // fatos na margem (rótulo + valor), em qualquer componente: params.fatos, params.margem, params.largura
  const fatos = (t, c) => (c.params?.fatos || []).map(f => fato(t, f, c.params.margem ?? 1180, c.params.largura ?? 640)).join('');
  const rotuloIA = (t, c) => c.rotulo_ia ? `<div class="abs tw" style="left:120px;top:62px;font-size:20px;letter-spacing:6px;color:${papelA(.75)};opacity:${p(t, c.ini + .1, c.ini + .4)}">RECONSTITUIÇÃO · IMAGEM GERADA POR IA</div>` : '';
  const rotuloVoz = (t, c) => { const v = c.params?.voz_rotulo; return v ? `<div class="abs tw" style="left:${v.left ?? 120}px;top:${v.top ?? 98}px;font-size:22px;letter-spacing:8px;color:${COR[v.cor] || C.ambar};opacity:${p(t, c.ini + .1, c.ini + .4)}">■ ${esc(v.texto)}</div>` : ''; };
  function legendas(T) {
    for (const v of D.vozes || []) for (const [a, b, txt] of v.legendas || []) if (T >= a && T < b)
      return `<div class="abs" style="left:0;right:0;top:900px;height:180px;background:linear-gradient(180deg,${fundoA(0)},${fundoA(.85)})"></div><div class="abs serif" style="left:180px;right:180px;top:930px;text-align:center;font-size:38px;line-height:1.2;font-style:italic;opacity:${p(T, a, a + .2) * (1 - p(T, b - .15, b))}">${esc(txt)}</div>`;
    return '';
  }
  function guia(T) {
    const g = D.capitulos; if (!g) return '';
    const op = p(T, g.aparece ?? g.ini, (g.aparece ?? g.ini) + .7), k = p(T, g.ini, g.fim), n = g.lista.length;
    const w = 1920 - 240, gap = 14, sw = (w - gap * (n - 1)) / n; let h = '';
    g.lista.forEach(([nome], i) => {
      const x = 120 + i * (sw + gap), c = g.atual - 1;
      const cor = i < c ? papelA(.55) : i === c ? C.vermelho : papelA(.18), fill = i < c ? 1 : i === c ? k : 0;
      h += `<div class="abs tw" style="left:${x}px;top:12px;width:${sw}px;font-size:15px;letter-spacing:1px;color:${i === c ? C.papel : i < c ? papelA(.65) : papelA(.4)};white-space:nowrap;overflow:hidden;text-shadow:none">${i + 1}. ${esc(nome.toUpperCase())}</div>
    <div class="abs" style="left:${x}px;top:36px;width:${sw}px;height:4px;background:${papelA(.16)}"></div><div class="abs" style="left:${x}px;top:36px;width:${sw * fill}px;height:4px;background:${cor}"></div>`;
    });
    return `<div style="position:absolute;inset:0;opacity:${op}">${h}</div>`;
  }

  // ---------- render ----------
  const grao = document.getElementById('grain'), gx = grao.getContext('2d'), img = gx.createImageData(480, 270);
  function rng(seed) { return function () { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function render(T) {
    const c = D.cenas.find(x => T >= x.ini && T < x.fim) || D.cenas[D.cenas.length - 1];
    const html = COMP[c.componente](T, c) + fatos(T, c) + textos(T, c) + rotuloIA(T, c) + rotuloVoz(T, c) + legendas(T) + guia(T);
    document.getElementById('cam').innerHTML = html;
    const r = rng(Math.floor(T * D.estilo.fps) + 99);
    for (let i = 0; i < img.data.length; i += 4) { const v = r() * 255; img.data[i] = img.data[i + 1] = img.data[i + 2] = v; img.data[i + 3] = 255; }
    gx.putImageData(img, 0, 0);
  }
  window.COMPONENTES = Object.keys(COMP);
  window.render = render;
  window.pronto = false;
  Promise.all(Object.values(D.recursos).map(s => new Promise(ok => { const i = new Image(); i.onload = i.onerror = () => i.decode ? i.decode().then(ok, ok) : ok(); i.src = s; })))
    .then(() => { window.pronto = true; });
  render(0);
})();
