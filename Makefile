.PHONY: bootstrap-predictor

bootstrap-predictor:
	@if [ -f cooldown_v5/predictor_model.json ]; then \
		mkdir -p data/cooldown_model && \
		cp cooldown_v5/predictor_model.json data/cooldown_model/ && \
		echo "Predictor model bootstrapped from cooldown_v5/"; \
	else \
		echo "ERROR: cooldown_v5/predictor_model.json not found"; \
		exit 1; \
	fi
