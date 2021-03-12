#!/bin/sh

## !!!! THIS IS THE STARTUP SCRIPT FOR THE PRODUCTION SERVER !!!!

if [ -d ./env ]; then
	python -m venv env

	. env/bin/activate

	pip3 install -r requirements.txt

	deactivate
fi

. env/bin/activate

python bot.py

deactivate
