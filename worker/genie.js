// Canada Insight research assistant: a small Cloudflare Worker that holds the Claude key, so the browser never sees it.
//
// POST /ask  { messages: [{role, content}], city, ward, mode: 'quick' | 'thorough' | 'report', code? }
//   -> { answer, steps, model, usage }
//
// The assistant answers only from data it reads in this request: the platform's published files (dashboard,
// amenities, sources, quality) and the city's open data portal (search the catalogue, read a dataset's columns,
// run a query). It must cite every figure and say when a question can't be answered reliably.
//
// Secrets and settings (wrangler.toml / `wrangler secret put`):
//   ANTHROPIC_API_KEY  the Claude key (secret)
//   ACCESS_CODE        optional: when set, requests must carry this code (secret)
//   SITE_ORIGIN        the website's origin, for CORS (e.g. https://hassanaliarshad110.github.io)
//   SITE_DATA          the published data folder (e.g. https://hassanaliarshad110.github.io/canada-insight/data/)
//   DAILY_LIMIT_IP     questions per visitor per day (default 30); DAILY_LIMIT_ALL for everyone (default 600)
//   LIMITS             a KV namespace for the daily counters (optional; without it, no limits are kept)

const API = 'https://api.anthropic.com/v1/messages';
const MODELS = { quick: 'claude-haiku-5-5', thorough: 'claude-sonnet-5-5', report: 'claude-sonnet-5-5' };
const MAX_STEPS = { quick: 8, thorough: 14, report: 20 };
const PORTALS = { calgary: 'https://data.calgary.ca', edmonton: 'https://data.edmonton.ca' };

const SYSTEM = (city, ward, mode) => `You are the research assistant of Canada Insight, an independent civic research site by Hassan Ali, \
currently looking at ${city}${ward ? `, ${/^\d+$/.test(ward) ? 'Ward ' + ward : ward + ' Ward'}` : ''}.

Rules you never break:
- State a number only if you read it in this conversation with a tool. Never estimate, recall or invent a statistic.
- Say where every figure comes from (dataset name and ID, or the platform file) and its period, in the same sentence or a source list.
- Show the calculation when you derive a figure (rates, changes, shares).
- Separate facts (what the data says) from interpretation (what it might mean). Mark interpretation as such.
- Never imply that one thing causes another because they move together.
- If the data can't answer the question reliably, say so plainly, say why, and say what data would be needed.
- Use the platform's own figures first (get_platform_data); query the open data portal only when they don't cover the question.
- Before saying the city has no data on a topic, search the catalogue with at least two different wordings.
- Present findings, not recommendations to elected officials; you may list options for further investigation.
- Write plainly for residents, journalists and staff. Name the area of every figure.
${mode === 'report' ? `
Write a structured research report in Markdown with these sections, in order: Research question; Executive summary;
Methodology; Data sources and collection dates; Geographic scope; Findings; Supporting statistics (a table);
Limitations; Alternative explanations; Options for further investigation; Reproducibility (every dataset ID, filter and
query used). Every finding must be traceable to a figure you read.` : 'Keep answers short: a direct answer first, then the figures and sources.'}`;

const TOOLS = [
  { name: 'get_platform_data', description: 'Read a file the platform publishes for this city. dashboard: city and ward figures (311, safety, families, development, population, tax) for each way of counting residents. access: amenity access, crowding and scores by community and ward. sources: every dataset used, with dates. quality: data quality checks.',
    input_schema: { type: 'object', properties: { file: { type: 'string', enum: ['dashboard', 'access', 'sources', 'quality'] },
      ward: { type: 'integer', description: 'Optional ward number to narrow the result' } }, required: ['file'] } },
  { name: 'search_datasets', description: "Search the city's open data catalogue. Returns dataset IDs, names, descriptions and last update dates.",
    input_schema: { type: 'object', properties: { query: { type: 'string' } }, required: ['query'] } },
  { name: 'describe_dataset', description: "A dataset's columns, row count, description and last update.",
    input_schema: { type: 'object', properties: { id: { type: 'string', description: 'e.g. iahh-g8bj' } }, required: ['id'] } },
  { name: 'query_dataset', description: 'Run a SoQL query on a dataset (select, where, group, order, limit; at most 1,000 rows returned). Use aggregates (count(*), sum(), avg()) rather than raw rows.',
    input_schema: { type: 'object', properties: { id: { type: 'string' }, select: { type: 'string' }, where: { type: 'string' },
      group: { type: 'string' }, order: { type: 'string' }, limit: { type: 'integer' } }, required: ['id'] } },
  { name: 'calculate', description: 'Evaluate an arithmetic expression exactly (+ - * / parentheses and numbers only).',
    input_schema: { type: 'object', properties: { expression: { type: 'string' } }, required: ['expression'] } },
];

