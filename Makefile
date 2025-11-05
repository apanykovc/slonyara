.PHONY: install run

install:
	python -m pip install --upgrade pip
	python -m pip install -r requirements.txt

run:
	bash -c 'set -a && source .env && python -m slonyara run'
