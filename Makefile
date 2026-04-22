.PHONY: all ci fix-plr check-plr lint fix format format-check typecheck

# Fa tutto: fix, format, typecheck
all: fix format typecheck

# Solo il "check" completo senza modificare nulla (ideale per CI/CD)
ci: lint format-check typecheck

# Cerca i metodi che non usano 'self' e li converte automaticamente in @staticmethod
fix-plr:
	uvx ruff check src \
		--select PLR6301 \
		--preview \
		--fix \
		--unsafe-fixes

# Verifica che non ci siano più metodi da convertire in @staticmethod (deve stampare "All checks passed!")
check-plr:
	uvx ruff check src \
		--select PLR6301 \
		--preview

# Controlla tutto il codice senza modificare nulla (utile in CI)
lint:
	uvx ruff check src

# Applica tutti i fix automatici sicuri
fix:
	uvx ruff check src --fix

# Formatta il codice (stile black)
format:
	uvx ruff format src

# Controlla la formattazione senza modificare (utile in CI)
format-check:
	uvx ruff format src --check

# Controlla i tipi con mypy
typecheck:
	uvx mypy src