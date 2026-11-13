"""BUG225 pure reference matching/ranking/filtering; no I/O or saved UI state."""
from __future__ import annotations

import re
import math
import spec_id

CONTRACT_VERSION = 1
_NUMERIC_TAIL = re.compile(r"^[0-9]+(?:-[0-9]+)*$")


def archive_observation(value):
    """Archive display observation only; never a performance/global clock."""
    if value is None:
        return None
    if type(value) not in (int, float):
        raise ValueError('archive observation must be finite genuine numeric UTC epoch seconds')
    try:
        value = float(value)
    except OverflowError as exc:
        raise ValueError('archive observation is outside the representable UTC epoch range') from exc
    if not math.isfinite(value):
        raise ValueError('archive observation must be finite genuine numeric UTC epoch seconds')
    return value


def _tokens(value, *, prefix=""):
    if value is None or value == "all":
        return None
    if not isinstance(value, (list, tuple, set, frozenset)) or any(not isinstance(x, str) for x in value):
        raise ValueError("facet must be all or an array of strings")
    return {x[len(prefix):] if prefix and x.startswith(prefix) else x for x in value}


def normalize_filters(filters=None):
    f = dict(filters or {})
    archive = f.get("include_archived", True)
    if type(archive) is not bool:
        raise ValueError("include_archived must be a boolean")
    project, version = f.get("project", ""), f.get("version", "all")
    if not isinstance(project, str) or not isinstance(version, str):
        raise ValueError("project/version must be strings")
    return {"project": project.upper(), "include_archived": archive,
            "archive_observed_at": archive_observation(f.get('archive_observed_at')),
            "statuses": _tokens(f.get("statuses")), "types": _tokens(f.get("types")),
            "version": version,
            "tags": _tokens(f.get("tags"))}


def _scope_parsed(parsed, project):
    # Nonconforming historical labels cannot name a registered project code;
    # keep them readable without widening valid foreign namespace admission.
    return (parsed is None or not parsed.code or parsed.code == project
            or spec_id.code_status(parsed.code) != 'ok')


def _scope(record, project):
    return _scope_parsed(spec_id.parse_id(record["id"].upper()), project)


def _prepare_query(query):
    upper = query.upper()
    return upper, query.lower(), spec_id.parse_id(upper), bool(_NUMERIC_TAIL.fullmatch(query))


def _tier_prepared(record, record_upper, parsed_record, prepared):
    upper, lower, parsed_query, numeric = prepared
    if numeric:
        return 1 if parsed_record and parsed_record.number == lower else None
    if parsed_query:
        if parsed_query.code:
            return 0 if upper == record_upper else None
        if parsed_record and parsed_record.kind == parsed_query.kind and parsed_record.number == parsed_query.number:
            return 0 if upper == record_upper else 1
        return None
    if lower in str(record.get("title", "")).lower() or upper == record_upper:
        return 0
    if lower in str(record.get("body", "")).lower():
        return 1
    return None


def _tier(record, query):
    record_upper = record["id"].upper()
    return _tier_prepared(record, record_upper, spec_id.parse_id(record_upper), _prepare_query(query))


def _eligible(record, f):
    if not f["include_archived"] and record.get("archived", False):
        return False
    if f["statuses"] is not None and record.get("status", "draft") not in f["statuses"]:
        return False
    if f["types"] is not None and (record.get("type") or "feature") not in f["types"]:
        return False
    version = record.get("version")
    if f["version"] == "unassigned":
        if version is not None:
            return False
    elif f["version"] != "all" and version != (f["version"][2:] if f["version"].startswith("v:") else f["version"]):
        return False
    if f["tags"] is not None:
        raw = record.get("tags")
        raw = [raw] if isinstance(raw, str) else raw if isinstance(raw, list) else []
        tags = {x for x in raw if isinstance(x, str) and x.strip()}
        selected = {x[2:] if x.startswith("t:") else x for x in f["tags"] if x != "untagged"}
        if not (tags & selected or (not tags and "untagged" in f["tags"])):
            return False
    return True


def search_records(records, query, filters=None, *, offset=0, limit=None):
    """Rank the full eligible set before paging; legacy hit fields are unchanged."""
    if not isinstance(query, str):
        raise ValueError("query must be a string")
    if type(offset) is not int or offset < 0 or (limit is not None and (type(limit) is not int or limit <= 0)):
        raise ValueError("offset/limit must be genuine nonnegative/positive integers")
    f, query = normalize_filters(filters), query.strip()
    matches = []
    if query:
        prepared = _prepare_query(query)
        for record in records:
            record_upper = record["id"].upper()
            parsed_record = spec_id.parse_id(record_upper)
            if _scope_parsed(parsed_record, f["project"]):
                tier = _tier_prepared(record, record_upper, parsed_record, prepared)
                if tier is not None:
                    matches.append((tier, record))
    eligible = [(tier, record) for tier, record in matches if _eligible(record, f)]
    eligible.sort(key=lambda pair: (pair[0], pair[1]["id"]))
    hits = []
    for _, record in eligible[offset:None if limit is None else offset + limit]:
        haystack = (record["id"] + " " + str(record.get("title", "")) + " " + str(record.get("body", ""))).lower()
        index = max(haystack.find(query.lower()), 0)
        hits.append({"id": record["id"], "title": record.get("title") or record["id"],
                     "status": record.get("status", "draft"),
                     "excerpt": "..." + haystack[max(0, index - 60):index + len(query) + 60] + "..."})
    scope = {key: sorted(value) if isinstance(value, set) else value for key, value in f.items()}
    return {"contract_version": CONTRACT_VERSION, "query": query, "scope": scope, "results": hits,
            "total": len(eligible), "matching_before_filters": len(matches), "excluded_by_filters": len(matches) - len(eligible),
            "offset": offset, "limit": limit, "has_more": offset + len(hits) < len(eligible)}


