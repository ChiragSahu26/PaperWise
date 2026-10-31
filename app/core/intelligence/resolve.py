"""Metadata resolution and transparent evidence scoring."""
import asyncio, json, re
from datetime import datetime,timezone,date
from difflib import SequenceMatcher
from urllib.parse import quote
from app.core.intelligence import online
from app.db.session import connect
from app.jobs.queue import now
import config

S2_FIELDS='title,year,venue,publicationDate,citationCount,influentialCitationCount,externalIds,authors,openAccessPdf,publicationTypes'

def normalized(text):return ' '.join(re.findall(r'[a-z0-9]+',(text or '').lower()))
def s2_headers():return {'x-api-key':config.SEMANTIC_SCHOLAR_KEY} if config.SEMANTIC_SCHOLAR_KEY else {}
def arxiv_id(value):return re.sub(r'^arxiv\s*:\s*','',value or '',flags=re.I).strip()

def age(date_str):
    if not date_str:return None
    try:days=(date.today()-date.fromisoformat(date_str[:10])).days
    except (TypeError,ValueError):return None
    years=max(0,days/365.2425)
    return 'new' if years<1 else 'recent' if years<3 else 'established' if years<7 else 'older'

def evidence(total,influential,published,kind,retracted):
    parts=[]
    rate=None
    if total is not None and published:
        try: years=max(1,(date.today()-date.fromisoformat(published[:10])).days/365.2425)
        except (ValueError,TypeError): years=None
        if years is not None: rate=total/years
    level=None if rate is None else 'low' if rate<5 else 'medium' if rate<50 else 'high'
    parts.append({'name':'age_adjusted_citations','level':level,'value':f'{rate:.1f} per year' if rate is not None else None,
                  'note':'Total citations divided by at least one year since publication.' if rate is not None else 'Citation count or exact publication date unavailable.'})
    ratio=influential/max(1,total) if influential is not None and total is not None else None
    level=None if ratio is None else 'low' if ratio<.05 else 'high' if ratio>=.15 else 'medium'
    parts.append({'name':'influential_ratio','level':level,'value':ratio,'note':'Influential citations divided by total citations.' if ratio is not None else 'Influential or total citation count unavailable.'})
    reviewed=(kind in ('journal','conference')) if kind in ('journal','conference','preprint') else None
    parts.append({'name':'peer_review','level':('high' if reviewed else 'low') if reviewed is not None else None,'value':reviewed,
                  'note':'Based on publication type, not an independent review assessment.'})
    parts.append({'name':'retraction','level':('low' if retracted else 'medium') if retracted is not None else None,'value':retracted,
                  'note':'Retraction overrides the overall level when reported.'})
    levels=[p['level'] for p in parts if p['level'] is not None]
    overall='low' if retracted is True or levels.count('low')>=2 else 'high' if levels.count('high')>=2 and 'low' not in levels else 'medium'
    return {'level':overall if levels else None,'parts':parts,'note':'A guide, not a verdict on quality.'}

def offline(row):
    with connect() as db:
        first=db.execute("SELECT text FROM chunks WHERE doc_id=? AND type='text' ORDER BY segment_index,chunk_index LIMIT 1",(row['id'],)).fetchone()
    match=re.search(r'(?i)\b(?:published|publication date)\s*[: -]\s*(\d{4}-\d{2}-\d{2})\b',first[0] if first else '')
    published=match.group(1) if match else None
    return {'online':False,'identified':bool(row['doi'] or row['arxiv_id']),'title':row['title'],
            'authors':json.loads(row['authors_json'] or '[]'),'doi':row['doi'],'arxiv_id':row['arxiv_id'],
            'venue':None,'type':None,'published':published,'age_bucket':age(published),'citations':None,'retraction':None,
            'code':None,'trending':None,'evidence_strength':None,'sources':[],'fetched_at':None}

async def optional(url,**kwargs):
    try:return await online.get_json(url,**kwargs)
    except (Exception,):return None

