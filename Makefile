.PHONY: install run test openapi eval
install:
	python -m pip install -e '.[test]'
run:
	uvicorn app.main:app --host 127.0.0.1 --port 8000
test:
	pytest -q
openapi:
	python scripts/make_openapi.py
eval:
	python scripts/run_evaluation.py --compare-modes --questions tests/eval/questions.json --k 5
