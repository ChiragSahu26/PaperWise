from pathlib import Path
import json, sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.main import app
path = Path(__file__).resolve().parents[1] / 'openapi.json'
path.write_text(json.dumps(app.openapi(), indent=2) + '\n')
print(path)