async def intelligence(row,refresh=False):
    local=offline(row)
    if not online.enabled():return local
    doi=row['doi']; arxiv=arxiv_id(row['arxiv_id']); s2=None
    params={'fields':S2_FIELDS};heads=s2_headers()
    if not doi and not arxiv and row['title']:
        search=await optional('https://api.semanticscholar.org/graph/v1/paper/search',params={'query':row['title'],'limit':3,'fields':S2_FIELDS},headers=heads,refresh=refresh)
        for candidate in (search or {}).get('data',[]):
            if SequenceMatcher(None,normalized(row['title']),normalized(candidate.get('title'))).ratio()>=.9:
                s2=candidate;break
        if s2:
            ext=s2.get('externalIds') or {};doi=ext.get('DOI');arxiv=ext.get('ArXiv') or ''
    if not doi and not arxiv and not s2:return {**local,'online':True,'identified':False}
    url_s2='https://api.semanticscholar.org/graph/v1/paper/'+quote(('DOI:'+doi) if doi else ('ARXIV:'+arxiv),safe=':/') if (doi or arxiv) else None
    oparams={'api_key':config.OPENALEX_API_KEY} if config.OPENALEX_API_KEY else {}
    crossparams={'mailto':config.CONTACT_EMAIL} if config.CONTACT_EMAIL else {}
    tasks=[]
    if not s2 and url_s2:tasks.append(('s2',optional(url_s2,params=params,headers=heads,refresh=refresh)))
    if doi:
        tasks.extend([('oa',optional('https://api.openalex.org/works/doi:'+quote(doi,safe=''),params=oparams,refresh=refresh)),
                      ('cr',optional('https://api.crossref.org/works/'+quote(doi,safe=''),params=crossparams,refresh=refresh)),
                      ('notices',optional('https://api.crossref.org/works',params={**crossparams,'filter':'updates:'+doi+',update-type:retraction','rows':3},refresh=refresh))])
    resolved=dict(zip([k for k,_ in tasks],await asyncio.gather(*(f for _,f in tasks))))
    s2=s2 or resolved.get('s2') or {}; oa=resolved.get('oa') or {};cr=(resolved.get('cr') or {}).get('message') or {}
    if not s2 and not oa and not cr:return local
    ext=s2.get('externalIds') or {};arxiv=arxiv or ext.get('ArXiv') or '';doi=doi or ext.get('DOI')
    published=s2.get('publicationDate') or oa.get('publication_date')
    if not published and s2.get('year'):published=str(s2['year'])
    if not published:
        d=((cr.get('published') or {}).get('date-parts') or [[]])[0]
        if d:published='-'.join([str(d[0])]+[f'{x:02d}' for x in d[1:3]])
    typetext=' '.join([str(oa.get('type') or ''),str(cr.get('type') or ''),' '.join(s2.get('publicationTypes') or [])]).lower()
    kind='conference' if 'conference' in typetext or 'proceedings' in typetext else 'journal' if 'journal' in typetext or 'article' in typetext else 'preprint' if 'preprint' in typetext or arxiv else None
    by_year={str(x['year']):x.get('cited_by_count',0) for x in oa.get('counts_by_year',[]) if 'year' in x}
    recent=sum(by_year.get(str(y),0) for y in (date.today().year,date.today().year-1)) if by_year else None
    total=s2.get('citationCount') if s2.get('citationCount') is not None else oa.get('cited_by_count')
    influential=s2.get('influentialCitationCount')
    notices=((resolved.get('notices') or {}).get('message') or {}).get('items',[])
    # Production Crossref reports updates on the original work in updated-by.
    updated=[x for x in cr.get('updated-by',[]) if x.get('type','').lower()=='retraction']
    retracted=oa.get('is_retracted') if 'is_retracted' in oa else None
    if notices or updated:retracted=True
    notice=(updated or notices or [{}])[0]
    notice_url='https://doi.org/'+notice['DOI'] if notice.get('DOI') else None
    venue=s2.get('venue') or ((oa.get('primary_location') or {}).get('source') or {}).get('display_name') or next(iter(cr.get('container-title') or []),None)
    authors=[a['name'] for a in s2.get('authors',[]) if a.get('name')] or local['authors']
    sources=[]
    if s2:sources.append({'name':'Semantic Scholar','url':s2.get('url') or ('https://www.semanticscholar.org/paper/'+s2['paperId'] if s2.get('paperId') else url_s2)})
    if oa:sources.append({'name':'OpenAlex','url':oa.get('id')})
    if cr:sources.append({'name':'Crossref','url':'https://doi.org/'+doi})
    # Only repository names from the first three pages and last page are sent, never text.
    with connect() as db:
        texts=[r[0] for r in db.execute("SELECT text FROM chunks WHERE doc_id=? AND type='text' AND (page IS NULL OR page<=3 OR page=?)",(row['id'],row['page_count']))]
    repos=[]
    for match in re.findall(r'https?://github\.com/([\w.-]+)/([\w.-]+)', '\n'.join(texts),re.I):
        repo=(match[0],match[1].rstrip('.').removesuffix('.git'))
        if repo not in repos:repos.append(repo)
    github_headers={'Authorization':'Bearer '+config.GITHUB_TOKEN} if config.GITHUB_TOKEN else {}
    async def code(owner,repo):
        response=await optional('https://api.github.com/repos/'+quote(owner,safe='')+'/'+quote(repo,safe=''),headers=github_headers,refresh=refresh)
        return {'url':'https://github.com/'+owner+'/'+repo,'stars':response.get('stargazers_count') if response else None,'last_commit':(response.get('pushed_at') or '')[:10] or None if response else None}
    entries=await asyncio.gather(*(code(a,b) for a,b in repos[:20]))
    hf=None
    if arxiv:
        try:
            await online.get_json('https://huggingface.co/api/papers/'+quote(arxiv,safe=''),refresh=refresh)
            hf=True
        except online.OnlineNotFound: hf=False
        except Exception: hf=None
    result={'online':True,'identified':True,'title':s2.get('title') or oa.get('title') or local['title'],'authors':authors,'doi':doi,
       'arxiv_id':('arXiv:'+arxiv) if arxiv else None,'venue':venue,'type':kind,'published':published,'age_bucket':age(published),
       'citations':{'total':total,'influential':influential,'last_12_months':recent,'by_year':by_year or None},
       'retraction':{'retracted':retracted,'notice_url':notice_url},'code':entries,'trending':{'huggingface':hf},
       'evidence_strength':evidence(total,influential,published,kind,retracted),'sources':sources,'fetched_at':now()}
    if by_year and result['evidence_strength']['parts']:
        result['evidence_strength']['parts'][0]['note']+=' Recent citations sum the current and previous calendar years, not a rolling 12 months.'
    return result
