"""Opt-in live acceptance check. Sends only a DOI and title to public services."""
import json,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import config
from fastapi.testclient import TestClient
from app.main import app
from app.db.session import connect
from app.jobs.queue import now

def main():
    with tempfile.TemporaryDirectory(prefix='paperwise-live-check-') as temp:
        config.DATA_DIR=Path(temp)
        with TestClient(app) as client:
            with connect() as db:
                db.execute('INSERT INTO documents(id,filename,file_path,file_type,status,title,authors_json,doi,added_at) VALUES (?,?,?,?,?,?,?,?,?)',
                           ('live','paper.pdf','/not-read','pdf','ready','Nanometer scale thermometry in a living cell','[]','10.1038/nature12373',now()))
            offline=client.get('/api/v1/documents/live/intelligence').json()
            assert offline['online'] is False
            client.put('/api/v1/settings',json={'online_lookups':True})
            response=client.get('/api/v1/documents/live/intelligence?refresh=true')
            response.raise_for_status();data=response.json()
            keys={'online','identified','title','authors','venue','type','published','age_bucket','citations','retraction','code','trending','evidence_strength','sources','fetched_at'}
            assert keys<=data.keys() and data['online'] and data['identified']
            assert {p['name'] for p in data['evidence_strength']['parts']}=={'age_adjusted_citations','influential_ratio','peer_review','retraction'}
            print(json.dumps({'offline_check':True,'doi':'10.1038/nature12373','online':data['online'],'sources':data['sources'],
                              'citations':data['citations'],'evidence_strength':data['evidence_strength']},indent=2))
            missing=[p['name'] for p in data['evidence_strength']['parts'] if p['value'] is None]
            if missing:print('Provider data not available for:',', '.join(missing),file=sys.stderr)
if __name__=='__main__':main()