def javascript():
    """Static-export equivalent; tests compare both languages to frozen oracles."""
    import json
    pattern = re.sub(r'\(\?P<[^>]+>', '(', spec_id.LEGACY_ID_RE.pattern)
    return r'''
window.NightshiftSearch = (() => {
  const pattern = new RegExp(__ID_PATTERN__);
  const parse = id => { const m = String(id).toUpperCase().match(pattern); return m ? {kind:m[1],code:m[2].replace(/-$/, ''),number:m[3]} : null; };
  const points = (a,b) => {const x=Array.from(a),y=Array.from(b); for(let i=0;i<Math.min(x.length,y.length);i++){if(x[i]!==y[i])return x[i].codePointAt(0)-y[i].codePointAt(0);}return x.length-y.length;};
  function search(records, input, filters={}, offset=0, limit=null) {
    const q = input.trim(), upper=q.toUpperCase(), lower=q.toLowerCase(), pq=parse(q);
    const f={project:'',include_archived:true,archive_observed_at:null,statuses:null,types:null,version:'all',tags:null,...filters};
    if(f.archive_observed_at!==null&&(typeof f.archive_observed_at!=='number'||!Number.isFinite(f.archive_observed_at)))throw new Error('invalid archive observation');
    for(const key of ['statuses','types','tags'])if(f[key]==='all')f[key]=null;
    const matches=[];
    for(const r of q ? records : []) {
      const pr=parse(r.id);
      if(pr && pr.code && pr.code.split('-').length<=2 && pr.code.split('-').every(part=>new RegExp(__CODE_PART__).test(part)) && pr.code!==f.project.toUpperCase())continue;
      let tier=null;
      if(/^[0-9]+(?:-[0-9]+)*$/.test(q))tier=pr&&pr.number===q?1:null;
      else if(pq){if(pq.code)tier=upper===r.id.toUpperCase()?0:null;
        else if(pr&&pr.kind===pq.kind&&pr.number===pq.number)tier=upper===r.id.toUpperCase()?0:1;}
      else if(String(r.title||'').toLowerCase().includes(lower)||upper===r.id.toUpperCase())tier=0;
      else if(String(r.body||'').toLowerCase().includes(lower))tier=1;
      if(tier!==null)matches.push({tier,r});
    }
    const eligible=matches.filter(({r})=>{
      if(!f.include_archived&&r.archived)return false;
      if(f.statuses&&!f.statuses.includes(r.status||'draft'))return false;
      if(f.types&&!f.types.includes(r.type||'feature'))return false;
      if(f.version==='unassigned'){if(r.version!==null&&r.version!==undefined)return false;}
      else if(f.version!=='all'&&r.version!==(f.version.startsWith('v:')?f.version.slice(2):f.version))return false;
      if(f.tags){const raw=typeof r.tags==='string'?[r.tags]:Array.isArray(r.tags)?r.tags:[];
        const tags=raw.filter(t=>typeof t==='string'&&t.trim());
        if(!f.tags.some(t=>t==='untagged'?tags.length===0:tags.includes(t.startsWith('t:')?t.slice(2):t)))return false;}
      return true;
    }).sort((a,b)=>a.tier-b.tier||points(a.r.id,b.r.id));
    const results=eligible.slice(offset,limit===null?undefined:offset+limit).map(({r})=>{
      const h=(r.id+' '+(r.title||'')+' '+(r.body||'')).toLowerCase(),i=Math.max(0,h.indexOf(lower));
      return {id:r.id,title:r.title||r.id,status:r.status||'draft',excerpt:'...'+h.slice(Math.max(0,i-60),i+q.length+60)+'...'};
    });
    return {contract_version:1,query:q,scope:f,results,total:eligible.length,matching_before_filters:matches.length,excluded_by_filters:matches.length-eligible.length,offset,limit,has_more:offset+results.length<eligible.length};
  }
  return {search};
})();
'''.replace('__ID_PATTERN__', json.dumps(pattern)).replace('__CODE_PART__', json.dumps(spec_id._CODE_SEGMENT_RE.pattern))