function cors(env, extra = {}) {
  return { 'Access-Control-Allow-Origin': env.SITE_ORIGIN || '*', 'Access-Control-Allow-Methods': 'POST, OPTIONS',
           'Access-Control-Allow-Headers': 'content-type', 'Vary': 'Origin', ...extra };
}
const json = (env, body, status = 200) => new Response(JSON.stringify(body), { status, headers: cors(env, { 'content-type': 'application/json' }) });

function trim(v, max = 12000) {
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  return s.length > max ? s.slice(0, max) + `… [cut: ${s.length - max} more characters; narrow the request]` : s;
}

async function runTool(name, input, ctx) {
  const portal = PORTALS[ctx.city];
  try {
    if (name === 'calculate') {
      if (!/^[\d\s+\-*/().,eE]+$/.test(input.expression || '')) return 'Only numbers and + - * / ( ) are allowed.';
      // eslint-disable-next-line no-new-func
      return String(Function(`"use strict"; return (${input.expression.replace(/,/g, '')});`)());
    }
    if (name === 'get_platform_data') {
      const file = { dashboard: 'dashboard.json', access: 'access.json', sources: 'sources.json', quality: 'quality.json' }[input.file];
      const r = await fetch(`${ctx.env.SITE_DATA}${ctx.city}/${file}`, { cf: { cacheTtl: 600 } });
      if (!r.ok) return `Could not read ${file} (${r.status}).`;
      let d = await r.json();
      const w = input.ward;
      if (input.file === 'dashboard') {
        d = { source: d.source, read_at: d.read_at, default_method: d.default_method, methods: Object.fromEntries(Object.entries(d.methods).map(([k, m]) =>
          [k, { label: m.label, period: m.period, crime_period: m.crime_period, note: m.note, city: m.city,
                wards: w ? m.wards.filter(x => +x.ward === +w) : m.wards }])), tax_by_ward: d.tax && (w ? { [w]: d.tax.by_ward[w] } : d.tax.by_ward) };
      } else if (input.file === 'access') {
        const areas = w ? Object.fromEntries(Object.entries(d.areas).filter(([, a]) => +a.ward === +w)) : d.areas;
        const brief = Object.fromEntries(Object.entries(areas).map(([c, a]) => [c, { name: a.name, ward: a.ward, homes: a.units,
          within_first_distance: Object.fromEntries(Object.entries(a.access).filter(([k]) => !k.includes('|')).map(([k, s]) => [k, s.share_primary])),
          score: d.scores && d.scores.areas[c] ? { overall: d.scores.areas[c].overall, groups: d.scores.areas[c].groups } : null }]));
        d = { built_at: d.built_at, kinds: d.kinds, city_access: d.city_access, wards: w ? { [w]: d.wards[w] } : d.wards,
              ward_scores: d.scores && Object.fromEntries(Object.entries(d.scores.areas).filter(([k]) => k.startsWith('ward:'))), communities: brief,
              method: 'Share of homes within walking distance; crowding = amenity within reach per person sharing it; score = crowding / city level.' };
      }
      return trim(d, 30000);
    }
    if (!portal) return 'No open data portal is configured for this city.';
    if (name === 'search_datasets') {
      const u = `${portal}/api/catalog/v1?` + new URLSearchParams({ domains: new URL(portal).host, search_context: new URL(portal).host, q: input.query, limit: '12' });
      const d = await (await fetch(u)).json();
      return trim((d.results || []).filter(x => x.resource && x.resource.type === 'dataset').map(x => ({ id: x.resource.id, name: x.resource.name,
        updated: (x.resource.data_updated_at || x.resource.updatedAt || '').slice(0, 10), description: (x.resource.description || '').slice(0, 300) })));
    }
    if (name === 'describe_dataset') {
      const m = await (await fetch(`${portal}/api/views/${encodeURIComponent(input.id)}.json`)).json();
      return trim({ id: input.id, name: m.name, description: (m.description || '').slice(0, 800),
        updated: m.rowsUpdatedAt ? new Date(m.rowsUpdatedAt * 1000).toISOString().slice(0, 10) : null,
        columns: (m.columns || []).map(c => ({ field: c.fieldName, name: c.name, type: c.dataTypeName })), page: `${portal}/d/${input.id}` });
    }
    if (name === 'query_dataset') {
      const q = {};
      for (const k of ['select', 'where', 'group', 'order']) if (input[k]) q['$' + k] = input[k];
      q.$limit = String(Math.min(input.limit || 100, 1000));
      const r = await fetch(`${portal}/resource/${encodeURIComponent(input.id)}.json?` + new URLSearchParams(q));
      const t = await r.text();
      return r.ok ? trim(t) : `Query failed (${r.status}): ${t.slice(0, 400)}`;
    }
    return `Unknown tool ${name}.`;
  } catch (e) {
    return `Tool error: ${String(e).slice(0, 300)}`;
  }
}

