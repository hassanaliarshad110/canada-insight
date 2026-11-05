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
              people: null, mode: 'near', sGroup: 'overall', sFilter: 'all', sq: '',
              view: 'dashboard', ward: 0, base: null, set: 'public', dash: null, popMethod: null, wcTopic: 'people', wcSort: null, wardsGeo: null };
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
    let [city, view, kind] = (p || '').split('/');
    if (view && !['dashboard', 'amenities', 'wards', 'about', 'ask'].includes(view)) { kind = view; view = 'amenities'; }   // old links
    const q = new URLSearchParams(qs || '');
    return { city, view: view || 'dashboard', kind, th: q.get('d') === '800' || q.get('d') === '1' ? 1 : 0, c: q.get('c'),
             p: q.get('p'), m: q.get('m'), w: +(q.get('w') || 0), set: q.get('set'), pm: q.get('pm') };
  }
  function writeHash() {
    if (!S.city) return;
    const q = new URLSearchParams();
    if (S.th) q.set('d', '1');
    if (S.selected) q.set('c', S.selected);
    if (S.people && S.data && S.data.crowding && S.people !== S.data.crowding.default) q.set('p', S.people);
    if (S.mode === 'crowding') q.set('m', 'crowding');
    if (S.ward) q.set('w', S.ward);
    if (S.set !== 'public') q.set('set', S.set);
    if (S.popMethod && S.dash && S.popMethod !== S.dash.default_method) q.set('pm', S.popMethod);
    const h = `#/${S.city.id}/${S.view}` + (S.view === 'amenities' ? '/' + S.base : '') + (q.toString() ? '?' + q : '');
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
    S.view = h.view; S.ward = h.w || 0; S.set = ['public', 'city', 'private'].includes(h.set) ? h.set : 'public'; S.popMethod = h.pm;
    await openCity(first.id, h.kind, h.c);
  }

  async function openCity(id, kind, code) {
    S.city = S.cities.find(c => c.id === id);
    $('#city').value = id;
    const base = `data/${id}/`;
    [S.data, S.areas, S.sources, S.quality] = await Promise.all(
      ['access.json', 'areas.geojson', 'sources.json', 'quality.json'].map(f => get(base + f)));
    [S.dash, S.wardsGeo] = await Promise.all([get(base + 'dashboard.json').catch(() => null), get(base + 'wards.geojson').catch(() => null)]);
    const bases = Object.keys(S.data.kinds).filter(k => !S.data.kinds[k].variant_of);
    S.base = bases.includes(kind) ? kind : bases[0];
    S.kind = effKey(S.base);
    if (S.dash && !S.dash.methods[S.popMethod]) S.popMethod = S.dash.default_method;
    renderWardPicker();
    S.selected = code && S.data.areas[code] ? code : null;
    S.compare = [];
    const cr = S.data.crowding;
    if (!cr || !cr.options[S.people]) S.people = cr ? cr.default : null;
    renderPeople();
    $$('.gy').forEach(e => e.textContent = S.data.growth_year);
    $('#csv').href = base + 'access_by_area.csv';
    $('#built').textContent = `Built ${new Date(S.data.built_at).toLocaleString('en-CA', { dateStyle: 'long', timeStyle: 'short' })} from the sources listed above. Version ${S.data.version}.`;
    renderKinds(); initMap(); renderAll(); renderSources(); renderQuality(); renderOsmStats();
    showView(S.view);
    if (S.selected) focusArea(S.selected);
  }

  // ---------- views, ward picker, amenity sets ----------
  function effKey(base) {
    const k = S.set === 'public' ? base : `${base}|${S.set}`;
    return S.data.kinds[k] ? k : base;
  }
  function baseOf(k) { return (S.data.kinds[k] || {}).variant_of || k; }
  function baseKinds() { return Object.entries(S.data.kinds).filter(([, v]) => !v.variant_of); }
  function showView(v) {
    S.view = v;
    $$('.view').forEach(e => e.hidden = e.dataset.view !== v);
    $$('.tabs a').forEach(a => a.setAttribute('aria-current', a.dataset.view === v ? 'page' : 'false'));
    if (v === 'amenities' && map) setTimeout(() => { map.invalidateSize(); fitScope(); }, 50);
    if (v === 'dashboard') renderDash();
    if (v === 'wards') renderWards();
    writeHash();
    window.scrollTo(0, 0);
  }
  function wardName(w) {
    const d = (S.data.wards || {})[w] || {};
    return `Ward ${w}` + (d.councillor ? ` (${d.councillor})` : '');
  }
  function renderWardPicker() {
    const sel = $('#ward');
    const ws = Object.keys(S.data.wards || {}).map(Number).sort((a, b) => a - b);
    sel.innerHTML = `<option value="0">All of ${esc(S.data.name)}</option>` + ws.map(w => `<option value="${w}">${esc(wardName(w))}</option>`).join('');
    if (!ws.includes(S.ward)) S.ward = 0;
    sel.value = String(S.ward);
    $('#scope-note').textContent = S.ward ? `Every figure below is for Ward ${S.ward}, set against ${S.data.name}.` : '';
  }
  function scopeName() { return S.ward ? `Ward ${S.ward}` : S.data.name; }
  function scopeAccess(k) { return S.ward ? ((S.data.wards[S.ward] || {}).access || {})[k] : S.data.city_access[k]; }
  function scopeKey() { return S.ward ? `ward:${S.ward}` : '_all'; }
  function inScope(code) { return !S.ward || (S.data.areas[code] || {}).ward === S.ward; }
  function renderOsmStats() {
    const o = S.data.osm, box = $('#osm-stats');
    if (!o || !o.stats) { box.textContent = 'Non-City amenities were not available for this build: City amenities only.'; $('#set-wrap').hidden = true; return; }
    const st = o.stats;
    box.textContent = `This build: ${st.playground.public} playgrounds and ${st.park.public} parks open to everyone added from OpenStreetMap, ` +
      `${st.playground.private} playgrounds and ${st.park.private} parks that are private (counted only with the filter), ` +
      `${st.playground.city + st.park.city} already in the City's lists and not counted again` + (o.reused ? `. OpenStreetMap could not be reached, so the copy read ${o.reused} was used.` : '.');
  }

  // ---------- hero ----------
  function renderKinds() {
    const box = $('#kinds');
    box.innerHTML = baseKinds().map(([k, v]) =>
      `<button type="button" data-k="${esc(k)}" aria-pressed="${k === S.base}">${esc(v.label)}</button>`).join('');
    $$('button', box).forEach(b => b.addEventListener('click', () => { S.base = b.dataset.k; S.kind = effKey(S.base); $$('button', box).forEach(x => x.setAttribute('aria-pressed', x === b)); renderAll(); }));
  }

  function th() { return S.data.kinds[S.kind].thresholds_m; }
  function baseLabel() { return S.data.kinds[S.base].label; }

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
    return (v >= 10 ? Math.round(v) : v.toFixed(v >= 1 ? 1 : 2)) + ' ' + (c.unit || '').replace(/ within reach$/, '');
  }
  function crowdShort(kind, v) { return v == null ? '–' : (v >= 10 ? Math.round(v) : v.toFixed(v >= 1 ? 1 : 2)); }
  function crowdUnitShort(kind) { const c = crowd(kind); return c ? (c.short || c.unit) : ''; }
  // ---------- scores ----------
  const BAND_LABEL = { well_below: 'Well below Calgary', below: 'Below Calgary', around: 'Around Calgary', above: 'Above Calgary' };
  const CONS = { consistent_gap: ['tag-cgap', 'Consistent gap'], depends: ['tag-dep', 'Depends on assumptions'], none: ['tag-none', 'No gap'] };
  function sc2(v) { return v == null ? '–' : v.toFixed(2); }
  function scoreCell(s) {
    if (!s || s.score == null) return '<span class="dim">–</span>';
    const max = 2.5, x = v => Math.min(Math.max(v, 0), max) / max * 84;
    return `<span class="sc ${s.band || ''}" title="${BAND_LABEL[s.band] || ''}; range ${sc2(s.low)} to ${sc2(s.high)} across ${s.scenarios} ways">
      <b>${sc2(s.score)}</b><span class="rng" aria-hidden="true"><i style="left:${x(s.low)}px;width:${Math.max(x(s.high) - x(s.low), 2)}px"></i><span class="one" style="left:${x(1)}px"></span><span class="mark" style="left:${x(s.score) - 1}px"></span></span>
      <small>${sc2(s.low)} to ${sc2(s.high)}</small></span>`;
  }
  function renderScores() {
    const sec = $('#scores'), sd = S.data.scores;
    if (!sd) { sec.hidden = true; return; }
    sec.hidden = false;
    $$('.tabs a').forEach(a => a.addEventListener('click', e => { e.preventDefault(); showView(a.dataset.view); }));
  window.addEventListener('hashchange', () => {
    if (!S.data) return;
    const h = readHash();
    if (h.w !== S.ward) { S.ward = h.w; renderWardPicker(); renderAll(); }
    if (h.view !== S.view) showView(h.view);
  });
  $('#ward').addEventListener('change', e => {
    S.ward = +e.target.value; renderWardPicker();
    restyle(); if (wardLayer) wardLayer.eachLayer(l => l.setStyle(wardStyle(l.feature.properties.ward)));
    if (S.view === 'amenities') fitScope();
    renderAll(); if (S.view === 'dashboard') renderDash(); if (S.view === 'wards') renderWards();
  });
  $('#set').addEventListener('change', e => { S.set = e.target.value; S.kind = effKey(S.base); renderAll(); });
  $('#pop-method').addEventListener('change', e => { S.popMethod = e.target.value; renderDash(); renderWards(); writeHash(); });
  $$('#score-col button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.g === S.sGroup)));
    $$('#score-filter button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.f === S.sFilter)));
    const pick = r => S.sGroup === 'overall' ? r.overall : r.groups[S.sGroup];
    const q = S.sq.trim().toLowerCase();
    let rows = Object.entries(sd.areas).filter(([code]) => !code.startsWith('ward:') && inScope(code)).map(([code, r]) => ({ code, name: (S.data.areas[code] || {}).name || code, units: (S.data.areas[code] || {}).units, r, s: pick(r) }));
    const counts = { consistent_gap: 0, depends: 0 };
    rows.forEach(x => { if (x.s && counts[x.s.consistency] != null) counts[x.s.consistency]++; });
    if (q) rows = rows.filter(x => x.name.toLowerCase().includes(q));
    if (S.sFilter !== 'all') rows = rows.filter(x => x.s && x.s.consistency === S.sFilter);
    rows.sort((a, b) => ((a.s && a.s.score != null) ? a.s.score : 9) - ((b.s && b.s.score != null) ? b.s.score : 9) || a.name.localeCompare(b.name));
    const gname = { overall: 'all amenities', local: 'local amenities', district: 'district facilities' }[S.sGroup];
    const wr = S.ward && sd.areas['ward:' + S.ward];
    const wtxt = wr ? `Ward ${S.ward} as a whole: ${sc2((S.sGroup === 'overall' ? wr.overall : wr.groups[S.sGroup]).score)} (${sc2((S.sGroup === 'overall' ? wr.overall : wr.groups[S.sGroup]).low)} to ${sc2((S.sGroup === 'overall' ? wr.overall : wr.groups[S.sGroup]).high)}). ` : '';
    $('#score-count').textContent = `${wtxt}On ${gname}: ${counts.consistent_gap} communities have a consistent gap, ${counts.depends} more depend on the assumptions, out of ${rows.length} scored${S.ward ? ' in Ward ' + S.ward : ''}. Sorted lowest first. Residents and children: ${S.data.crowding.options[S.people] ? S.data.crowding.options[S.people].label : ''} for the score shown; the range covers both.`;
    $('#stbl tbody').innerHTML = rows.length ? rows.map(x => {
      const c = x.s && CONS[x.s.consistency];
      return `<tr data-c="${esc(x.code)}" tabindex="0" class="${x.code === S.selected ? 'on' : ''}"><td>${esc(x.name)}${x.s && x.s.scenarios < x.s.scenarios_possible ? ' <span class="dim" title="No 2021 Census count, so fewer ways could be worked out">*</span>' : ''}</td>
        <td class="n">${num(x.units)}</td><td class="n">${scoreCell(x.r.groups.local)}</td><td class="n">${scoreCell(x.r.groups.district)}</td><td class="n">${scoreCell(x.r.overall)}</td>
        <td>${c ? `<span class="tag ${c[0]}">${c[1]}</span>` : '<span class="dim">–</span>'}</td></tr>`;
    }).join('') : '<tr><td colspan="6">No community matches. Clear the search or choose All.</td></tr>';
    $$('#stbl tr[data-c]').forEach(tr => {
      const go = () => { select(tr.dataset.c); focusArea(tr.dataset.c); $('#map').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block: 'center' }); };
      tr.addEventListener('click', go);
      tr.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } });
    });
  }

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
    const k = S.data.kinds[S.kind], c = scopeAccess(S.kind), [p, s] = th();
    const name = scopeName();
    const cityC = S.data.city_access[S.kind];
    $('#th0').textContent = metres(p); $('#th1').textContent = metres(s);
    $('#headline').innerHTML = `<strong>${pct(c.share_primary)}</strong> of ${esc(name)}'s homes are within ${metres(p)} of a ${esc(baseLabel().toLowerCase())}, and <strong>${pct(c.share_secondary)}</strong> within ${metres(s)}.` +
      (S.ward ? ` <span class="vs">${esc(S.data.name)}: ${pct(cityC.share_primary)} and ${pct(cityC.share_secondary)}.</span>` : '');
    const bars = [['Homes built before ' + S.data.growth_year, c.share_old_primary, ''], ['Homes built since ' + S.data.growth_year, c.share_new_primary, 'new']];
    $('#pace').innerHTML = `<p class="fine" style="margin:0 0 4px">Within ${metres(p)}:</p>` + bars.map(([l, v, cls]) =>
      `<div class="bar ${cls}"><span class="lbl">${esc(l)}</span><span class="track" role="img" aria-label="${esc(l)}: ${pct(v)}"><span class="fill" style="width:${(v || 0) * 100}%"></span></span><span class="v">${pct(v)}</span></div>`).join('');
    const gap = c.share_new_primary != null && c.share_old_primary != null ? Math.round((c.share_new_primary - c.share_old_primary) * 100) : null;
    const pace = gap == null ? '' : gap <= -5 ? `New homes are less well served by ${-gap} points. ` : gap >= 5 ? `New homes are better served by ${gap} points. ` : 'New and older homes are about equally served. ';
    const sens = S.data.sensitivity[S.kind];
    const cv = crowdVal(S.kind, scopeKey(), 0);
    const crowdNote = cv == null ? '' : ` Within ${metres(p)}, ${esc(name)} has ${crowdFmt(S.kind, cv)} who can reach them <span class="kind kind-estimate">Estimate</span> (${esc(S.data.crowding.options[S.people].label)}).`;
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
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { maxZoom: 19,
        attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors' }).addTo(map);
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
    if (S.wardsGeo) {
      if (wardLayer) wardLayer.remove();
      wardLayer = L.geoJSON(S.wardsGeo, { interactive: false, style: f => wardStyle(f.properties.ward) }).addTo(map);
    }
    fitScope();
  }
  let wardLayer;
  function wardStyle(w) {
    const on = S.ward && +w === S.ward;
    return { fill: false, color: dark.matches ? '#E5ECE9' : '#1C2A28', weight: on ? 3.5 : 1.2, opacity: S.ward && !on ? 0.35 : 0.8, dashArray: on ? null : '5 4' };
  }
  function fitScope() {
    if (!map) return;
    if (S.ward && wardLayer) {
      const l = wardLayer.getLayers().find(x => +x.feature.properties.ward === S.ward);
      if (l) { map.fitBounds(l.getBounds(), { padding: [12, 12] }); return; }
    }
    if (areaLayer) map.fitBounds(areaLayer.getBounds(), { padding: [10, 10] });
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
    void 0;
    const sel = code === S.selected, chk = !cm && st && st.status === 'gap_check' && !S.th;
    if (cm) {
      const i = v == null ? -1 : RBINS.findIndex(b => v < b);
      const fill = v == null ? getComputedStyle(document.documentElement).getPropertyValue('--nodata').trim() : colors()[i === -1 ? 5 : i];
      return { fillColor: fill, fillOpacity: !inScope(code) ? 0.15 : v == null ? 0.35 : 0.82, color: sel ? (dark.matches ? '#fff' : '#1C2A28') : (dark.matches ? '#121A19' : '#ffffff'), weight: sel ? 3 : 0.8, dashArray: null };
    }
    const dim = !inScope(code);
    return { fillColor: colorFor(v), fillOpacity: dim ? 0.15 : v == null ? 0.35 : 0.82, color: sel ? (dark.matches ? '#fff' : '#1C2A28') : chk ? '#A86A0C' : (dark.matches ? '#121A19' : '#ffffff'),
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
    $$('#score-col button').forEach(b => b.addEventListener('click', () => { S.sGroup = b.dataset.g; renderScores(); }));
  $$('#score-filter button').forEach(b => b.addEventListener('click', () => { S.sFilter = b.dataset.f; renderScores(); }));
  $('#q-score').addEventListener('input', e => { S.sq = e.target.value; renderScores(); });
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
    const gj = ptsCache[key] || (ptsCache[key] = await get(`data/${S.city.id}/amenities/${S.kind.replace('|', '-')}.geojson`));
    const color = dark.matches ? '#F1F4F2' : '#1C2A28';
    ptsLayer = L.geoJSON(gj, {
      pointToLayer: (f, ll) => L.circleMarker(ll, { radius: 3.5, color: f.properties.source === 'osm' ? '#A86A0C' : color, weight: 1,
        fillColor: f.properties.source === 'osm' ? (f.properties.private ? '#ffffff' : '#A86A0C') : color, fillOpacity: 0.9, interactive: false }),
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
    const scs = S.data.scores && S.data.scores.areas[code];
    const block = scs ? `<div class="p-scores">${[['local', 'Local amenities', scs.groups.local], ['district', 'District facilities', scs.groups.district], ['overall', 'All amenities', scs.overall]].map(([g, l, s]) =>
      `<div><span class="l">${l}</span><span class="v">${sc2(s && s.score)}</span><br><span class="r">${s && s.low != null ? sc2(s.low) + ' to ' + sc2(s.high) : ''}</span>${s && CONS[s.consistency] ? `<br><span class="tag ${CONS[s.consistency][0]}">${CONS[s.consistency][1]}</span>` : ''}</div>`).join('')}</div>` : '';
    const rows = baseKinds().map(([bk, bkd]) => {
      const k = effKey(bk), kd = S.data.kinds[k];
      const st = a.access[k], [p, s] = kd.thresholds_m, [cls, lab] = STATUS[st.status];
      const cityv = S.data.city_access[k].share_primary;
      return `<div class="p-row ${k === S.kind ? 'sel' : ''}">
        <div class="t"><span>${esc(bkd.label)}</span><span class="tag ${cls}">${lab}</span></div>
        <div class="mini">
          <span class="k">Within ${metres(p)}</span><span>${pct(st.share_primary)} <span class="k">(city ${pct(cityv)})</span></span>
          <span class="k">Within ${metres(s)}</span><span>${pct(st.share_secondary)}</span>
          <span class="k">Built since ${S.data.growth_year}, within ${metres(p)}</span><span>${st.share_new_primary == null ? 'none built' : pct(st.share_new_primary)}</span>
          <span class="k">Median distance</span><span>${st.median_m == null ? (st.median_beyond_cap ? 'over ' + metres(s) : '–') : metres(st.median_m)}</span>
          ${crowd(k) && S.people ? `<span class="k">${crowdUnitShort(k)} within ${metres(p)} <span class="kind kind-estimate">Estimate</span></span><span>${crowdShort(k, crowdVal(k, code, 0))} <span class="k">(city ${crowdShort(k, crowdVal(k, '_all', 0))})</span></span>` : ''}
          ${scs && scs.amenities[bk] && scs.amenities[bk].score != null ? `<span class="k">Score against Calgary</span><span>${sc2(scs.amenities[bk].score)} <span class="k">(${sc2(scs.amenities[bk].low)} to ${sc2(scs.amenities[bk].high)})</span>${scs.amenities[bk].consistency === 'consistent_gap' ? ' <span class="tag tag-cgap">Consistent gap</span>' : ''}</span>` : ''}
        </div></div>`;
    }).join('');
    const inCmp = S.compare.includes(code);
    box.innerHTML = `<h3>${esc(a.name)}</h3>
      <p class="sub">${num(a.units)} homes on the property roll, ${Math.round(newShare * 100)}% built since ${S.data.growth_year} <span class="kind kind-official">Official</span>${a.homes_reference != null ? `<br><span title="${esc((S.data.homes.reference || {}).note || '')}">Calgary Data Desk counts ${num(a.homes_reference)} lived in (from a year after they're built)</span>` : ''}${a.ward ? '<br>' + esc(wardName(a.ward)) : ''}</p>
      ${block}${rows}
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
    const kinds = baseKinds().map(([bk]) => [effKey(bk), S.data.kinds[effKey(bk)]]);
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
    if (S.ward) rows = rows.filter(r => inScope(r.code));
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
        <td class="n">${r.unew < 1 ? '<span class="dim">none built</span>' : `${num(r.unew)} <span class="dim">homes, ${pct(r.nw)} within ${metres(th()[S.th])}</span>`}</td>
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


  // ---------- dashboard (figures from the linked Data Desk build) ----------
  const F = {
    num: v => v == null ? '–' : Math.round(v).toLocaleString('en-CA'),
    dec1: v => v == null ? '–' : v.toLocaleString('en-CA', { minimumFractionDigits: 1, maximumFractionDigits: 1 }),
    dec2: v => v == null ? '–' : v.toFixed(2),
    pct: v => v == null ? '–' : v.toLocaleString('en-CA', { maximumFractionDigits: 1 }) + '%',
    spct: v => v == null ? '–' : (v > 0 ? '+' : '') + v.toLocaleString('en-CA', { maximumFractionDigits: 1 }) + '%',
    share: v => v == null ? '–' : Math.round(v * 100) + '%',
    money: v => v == null ? '–' : '$' + (v >= 1e9 ? (v / 1e9).toFixed(2) + ' billion' : (v / 1e6).toFixed(1) + ' million'),
  };
  const CONTACT_NOTE = 'Includes old "311 Contact Us" records: about 24,900 city-wide, none made in the last 12 months.';
  const GROUPS = [
    { id: 'people', title: 'People and homes', m: [
      ['residents', 'Residents today', 'num', 'estimate'], ['growth_pct', 'Growth since the 2021 Census', 'spct', 'estimate'],
      ['homes_now', 'Homes lived in', 'num'], ['people_per_home', 'People per home', 'dec2', 'estimate'],
      ['census2021', 'Residents at the 2021 Census', 'num', 'official']] },
    { id: '311', title: '311 service requests', period: true, m: [
      ['requests_per_1000', '311 requests per 1,000 residents a year', 'dec1'], ['requests_change_pct', 'Change on the year before', 'spct'],
      ['infra_per_1000', 'Roads, water and parks reports per 1,000 a year', 'dec1'],
      ['open', 'Requests open now', 'num', null, CONTACT_NOTE], ['open_over_90_days', 'Open more than 90 days', 'num', null, CONTACT_NOTE],
      ['closed_7_days_pct', 'Closed within 7 days', 'pct', null, 'Counts only requests already closed, so recent months look faster.'],
      ['app_share_pct', 'Made through the 311 app', 'pct']] },
    { id: 'safety', title: 'Safety and traffic', crime: true, m: [
      ['crime_per_1000', 'Crimes per 1,000 residents a year', 'dec1'], ['crime_change_pct', 'Change in crime on the year before', 'spct'],
      ['violent_change_pct', 'Change in violent crime', 'spct'], ['traffic_per_1000', 'Traffic incidents per 1,000 residents a year', 'dec1'],
      ['traffic_change_pct', 'Change in traffic incidents', 'spct']] },
    { id: 'families', title: 'Children, child care and schools', m: [
      ['children_0_14', 'Children aged 0 to 14', 'num', 'estimate'], ['child_care_per_100_kids', 'Licensed child care spaces per 100 children aged 0 to 14', 'dec1'],
      ['daycare_per_100_0_4', 'Daycare spaces per 100 children aged 0 to 4', 'dec1'], ['schools', 'Schools', 'num'], ['students', 'Students enrolled', 'num']] },
    { id: 'development', title: 'Development and new homes', period: true, m: [
      ['new_homes12', 'Homes in building permits applied for', 'num'], ['new_homes_change_pct', 'Change on the year before', 'spct'],
      ['issued_homes12', 'Homes in building permits issued', 'num'], ['dev_permits12', 'Development permit applications', 'num']] },
  ];
  function dm() { return S.dash && S.dash.methods[S.popMethod]; }
  function dashRow(w) { const m = dm(); if (!m) return null; return w ? m.wards.find(r => +r.ward === +w) : m.city; }
  function kindChip(k) { return k === 'estimate' ? ' <span class="kind kind-estimate">Estimate</span>' : k === 'official' ? ' <span class="kind kind-official">Official</span>' : ''; }
  function card(label, value, cityValue, kind, note) {
    return `<div class="card"><div class="l">${esc(label)}${kindChip(kind)}</div><div class="v">${value}</div>` +
      (S.ward && cityValue != null ? `<div class="c">${esc(S.data.name)}: <b>${cityValue}</b></div>` : '') +
      (note ? `<div class="note">${esc(note)}</div>` : '') + '</div>';
  }
  function amenityCards() {
    const key = scopeKey(), sc = S.data.scores && S.data.scores.areas[key];
    const out = [];
    for (const [bk, kd] of baseKinds()) {
      const a = scopeAccess(bk), c = S.data.city_access[bk];
      out.push(card(`Homes within ${metres(kd.thresholds_m[0])} of a ${kd.label.toLowerCase()}`, F.share(a && a.share_primary), F.share(c.share_primary)));
    }
    if (sc) for (const [g, l] of [['local', 'Local amenities score'], ['district', 'District facilities score'], ['overall', 'All amenities score']]) {
      const v = g === 'overall' ? sc.overall : sc.groups[g];
      out.push(card(`${l} (1.00 = ${S.data.name})`, `${sc2(v.score)} <small>${sc2(v.low)} to ${sc2(v.high)}</small>`, '1.00', 'estimate'));
    }
    return out.join('');
  }
  function renderDash() {
    if (!S.data) return;
    const sel = $('#pop-method');
    if (S.dash) {
      sel.innerHTML = Object.entries(S.dash.methods).map(([k, m]) => `<option value="${esc(k)}">${esc(m.label)}</option>`).join('');
      sel.value = S.popMethod;
    }
    $('#dash-h').textContent = `${scopeName()} at a glance`;
    const m = dm(), row = dashRow(S.ward), city = dashRow(0);
    const groups = [];
    if (m && row) {
      for (const g of GROUPS) {
        const sub = g.crime ? (m.crime_period || '') : g.period ? (m.period || '') : '';
        groups.push(`<section class="dgroup"><h2>${esc(g.title)}${sub ? ` <small>${esc(sub)}</small>` : ''}</h2><div class="cards">` +
          g.m.map(([k, l, f, kind, note]) => card(l, F[f](row[k]), city ? F[f](city[k]) : null, kind, note)).join('') + '</div></section>');
      }
    }
    groups.push(`<section class="dgroup findings-box" id="dash-findings"></section>`);
    groups.push(`<section class="dgroup"><h2>Amenities within reach <small>Canada Insight, ${esc(new Date(S.data.built_at).toLocaleDateString('en-CA', { dateStyle: 'medium' }))}</small></h2><div class="cards">${amenityCards()}</div>
      <p class="fine"><a href="#" data-goto="amenities">Explore amenities community by community</a></p></section>`);
    const tax = S.dash && S.dash.tax && S.dash.tax.by_ward;
    if (tax) {
      const sum = k => Object.values(tax).reduce((a, r) => a + (r[k] || 0), 0);
      const t = S.ward ? tax[S.ward] : null;
      const val = k => t ? t[k] : sum(k);
      groups.push(`<section class="dgroup"><h2>Property tax <small>estimated from the assessment roll</small></h2><div class="cards">` +
        card('Property tax raised, total', F.money(val('total')), S.ward ? F.money(sum('total')) : null, 'estimate') +
        card('Municipal share', F.money(val('municipal')), S.ward ? F.money(sum('municipal')) : null, 'estimate') +
        card('Provincial education share', F.money(val('education')), S.ward ? F.money(sum('education')) : null, 'estimate') +
        card('From homes', F.money(val('residential')), S.ward ? F.money(sum('residential')) : null, 'estimate') + '</div></section>');
    }
    $('#dash-groups').innerHTML = groups.join('');
    renderFindings('#dash-findings');
    $$('#dash-groups [data-goto]').forEach(a => a.addEventListener('click', e => { e.preventDefault(); showView(a.dataset.goto); }));
    $('#dash-sub').textContent = m ? `Residents counted with: ${m.label}. ${m.period ? 'Twelve months: ' + m.period + '.' : ''}` : 'City figures are not available in this build.';
    $('#dash-source').innerHTML = S.dash ? `311, safety, families, development and tax figures: ${esc(S.dash.source.title)} (<a href="${esc(S.dash.source.url)}">${esc(S.dash.source.url.replace(/^https:\/\//, ''))}</a>), read ${esc((S.dash.read_at || '').slice(0, 10))}${S.dash.stale ? '. That build could not be read today, so the last copy is shown.' : ''}. They match that site exactly. Amenity figures are worked out by Canada Insight.` : '';
  }

  // ---------- ward comparison ----------
  function wardTopics() {
    const t = GROUPS.map(g => ({ id: g.id, title: g.title, cols: g.m.map(([k, l, f]) => ({ k, l, f, get: w => (dashRow(w) || {})[k] })) }));
    const am = baseKinds().map(([bk, kd]) => ({ k: bk, l: `Within ${metres(kd.thresholds_m[0])}: ${kd.label.toLowerCase()}`, f: 'share',
      get: w => { const a = w ? ((S.data.wards[w] || {}).access || {})[bk] : S.data.city_access[bk]; return a && a.share_primary; } }));
    const scg = [['local', 'Local score'], ['district', 'District score'], ['overall', 'All amenities score']].map(([g, l]) => ({ k: 's_' + g, l, f: 'dec2',
      get: w => { if (!w) return 1; const r = S.data.scores && S.data.scores.areas['ward:' + w]; return r ? (g === 'overall' ? r.overall : r.groups[g]).score : null; } }));
    t.push({ id: 'amenities', title: 'Amenities', cols: [...am, ...scg] });
    return t;
  }
  function renderWards() {
    if (!S.data || !S.data.wards) return;
    const topics = wardTopics();
    if (!topics.find(t => t.id === S.wcTopic)) S.wcTopic = topics[0].id;
    $('#wc-topics').innerHTML = topics.map(t => `<button type="button" data-t="${t.id}" aria-pressed="${t.id === S.wcTopic}">${esc(t.title)}</button>`).join('');
    $$('#wc-topics button').forEach(b => b.addEventListener('click', () => { S.wcTopic = b.dataset.t; S.wcSort = null; renderWards(); }));
    const t = topics.find(x => x.id === S.wcTopic);
    const ws = Object.keys(S.data.wards).map(Number).sort((a, b) => a - b);
    let rows = ws.map(w => ({ w, vals: t.cols.map(c => c.get(w)) }));
    if (S.wcSort) { const [i, dir] = S.wcSort; rows.sort((a, b) => ((a.vals[i] ?? -1e18) - (b.vals[i] ?? -1e18)) * dir); }
    const maxes = t.cols.map((c, i) => Math.max(...rows.map(r => Math.abs(r.vals[i] || 0))) || 1);
    $('#wctbl thead').innerHTML = `<tr><th scope="col">Ward</th>${t.cols.map((c, i) => `<th scope="col"><button data-i="${i}">${esc(c.l)}</button></th>`).join('')}</tr>`;
    $('#wctbl tbody').innerHTML = rows.map(r => `<tr class="${r.w === S.ward ? 'on' : ''}"><td>${esc(wardName(r.w))}</td>${r.vals.map((v, i) =>
      `<td><span class="barcell">${F[t.cols[i].f](v)}<i style="width:${Math.round(Math.abs(v || 0) / maxes[i] * 48)}px"></i></span></td>`).join('')}</tr>`).join('');
    $('#wctbl tfoot').innerHTML = `<tr><td>${esc(S.data.name)}</td>${t.cols.map(c => `<td>${F[c.f](c.get(0))}</td>`).join('')}</tr>`;
    $$('#wctbl th button').forEach(b => b.addEventListener('click', () => { const i = +b.dataset.i; S.wcSort = [i, S.wcSort && S.wcSort[0] === i ? -S.wcSort[1] : -1]; renderWards(); }));
    const m = dm();
    $('#wc-note').textContent = t.id === 'amenities' ? 'Amenity figures: Canada Insight. Homes are placed in wards by their exact location.'
      : `${m ? m.note || '' : ''} Source: ${S.dash ? S.dash.source.title : ''}, the same figures as that site.`;
  }


  // ---------- key findings, worked out from the data for whatever is selected (city or ward) ----------
  function pctPts(a, b) { return Math.round((a - b) * 100); }
  function findings() {
    const out = [], name = scopeName(), city = S.data.name, key = scopeKey();
    const kinds = Object.fromEntries(baseKinds().map(([bk]) => [bk, effKey(bk)]));
    const lab = bk => S.data.kinds[bk].label.toLowerCase();
    const plural = bk => S.data.kinds[bk].plural || lab(bk) + 's';
    const local = baseKinds().filter(([, v]) => v.group === 'local').map(([k]) => k);
    const district = baseKinds().filter(([, v]) => v.group === 'district').map(([k]) => k);
    // 1. nearness of local amenities
    const near = local.map(bk => ({ bk, a: scopeAccess(kinds[bk]), c: S.data.city_access[kinds[bk]] })).filter(x => x.a && x.c);
    if (near.length) {
      const parts = near.map(x => `${pct(x.a.share_primary)} of homes are within ${metres(S.data.kinds[x.bk].thresholds_m[0])} of ${an(lab(x.bk))}` + (S.ward ? ` (${city}: ${pct(x.c.share_primary)})` : ''));
      out.push({ kind: 'calculated', text: `In ${name}, ${parts.join('; ')}.` });
    }
    // 2. crowding: near, but shared by how many people
    for (const bk of local) {
      const k = kinds[bk], c = crowd(k);
      if (!c || !S.people) continue;
      const d = String(S.data.kinds[k].thresholds_m[0]);
      const by = c.by_option[S.people] && c.by_option[S.people][d];
      if (!by || by[key] == null || !by._all) continue;
      const ratio = by[key] / by._all;
      let txt = `Within ${metres(+d)}, ${name} has ${crowdFmt(k, by[key])} who can reach them` + (S.ward ? `, ${ratio.toFixed(2)} times ${city}'s level (${crowdShort(k, by._all)})` : '') + '.';
      if (S.ward) {
        const ws = Object.keys(S.data.wards || {}).map(w => [+w, by['ward:' + w]]).filter(x => x[1] != null).sort((a, b) => a[1] - b[1]);
        const r = ws.findIndex(x => x[0] === S.ward) + 1;
        if (r) txt += ` That is ${r === 1 ? 'the lowest' : r === ws.length ? 'the highest' : ordinal(r) + ' lowest'} of the ${ws.length} wards.`;
        const a = scopeAccess(k), cA = S.data.city_access[k];
        if (a && a.share_primary >= cA.share_primary - 0.02 && ratio < 0.8) txt += ` So ${plural(bk)} are near, but shared by more ${c.people} than in most of ${city}.`;
      }
      out.push({ kind: 'estimate', text: txt });
    }
    // 3. communities in the lowest quarter for playgrounds per child, within the scope
    const pk = kinds.playground, pc = pk && crowd(pk);
    if (pc && S.people) {
      const by = pc.by_option[S.people][String(S.data.kinds[pk].thresholds_m[0])] || {};
      const all = Object.entries(by).filter(([c, v]) => !c.startsWith('_') && !c.startsWith('ward:') && v != null && S.data.areas[c] && S.data.areas[c].access[pk].status !== 'too_few_homes').sort((a, b) => a[1] - b[1]);
      const q = Math.ceil(all.length / 4), low = new Set(all.slice(0, q).map(x => x[0]));
      const mine = all.filter(([c]) => inScope(c));
      const lowMine = mine.filter(([c]) => low.has(c));
      if (S.ward && mine.length) out.push({ kind: 'estimate', text: `${lowMine.length} of ${name}'s ${mine.length} communities are in ${city}'s lowest quarter for playgrounds per child within reach${lowMine.length ? ': ' + lowMine.map(([c]) => S.data.areas[c].name).join(', ') : ''}.` });
    }
    // 4. new homes against older homes, where the gap is 10 points or more
    const gaps = [];
    for (const [bk] of baseKinds()) {
      const a = scopeAccess(kinds[bk]);
      if (!a || a.share_new_primary == null || a.share_old_primary == null || a.units_new < 50) continue;
      const g = pctPts(a.share_new_primary, a.share_old_primary);
      if (Math.abs(g) >= 10) gaps.push(`${lab(bk)} ${pct(a.share_new_primary)} against ${pct(a.share_old_primary)}`);
    }
    if (gaps.length) out.push({ kind: 'calculated', text: `Homes built since ${S.data.growth_year} compared with older homes in ${name} (share within walking distance): ${gaps.join('; ')}.` });
    // 5. district facilities for new homes
    const dist = district.map(bk => [bk, scopeAccess(kinds[bk])]).filter(([, a]) => a && a.share_new_primary != null && a.units_new >= 50);
    if (dist.length) out.push({ kind: 'calculated', text: `For homes built since ${S.data.growth_year} in ${name}: ` + dist.map(([bk, a]) => `${pct(a.share_new_primary)} are within ${metres(S.data.kinds[bk].thresholds_m[0])} of a ${lab(bk)}`).join('; ') + '. New communities on the city\'s edge are farther from facilities that serve several communities, some of which are planned for later phases.' });
    // 6. parks near, few playgrounds (communities in scope)
    if (kinds.park && kinds.playground) {
      const pp = Object.entries(S.data.areas).filter(([c, a]) => inScope(c) && a.access[kinds.park].status !== 'too_few_homes'
        && a.access[kinds.park].share_primary >= 0.9 && a.access[kinds.playground].share_primary < 0.5).map(([, a]) => a.name);
      if (pp.length) out.push({ kind: 'calculated', text: `Parks within easy reach but few playgrounds (90% or more of homes near a park, under half near a playground): ${pp.slice(0, 12).join(', ')}${pp.length > 12 ? ` and ${pp.length - 12} more` : ''}.` });
    }
    // 7. cautions
    const cc = kinds.community_centre && scopeAccess(kinds.community_centre);
    if (cc && cc.share_primary < 0.2) out.push({ kind: 'caution', text: `Community centres read low in ${name} (${pct(cc.share_primary)} of homes within ${metres(S.data.kinds[kinds.community_centre].thresholds_m[0])}). The City's list may not include every community association hall: check before quoting this figure.` });
    return out;
  }
  function an(word) { return /^[aeiou]/i.test(word) ? 'an ' + word : 'a ' + word; }
  function ordinal(n) { const s = ['th', 'st', 'nd', 'rd'], v = n % 100; return n + (s[(v - 20) % 10] || s[v] || s[0]); }
  function renderFindings(target) {
    const f = findings();
    const chip = k => k === 'estimate' ? '<span class="kind kind-estimate">Estimate</span>' : k === 'caution' ? '<span class="kind kind-caution">Check</span>' : '<span class="kind kind-calculated">Calculated</span>';
    $(target).innerHTML = f.length ? `<h2>What the data shows for ${esc(scopeName())}</h2><ul class="findings">${f.map(x => `<li>${esc(x.text)} ${chip(x.kind)}</li>`).join('')}</ul>
      <p class="fine">Worked out from the published figures each morning, the same way for every ward. Facts, not recommendations. Residents and children: ${esc(S.data.crowding && S.data.crowding.options[S.people] ? S.data.crowding.options[S.people].label : '')}; amenities: ${esc({ public: "City's plus non-City ones open to everyone", city: "City's only", private: 'including private ones' }[S.set])}.</p>` : '';
  }

  function renderAll() {
    $('#set-wrap').hidden = !S.data.kinds[S.base + '|city'];
    $('#set').value = S.set;
    renderHero(); renderLegend(); restyle(); renderTable(); renderProfile(); renderCompare(); renderPoints(); renderScores();
    renderFindings('#findings'); writeHash();
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

  // ---------- research assistant ----------
  const A = { cfg: null, mode: 'quick', msgs: [], busy: false };
  async function initAsk() {
    try { A.cfg = await get('genie.json'); } catch { A.cfg = null; }
    $('#ask-code-wrap').hidden = !(A.cfg && A.cfg.needs_code);
    try { $('#ask-code').value = sessionStorage.getItem('ci-code') || ''; } catch { /* storage unavailable */ }
    if (!A.cfg || !A.cfg.url) {
      $('#ask-status').textContent = 'The assistant is being set up and will be available here shortly.';
      $('#ask-send').disabled = true;
    }
  }
  function md(text) {
    const html = window.marked ? marked.parse(text || '') : esc(text);
    return window.DOMPurify ? DOMPurify.sanitize(html) : esc(text);
  }
  function renderThread() {
    $('#thread').innerHTML = A.msgs.map((m, i) => {
      if (m.role === 'user') return `<div class="msg user">${esc(m.content)}</div>`;
      if (m.error) return `<div class="msg ai err">${esc(m.error)}</div>`;
      const steps = (m.steps || []).map(s => `<li>${esc(s.tool)}: <code>${esc(JSON.stringify(s.input))}</code></li>`).join('');
      return `<div class="msg ai">${md(m.content)}<div class="meta"><span class="kind kind-ai">AI-generated</span>
        <span>${esc(m.model || '')}</span>${m.report ? `<a href="#" data-dl="${i}">Download the report (Markdown)</a>` : ''}</div>
        ${steps ? `<details><summary>What it looked up (${m.steps.length})</summary><ul>${steps}</ul></details>` : ''}</div>`;
    }).join('') + (A.busy ? '<div class="msg ai"><span class="fine">Looking it up in the data…</span></div>' : '');
    $$('#thread [data-dl]').forEach(x => x.addEventListener('click', e => {
      e.preventDefault();
      const m = A.msgs[+x.dataset.dl];
      const blob = new Blob([m.content], { type: 'text/markdown' });
      const u = URL.createObjectURL(blob), a = document.createElement('a');
      a.href = u; a.download = 'canada-insight-report.md'; a.click(); setTimeout(() => URL.revokeObjectURL(u), 1000);
    }));
  }
  async function ask(q) {
    if (!A.cfg || !A.cfg.url || A.busy || !q.trim()) return;
    A.msgs.push({ role: 'user', content: q.trim() });
    A.busy = true; $('#ask-send').disabled = true; renderThread();
    const code = $('#ask-code').value.trim();
    try { if (code) sessionStorage.setItem('ci-code', code); } catch { /* storage unavailable */ }
    try {
      const history = A.msgs.filter(m => !m.error).map(m => ({ role: m.role === 'user' ? 'user' : 'assistant', content: m.content }));
      const r = await fetch(A.cfg.url.replace(/\/$/, '') + '/ask', { method: 'POST', headers: { 'content-type': 'application/json' },
        body: JSON.stringify({ messages: history, city: S.city.id, ward: S.ward || null, mode: A.mode, code: code || undefined }) });
      const d = await r.json().catch(() => ({ error: `The assistant answered ${r.status}.` }));
      if (!r.ok || d.error) A.msgs.push({ role: 'assistant', error: d.error || `The assistant answered ${r.status}.` });
      else A.msgs.push({ role: 'assistant', content: d.answer, steps: d.steps, model: d.model, report: A.mode === 'report' });
    } catch (e) {
      A.msgs.push({ role: 'assistant', error: 'The assistant could not be reached. Check your connection and try again.' });
    }
    A.busy = false; $('#ask-send').disabled = false; renderThread();
  }
  $$('#ask-mode button').forEach(b => b.addEventListener('click', () => { A.mode = b.dataset.m; $$('#ask-mode button').forEach(x => x.setAttribute('aria-pressed', String(x === b))); }));
  $('#ask-form').addEventListener('submit', e => { e.preventDefault(); const q = $('#ask-q').value; $('#ask-q').value = ''; ask(q); });
  $('#ask-q').addEventListener('keydown', e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#ask-form').requestSubmit(); } });
  initAsk();
  boot();
})();
