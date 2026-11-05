/* Canada Insight: access explorer. Reads only the static files the pipeline publishes (data/...). */
(function () {
  'use strict';
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const pct = v => v == null ? '–' : (v * 100 >= 99.5 && v < 1 ? '>99' : Math.round(v * 100)) + '%';
  const num = v => v == null ? '–' : Math.round(v).toLocaleString('en-CA');
  const metres = m => m >= 1000 ? (m / 1000).toLocaleString('en-CA', { maximumFractionDigits: 1 }) + '\u00a0km' : m + '\u00a0m';

  const BINS = [0.25, 0.5, 0.7, 0.85, 0.95];        // the 0.5 break is the gap rule
  const COLORS_LIGHT = ['#E3B04F', '#F3DDAE', '#CFE5DC', '#8CC3B3', '#3F8F80', '#165A50'];
  const COLORS_DARK = ['#B9842A', '#6B5528', '#2A4A43', '#2F7A6B', '#4FA393', '#93DCCB'];
  const dark = matchMedia('(prefers-color-scheme: dark)');
  const colors = () => dark.matches ? COLORS_DARK : COLORS_LIGHT;
  const colorFor = v => v == null ? getComputedStyle(document.documentElement).getPropertyValue('--nodata').trim() : colors()[BINS.findIndex(b => v < b) === -1 ? 5 : BINS.findIndex(b => v < b)];

  const STATUS = {
    gap: ['tag-gap', 'Measured gap'],
    gap_check: ['tag-check', 'Check inventory'],
    no_gap: ['tag-ok', 'Most homes within reach'],
    too_few_homes: ['tag-na', 'Too few homes'],
  };

  const S = { cities: [], city: null, data: null, areas: null, sources: null, quality: null, kind: null, th: 0,
              filter: 'all', sort: ['share', 1], selected: null, compare: [], q: '', showPts: false,
              people: null, mode: 'near' };
  let map, areaLayer, ptsLayer, layerByCode = {};
  const ptsCache = {};

  async function get(path) {
    const r = await fetch(path, { cache: 'no-cache' });
    if (!r.ok) throw new Error(`${path}: ${r.status}`);
    return path.endsWith('.csv') ? r.text() : r.json();
  }

  // ---------- state in the address bar ----------
  function readHash() {
    const [p, qs] = location.hash.replace(/^#\/?/, '').split('?');
    const [city, kind] = (p || '').split('/');
    const q = new URLSearchParams(qs || '');
    return { city, kind, th: q.get('d') === '800' || q.get('d') === '1' ? 1 : 0, c: q.get('c'), p: q.get('p'), m: q.get('m') };
  }
  function writeHash() {
    if (!S.city) return;
    const q = new URLSearchParams();
    if (S.th) q.set('d', '1');
    if (S.selected) q.set('c', S.selected);
    if (S.people && S.data && S.data.crowding && S.people !== S.data.crowding.default) q.set('p', S.people);
    if (S.mode === 'crowding') q.set('m', 'crowding');
    const h = `#/${S.city.id}/${S.kind}` + (q.toString() ? '?' + q : '');
    if (location.hash !== h) history.replaceState(null, '', h);
  }

  // ---------- boot ----------
  async function boot() {
    try {
      S.cities = (await get('data/cities.json')).cities;
    } catch (e) {
      $('#headline').innerHTML = '<span class="err">The published data could not be loaded. The daily build may still be running; try again in a few minutes.</span>';
      return;
    }
    const sel = $('#city');
    sel.innerHTML = S.cities.map(c => `<option value="${esc(c.id)}" ${c.built_at ? '' : 'disabled'}>${esc(c.name)}${c.built_at ? '' : ' (planned)'}</option>`).join('');
    sel.addEventListener('change', () => openCity(sel.value));
    const h = readHash();
    const first = S.cities.find(c => c.id === h.city && c.built_at) || S.cities.find(c => c.built_at);
    if (!first) { $('#headline').textContent = 'No city has been built yet.'; return; }
    S.th = h.th; S.people = h.p; S.mode = h.m === 'crowding' ? 'crowding' : 'near';
    await openCity(first.id, h.kind, h.c);
  }

  async function openCity(id, kind, code) {
    S.city = S.cities.find(c => c.id === id);
    $('#city').value = id;
    const base = `data/${id}/`;
    [S.data, S.areas, S.sources, S.quality] = await Promise.all(
      ['access.json', 'areas.geojson', 'sources.json', 'quality.json'].map(f => get(base + f)));
    S.kind = S.data.kinds[kind] ? kind : Object.keys(S.data.kinds)[0];
    S.selected = code && S.data.areas[code] ? code : null;
    S.compare = [];
    const cr = S.data.crowding;
    if (!cr || !cr.options[S.people]) S.people = cr ? cr.default : null;
    renderPeople();
    $$('.gy').forEach(e => e.textContent = S.data.growth_year);
    $('#csv').href = base + 'access_by_area.csv';
    $('#built').textContent = `Built ${new Date(S.data.built_at).toLocaleString('en-CA', { dateStyle: 'long', timeStyle: 'short' })} from the sources listed above. Version ${S.data.version}.`;
    renderKinds(); initMap(); renderAll(); renderSources(); renderQuality();
    if (S.selected) focusArea(S.selected);
  }

  // ---------- hero ----------
  function renderKinds() {
    const box = $('#kinds');
    box.innerHTML = Object.entries(S.data.kinds).map(([k, v]) =>
      `<button type="button" data-k="${esc(k)}" aria-pressed="${k === S.kind}">${esc(v.label)}</button>`).join('');
    $$('button', box).forEach(b => b.addEventListener('click', () => { S.kind = b.dataset.k; $$('button', box).forEach(x => x.setAttribute('aria-pressed', x === b)); renderAll(); }));
  }

  function th() { return S.data.kinds[S.kind].thresholds_m; }

  // ---------- crowding (estimate) ----------
  function crowd(kind) { const c = S.data.crowding; return c && c.kinds[kind] ? c.kinds[kind] : null; }
  function crowdVal(kind, code, thIndex) {
    const c = crowd(kind); if (!c || !S.people || !c.by_option[S.people]) return null;
    const d = S.data.kinds[kind].thresholds_m[thIndex ?? S.th];
    const v = c.by_option[S.people][String(d)];
    return v ? v[code] ?? null : null;
  }
  function crowdFmt(kind, v) {
    if (v == null) return '–';
    const c = crowd(kind);
    return (v >= 10 ? Math.round(v) : v.toFixed(v >= 1 ? 1 : 2)) + (c.people === 'children' ? ' per 1,000 children' : ' ha per 1,000 residents');
  }
  function crowdShort(kind, v) { return v == null ? '–' : (v >= 10 ? Math.round(v) : v.toFixed(v >= 1 ? 1 : 2)); }
  function crowdUnitShort(kind) { const c = crowd(kind); return c ? (c.people === 'children' ? 'Playgrounds per 1,000 children' : 'Park ha per 1,000 residents') : ''; }
  function renderPeople() {
    const box = $('#people'), cr = S.data.crowding;
    if (!cr) { box.hidden = true; return; }
    box.hidden = false;
    $('#people-seg').innerHTML = Object.entries(cr.options).map(([k, o]) =>
      `<button type="button" data-p="${esc(k)}" aria-pressed="${k === S.people}">${esc(o.label)}</button>`).join('');
    $$('#people-seg button').forEach(b => b.addEventListener('click', () => { S.people = b.dataset.p; renderPeople(); renderAll(); }));
    $('#people-about').textContent = (cr.options[S.people] || {}).about || '';
  }

  function renderHero() {
    const k = S.data.kinds[S.kind], c = S.data.city_access[S.kind], [p, s] = th();
    const name = S.data.name;
    $('#th0').textContent = metres(p); $('#th1').textContent = metres(s);
    $('#headline').innerHTML = `<strong>${pct(c.share_primary)}</strong> of ${esc(name)}'s homes are within ${metres(p)} of a ${esc(k.label.toLowerCase())}, and <strong>${pct(c.share_secondary)}</strong> within ${metres(s)}.`;
    const bars = [['Homes built before ' + S.data.growth_year, c.share_old_primary, ''], ['Homes built since ' + S.data.growth_year, c.share_new_primary, 'new']];
    $('#pace').innerHTML = `<p class="fine" style="margin:0 0 4px">Within ${metres(p)}:</p>` + bars.map(([l, v, cls]) =>
      `<div class="bar ${cls}"><span class="lbl">${esc(l)}</span><span class="track" role="img" aria-label="${esc(l)}: ${pct(v)}"><span class="fill" style="width:${(v || 0) * 100}%"></span></span><span class="v">${pct(v)}</span></div>`).join('');
    const gap = c.share_new_primary != null && c.share_old_primary != null ? Math.round((c.share_new_primary - c.share_old_primary) * 100) : null;
    const pace = gap == null ? '' : gap <= -5 ? `New homes are less well served by ${-gap} points. ` : gap >= 5 ? `New homes are better served by ${gap} points. ` : 'New and older homes are about equally served. ';
    const sens = S.data.sensitivity[S.kind];
    const cv = crowdVal(S.kind, '_all', 0);
    const crowdNote = cv == null ? '' : ` Within ${metres(p)}, Calgary has ${crowdFmt(S.kind, cv)} who can reach them <span class="kind kind-estimate">Estimate</span> (${esc(S.data.crowding.options[S.people].label)}).`;
    $('#headline-note').innerHTML = `${pace}${esc(k.threshold_basis || '')} ${k.threshold_url ? `<a href="${esc(k.threshold_url)}">Source</a>.` : ''} Communities with a measured gap: ${sens.gaps_at_primary} at ${metres(p)}, ${sens.gaps_at_secondary} at ${metres(s)}. <span class="kind kind-calculated">Calculated</span>${crowdNote}`;
    drawRings(c.share_primary, c.share_secondary, p, s);
  }

  function drawRings(a, b, p, s) {
    const R0 = 70, R1 = 118, W0 = 16, W1 = 16, C0 = 2 * Math.PI * R0, C1 = 2 * Math.PI * R1;
    const fig = $('#rings');
    if (!fig.firstChild) {
      fig.innerHTML = `<svg viewBox="-150 -150 300 300">
        <circle class="track" r="${R1}" stroke-width="${W1}"/><circle class="track" r="${R0}" stroke-width="${W0}"/>
        <circle class="arc1" r="${R1}" stroke-width="${W1}" transform="rotate(-90)" stroke-dasharray="${C1}" stroke-dashoffset="${C1}"/>
        <circle class="arc0" r="${R0}" stroke-width="${W0}" transform="rotate(-90)" stroke-dasharray="${C0}" stroke-dashoffset="${C0}"/>
        <circle class="hub" r="7"/>
        <text class="l0" x="0" y="${-R0 + 32}" text-anchor="middle"></text>
        <text class="l1" x="0" y="${-R1 + 32}" text-anchor="middle"></text></svg>`;
    }
    requestAnimationFrame(() => {
      $('.arc0', fig).style.strokeDashoffset = C0 * (1 - (a || 0));
      $('.arc1', fig).style.strokeDashoffset = C1 * (1 - (b || 0));
    });
    $('.l0', fig).textContent = metres(p); $('.l1', fig).textContent = metres(s);
  }

  // ---------- map ----------
  function initMap() {
    if (!window.L) { $('#map').innerHTML = '<p class="hint" style="padding:16px">The map could not load. The table below has every figure.</p>'; return; }
    if (!map) {
      map = L.map('map', { zoomSnap: 0.25, attributionControl: true, scrollWheelZoom: false });
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png', { maxZoom: 18, subdomains: 'abcd',
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors, © <a href="https://carto.com/attributions">CARTO</a>' }).addTo(map);
      map.createPane('labels'); map.getPane('labels').style.zIndex = 650; map.getPane('labels').style.pointerEvents = 'none';
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png', { maxZoom: 18, subdomains: 'abcd', pane: 'labels' }).addTo(map);
      map.on('focus', () => map.scrollWheelZoom.enable()); map.on('blur', () => map.scrollWheelZoom.disable());
    }
    if (areaLayer) areaLayer.remove();
    layerByCode = {};
    areaLayer = L.geoJSON(S.areas, {
      style: f => styleArea(f.properties.code),
      onEachFeature: (f, layer) => {
        layerByCode[f.properties.code] = layer;
        layer.on('click', () => select(f.properties.code));
        layer.bindTooltip(() => tip(f.properties.code), { sticky: true });
      },
    }).addTo(map);
    map.fitBounds(areaLayer.getBounds(), { padding: [10, 10] });
  }

  function share(code) { const a = S.data.areas[code]; return a ? a.access[S.kind][S.th ? 'share_secondary' : 'share_primary'] : null; }
  const RBINS = [0.5, 0.75, 1, 1.5, 2];
  function crowdRatio(code) {
    const v = crowdVal(S.kind, code), c = crowdVal(S.kind, '_all');
    return v == null || !c ? null : v / c;
  }
  function useCrowd() { return S.mode === 'crowding' && crowd(S.kind) && S.people; }
  function stat(code) { const a = S.data.areas[code]; return a && a.access[S.kind]; }

  function styleArea(code) {
    const st = stat(code), cm = useCrowd();
    const v = cm ? crowdRatio(code) : (st && st.status !== 'too_few_homes' ? share(code) : null);
    const sel = code === S.selected, chk = !cm && st && st.status === 'gap_check' && !S.th;
    if (cm) {
      const i = v == null ? -1 : RBINS.findIndex(b => v < b);
      const fill = v == null ? getComputedStyle(document.documentElement).getPropertyValue('--nodata').trim() : colors()[i === -1 ? 5 : i];
      return { fillColor: fill, fillOpacity: v == null ? 0.35 : 0.82, color: sel ? (dark.matches ? '#fff' : '#1C2A28') : (dark.matches ? '#121A19' : '#ffffff'), weight: sel ? 3 : 0.8, dashArray: null };
    }
    return { fillColor: colorFor(v), fillOpacity: v == null ? 0.35 : 0.82, color: sel ? (dark.matches ? '#fff' : '#1C2A28') : chk ? '#A86A0C' : (dark.matches ? '#121A19' : '#ffffff'),
             weight: sel ? 3 : chk ? 2 : 0.8, dashArray: chk && !sel ? '4 3' : null };
  }
  function tip(code) {
    const a = S.data.areas[code];
    if (!a) return esc(nameOf(code)) + ': no homes on the roll';
    const st = a.access[S.kind];
    if (st.status === 'too_few_homes') return `<strong>${esc(a.name)}</strong><br>Too few homes to measure`;
    if (useCrowd()) return `<strong>${esc(a.name)}</strong><br>${crowdFmt(S.kind, crowdVal(S.kind, code))} within ${metres(th()[S.th])}`;
    return `<strong>${esc(a.name)}</strong><br>${pct(share(code))} of homes within ${metres(th()[S.th])}`;
  }
  function nameOf(code) {
    const f = S.areas.features.find(x => x.properties.code === code);
    return (S.data.areas[code] || {}).name || (f && f.properties.name) || code;
  }

  function renderLegend() {
    const mt = $('#mode-wrap');
    mt.hidden = !crowd(S.kind);
    $$('#mode-seg button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.m === (crowd(S.kind) ? S.mode : 'near'))));
    if (useCrowd()) {
      $('#legend').innerHTML = `<div>${crowdUnitShort(S.kind)} within ${metres(th()[S.th])}, against Calgary</div><div class="sw">${colors().map(c => `<span style="background:${c}"></span>`).join('')}</div>
        <div class="ticks">${['', '½', '¾', 'same', '1½×', '2×', ''].map(x => `<span>${x}</span>`).join('')}</div>
        <div class="nd"><i></i>No estimate (no ${crowd(S.kind).people} counted)</div><div class="nd"><span class="kind kind-estimate" style="margin:0">Estimate</span> ${esc(S.data.crowding.options[S.people].label)}</div>`;
      return;
    }
    const t = ['0', '25', '50', '70', '85', '95', '100'];
    $('#legend').innerHTML = `<div>Homes within ${metres(th()[S.th])}</div><div class="sw">${colors().map(c => `<span style="background:${c}"></span>`).join('')}</div>
      <div class="ticks">${['0', '25', '50', '70', '85', '95', '100%'].map(x => `<span>${x}</span>`).join('')}</div>
      <div class="nd"><i></i>No homes or too few to measure</div>` + (S.th ? '' : '<div class="nd"><i style="background:none;border:2px dashed #A86A0C"></i>Gap, check inventory</div>');
    void t;
  }

  async function renderPoints() {
    if (ptsLayer) { ptsLayer.remove(); ptsLayer = null; }
    if (!S.showPts || !map) return;
    const key = S.city.id + '/' + S.kind;
    const gj = ptsCache[key] || (ptsCache[key] = await get(`data/${S.city.id}/amenities/${S.kind}.geojson`));
    const color = dark.matches ? '#F1F4F2' : '#1C2A28';
    ptsLayer = L.geoJSON(gj, {
      pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 3.5, color, weight: 1, fillColor: color, fillOpacity: 0.9, interactive: false }),
      style: () => ({ color, weight: 1, fillColor: color, fillOpacity: 0.25, interactive: false }),
    }).addTo(map);
  }

  // ---------- profile and compare ----------
  function select(code) {
    S.selected = code;
    if (S.compare.length && !S.compare.includes(code)) { /* keep compare as is */ }
    renderProfile(); restyle(); markRow(); writeHash();
  }
  function focusArea(code) {
    const l = layerByCode[code];
    if (l && map) map.fitBounds(l.getBounds(), { maxZoom: 14, padding: [40, 40] });
  }

  function renderProfile() {
    const box = $('#profile'), code = S.selected, a = code && S.data.areas[code];
    if (!code) { box.innerHTML = '<p class="hint">Select a community on the map or in the table to see every amenity for it, and add up to three to compare.</p>'; return; }
    if (!a) { box.innerHTML = `<h3>${esc(nameOf(code))}</h3><p class="sub">No homes on the property roll, so access is not measured here.</p>`; return; }
    const newShare = a.units ? a.units_new / a.units : 0;
    const rows = Object.entries(S.data.kinds).map(([k, kd]) => {
      const st = a.access[k], [p, s] = kd.thresholds_m, [cls, lab] = STATUS[st.status];
      const cityv = S.data.city_access[k].share_primary;
      return `<div class="p-row ${k === S.kind ? 'sel' : ''}">
        <div class="t"><span>${esc(kd.label)}</span><span class="tag ${cls}">${lab}</span></div>
        <div class="mini">
          <span class="k">Within ${metres(p)}</span><span>${pct(st.share_primary)} <span class="k">(city ${pct(cityv)})</span></span>
          <span class="k">Within ${metres(s)}</span><span>${pct(st.share_secondary)}</span>
          <span class="k">Built since ${S.data.growth_year}, within ${metres(p)}</span><span>${st.share_new_primary == null ? 'none built' : pct(st.share_new_primary)}</span>
          <span class="k">Median distance</span><span>${st.median_m == null ? (st.median_beyond_cap ? 'over ' + metres(s) : '–') : metres(st.median_m)}</span>
          ${crowd(k) && S.people ? `<span class="k">${crowdUnitShort(k)} within ${metres(p)} <span class="kind kind-estimate">Estimate</span></span><span>${crowdShort(k, crowdVal(k, code, 0))} <span class="k">(city ${crowdShort(k, crowdVal(k, '_all', 0))})</span></span>` : ''}
        </div></div>`;
    }).join('');
    const inCmp = S.compare.includes(code);
    box.innerHTML = `<h3>${esc(a.name)}</h3>
      <p class="sub">${num(a.units)} homes on the property roll, ${Math.round(newShare * 100)}% built since ${S.data.growth_year} <span class="kind kind-official">Official</span>${a.homes_reference != null ? `<br><span title="${esc((S.data.homes.reference || {}).note || '')}">Calgary Data Desk counts ${num(a.homes_reference)} lived in (from a year after they're built)</span>` : ''}${(a.attrs && a.attrs.sector) ? '<br>' + esc(a.attrs.sector[0] + a.attrs.sector.slice(1).toLowerCase()) + ' sector' : ''}</p>
      ${rows}
      <div class="actions"><button class="btn" id="cmp-btn" ${!inCmp && S.compare.length >= 3 ? 'disabled' : ''}>${inCmp ? 'Remove from comparison' : 'Add to comparison'}</button>
      <button class="btn" id="zoom-btn">Zoom to it</button></div>`;
    $('#cmp-btn').addEventListener('click', () => {
      S.compare = inCmp ? S.compare.filter(c => c !== code) : [...S.compare, code].slice(0, 3);
      renderProfile(); renderCompare();
    });
    $('#zoom-btn').addEventListener('click', () => focusArea(code));
  }

  function renderCompare() {
    const box = $('#compare');
    const list = S.compare.filter(c => S.data.areas[c]);
    if (!list.length) { box.hidden = true; return; }
    box.hidden = false;
    const kinds = Object.entries(S.data.kinds);
    box.innerHTML = `<h3><span>Comparing ${list.length} ${list.length === 1 ? 'community' : 'communities'} with ${esc(S.data.name)}</span></h3>
      <div class="table-wrap"><table class="cmp"><thead><tr><th scope="col">Share of homes within walking distance</th>${list.map(c => `<th scope="col">${esc(S.data.areas[c].name)} <button class="x" data-x="${esc(c)}" aria-label="Remove ${esc(S.data.areas[c].name)}">×</button></th>`).join('')}<th scope="col">${esc(S.data.name)}</th></tr></thead>
      <tbody><tr><td>Homes on the property roll</td>${list.map(c => `<td>${num(S.data.areas[c].units)}</td>`).join('')}<td>${num(S.data.homes.units)}</td></tr>
      ${kinds.map(([k, kd]) => `<tr><td>${esc(kd.label)}, ${metres(kd.thresholds_m[0])}</td>${list.map(c => `<td>${pct(S.data.areas[c].access[k].share_primary)}</td>`).join('')}<td>${pct(S.data.city_access[k].share_primary)}</td></tr>`
        + (crowd(k) && S.people ? `<tr><td>${crowdUnitShort(k)} within ${metres(kd.thresholds_m[0])} <span class="kind kind-estimate">Estimate</span></td>${list.map(c => `<td>${crowdShort(k, crowdVal(k, c, 0))}</td>`).join('')}<td>${crowdShort(k, crowdVal(k, '_all', 0))}</td></tr>` : '')).join('')}
      </tbody></table></div>`;
    $$('.x', box).forEach(b => b.addEventListener('click', () => { S.compare = S.compare.filter(c => c !== b.dataset.x); renderCompare(); renderProfile(); }));
  }

  // ---------- table ----------
  function rowsFor() {
    const q = S.q.trim().toLowerCase();
    let rows = Object.entries(S.data.areas).map(([code, a]) => {
      const st = a.access[S.kind];
      return { code, name: a.name, units: a.units, share: st.status === 'too_few_homes' ? null : (S.th ? st.share_secondary : st.share_primary),
               nw: st.share_new_primary, unew: a.units_new, median: st.median_m ?? (st.median_beyond_cap ? 1e9 : null), status: st.status,
               crowd: crowdVal(S.kind, code) };
    });
    if (q) rows = rows.filter(r => r.name.toLowerCase().includes(q));
    if (S.filter !== 'all') rows = rows.filter(r => r.status === S.filter);
    const [k, dir] = S.sort, order = { gap: 0, gap_check: 1, no_gap: 2, too_few_homes: 3 };
    const val = r => k === 'status' ? order[r.status] : k === 'new' ? r.nw : r[k];
    rows.sort((a, b) => {
      const x = val(a), y = val(b);
      if (x == null && y == null) return a.name.localeCompare(b.name);
      if (x == null) return 1; if (y == null) return -1;
      return (typeof x === 'string' ? x.localeCompare(y) : x - y) * dir || a.name.localeCompare(b.name);
    });
    return rows;
  }

  function renderTable() {
    const rows = rowsFor();
    const tb = $('#tbl tbody');
    tb.innerHTML = rows.length ? rows.map(r => {
      const [cls, lab] = STATUS[r.status];
      return `<tr data-c="${esc(r.code)}" tabindex="0" class="${r.code === S.selected ? 'on' : ''}">
        <td>${esc(r.name)}</td><td class="n">${num(r.units)}</td>
        <td class="n"><span class="cell">${pct(r.share)}<span class="spark" aria-hidden="true"><i style="width:${(r.share || 0) * 100}%"></i></span></span></td>
        <td class="n">${r.unew < 1 ? '<span class="dim">none built</span>' : `${pct(r.nw)} <span class="dim">of ${num(r.unew)}</span>`}</td>
        <td class="n">${r.median == null ? '–' : r.median >= 1e9 ? 'over ' + metres(th()[1]) : metres(r.median)}</td>
        <td class="n crowd-col">${crowdShort(S.kind, r.crowd)}</td>
        <td><span class="tag ${cls}">${lab}</span></td></tr>`;
    }).join('') : `<tr><td colspan="7">No community matches. Clear the search or choose All.</td></tr>`;
    $$('tr[data-c]', tb).forEach(tr => {
      const go = () => { select(tr.dataset.c); focusArea(tr.dataset.c); $('#map').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' }); };
      tr.addEventListener('click', go);
      tr.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    });
    $$('#tbl th button').forEach(b => b.setAttribute('aria-sort', b.dataset.sort === S.sort[0] ? (S.sort[1] > 0 ? 'ascending' : 'descending') : 'none'));
    $('#tbl th [data-sort="share"]').textContent = 'Within ' + metres(th()[S.th]);
    const showC = !!(crowd(S.kind) && S.people);
    $$('#tbl .crowd-col').forEach(e => e.hidden = !showC);
    if (showC) $('#tbl th [data-sort="crowd"]').textContent = crowdUnitShort(S.kind) + ' within ' + metres(th()[S.th]);
  }
  function markRow() { $$('#tbl tbody tr').forEach(tr => tr.classList.toggle('on', tr.dataset.c === S.selected)); }
  function restyle() { if (areaLayer) areaLayer.eachLayer(l => l.setStyle(styleArea(l.feature.properties.code))); if (S.selected && layerByCode[S.selected]) layerByCode[S.selected].bringToFront(); }

  // ---------- sources and quality ----------
  function renderSources() {
    $('#source-list').innerHTML = S.sources.sources.map(s => `<div class="src">
      <div><h3>${s.url.startsWith('http') ? `<a href="${esc(s.url)}">${esc(s.title)}</a>` : esc(s.title)}</h3><div class="meta">${esc(s.publisher)}</div></div>
      <div class="meta">${s.rows != null ? num(s.rows) + ' rows read' : ''}${s.publisher_updated ? `, last updated by the publisher ${esc(s.publisher_updated)}` : ''}, read ${esc((s.fetched_at || '').slice(0, 10))}.
        ${s.query ? `Filter: <code>${esc(s.query)}</code>.` : ''} Licence: ${esc(s.licence)}.
        <ul>${(s.transformations || []).map(t => `<li>${esc(t)}</li>`).join('')}${(s.limitations || []).filter(Boolean).map(t => `<li>${esc(t)}</li>`).join('')}</ul></div></div>`).join('');
  }
  function renderQuality() {
    const q = S.quality, n = { pass: 0, warn: 0, fail: 0 };
    q.checks.forEach(c => n[c.status]++);
    $('#quality-sum').textContent = `${q.checks.length} checks ran on this build: ${n.pass} passed, ${n.warn} raised a warning, ${n.fail} failed. A failed check stops the build, so a broken feed never replaces the last good data.`;
    const label = { pass: 'Passed', warn: 'Warning', fail: 'Failed' };
    $('#qtbl tbody').innerHTML = q.checks.map(c => `<tr><td>${esc(c.source.split('.').slice(1).join(' '))}</td><td>${esc(c.check.replace(/_/g, ' '))}</td><td class="st-${c.status}">${label[c.status]}</td><td>${esc(c.detail)}</td></tr>`).join('');
  }

  function renderAll() {
    renderHero(); renderLegend(); restyle(); renderTable(); renderProfile(); renderCompare(); renderPoints(); writeHash();
    $$('#th0, #th1').forEach(b => b.setAttribute('aria-pressed', String(+b.dataset.th === S.th)));
  }

  // ---------- controls ----------
  $$('#th0, #th1').forEach(b => b.addEventListener('click', () => { S.th = +b.dataset.th; renderAll(); }));
  $$('#mode-seg button').forEach(b => b.addEventListener('click', () => { S.mode = b.dataset.m; renderAll(); }));
  $('#show-pts').addEventListener('change', e => { S.showPts = e.target.checked; renderPoints(); });
  $$('.filter button').forEach(b => b.addEventListener('click', () => { S.filter = b.dataset.f; $$('.filter button').forEach(x => x.setAttribute('aria-pressed', x === b)); renderTable(); }));
  $('#q-comm').addEventListener('input', e => { S.q = e.target.value; renderTable(); });
  $$('#tbl th button').forEach(b => b.addEventListener('click', () => {
    const k = b.dataset.sort; S.sort = [k, S.sort[0] === k ? -S.sort[1] : (k === 'name' || k === 'share' || k === 'new' || k === 'status' || k === 'crowd' ? 1 : -1)]; renderTable();
  }));
  dark.addEventListener('change', () => { if (S.data) { restyle(); renderLegend(); renderPoints(); } });
  boot();
})();