async function overLimit(env, ip) {
  if (!env.LIMITS) return null;
  const day = new Date().toISOString().slice(0, 10);
  const per = +(env.DAILY_LIMIT_IP || 30), all = +(env.DAILY_LIMIT_ALL || 600);
  const kIp = `ip:${day}:${ip}`, kAll = `all:${day}`;
  const [nIp, nAll] = await Promise.all([env.LIMITS.get(kIp), env.LIMITS.get(kAll)]);
  if (+nIp >= per) return `You've reached today's limit of ${per} questions. It resets at midnight UTC.`;
  if (+nAll >= all) return 'The assistant has reached its daily limit for all visitors. Please try again tomorrow.';
  await Promise.all([env.LIMITS.put(kIp, String(+nIp + 1), { expirationTtl: 172800 }), env.LIMITS.put(kAll, String(+nAll + 1), { expirationTtl: 172800 })]);
  return null;
}

export default {
  async fetch(request, env) {
    if (request.method === 'OPTIONS') return new Response(null, { headers: cors(env) });
    const url = new URL(request.url);
    if (url.pathname === '/health') return json(env, { ok: true, key: !!env.ANTHROPIC_API_KEY, code: !!env.ACCESS_CODE });
    if (request.method !== 'POST' || url.pathname !== '/ask') return json(env, { error: 'Not found' }, 404);
    if (!env.ANTHROPIC_API_KEY) return json(env, { error: 'The assistant is not set up yet (no key on the server).' }, 503);
    let body;
    try { body = await request.json(); } catch { return json(env, { error: 'Send JSON.' }, 400); }
    if (env.ACCESS_CODE && body.code !== env.ACCESS_CODE) return json(env, { error: 'The access code is missing or wrong.' }, 401);
    const limited = await overLimit(env, request.headers.get('cf-connecting-ip') || 'unknown');
    if (limited) return json(env, { error: limited }, 429);
    const mode = MODELS[body.mode] ? body.mode : 'quick';
    const city = PORTALS[body.city] ? body.city : 'calgary';
    const ward = (typeof body.ward === 'string' || typeof body.ward === 'number') && /^[\p{L}\p{N} '’.-]{1,40}$/u.test(String(body.ward)) ? String(body.ward) : null;
    const messages = (body.messages || []).slice(-12).filter(m => (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string')
      .map(m => ({ role: m.role, content: m.content.slice(0, 4000) }));
    if (!messages.length || messages[messages.length - 1].role !== 'user') return json(env, { error: 'Ask a question.' }, 400);

    const ctx = { env, city };
    const steps = [];
    const usage = { input_tokens: 0, output_tokens: 0 };
    for (let i = 0; i < MAX_STEPS[mode]; i++) {
      const r = await fetch(API, {
        method: 'POST',
        headers: { 'x-api-key': env.ANTHROPIC_API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
        body: JSON.stringify({ model: MODELS[mode], max_tokens: mode === 'report' ? 8000 : 2500, system: SYSTEM(city, ward, mode), tools: TOOLS, messages }),
      });
      if (!r.ok) return json(env, { error: `The AI service answered ${r.status}. Try again in a minute.`, detail: (await r.text()).slice(0, 300) }, 502);
      const out = await r.json();
      usage.input_tokens += out.usage?.input_tokens || 0;
      usage.output_tokens += out.usage?.output_tokens || 0;
      messages.push({ role: 'assistant', content: out.content });
      const calls = out.content.filter(c => c.type === 'tool_use');
      if (out.stop_reason !== 'tool_use' || !calls.length) {
        const answer = out.content.filter(c => c.type === 'text').map(c => c.text).join('\n\n');
        return json(env, { answer, steps, model: MODELS[mode], usage });
      }
      const results = [];
      for (const c of calls) {
        steps.push({ tool: c.name, input: c.input });
        results.push({ type: 'tool_result', tool_use_id: c.id, content: await runTool(c.name, c.input, ctx) });
      }
      messages.push({ role: 'user', content: results });
    }
    return json(env, { error: 'The question needed more steps than allowed. Try narrowing it, or use Thorough or Report.', steps }, 422);
  },
};
