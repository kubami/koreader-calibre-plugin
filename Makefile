version = 0.1.0-alpha
zip_file = releases/KOReader Sync v$(version).zip
zip_contents = *.py LICENSE *.md *.txt images/*.png

all: zip

dependencies:
	@ wget -N https://github.com/SirAnthony/slpp/raw/master/slpp.py

zip:
	@ echo "creating new $(zip_file)" && zip "$(zip_file)" $(zip_contents) && echo "created new $(zip_file)"
